"""F-029 結合テストの共通ヘルパー（P2 追補d テスト設計 4.1）。

- `ChatCtx`（フィクスチャ `chat_ctx` は conftest.py）: 本物の MySQL（guapp_test）＋ seed ＋
  台本つきのアダプタを差し込める app
- 台本つきのアダプタは `app.dependency_overrides[get_llm_adapter]` で差し替える（DS-DEC-105）
- 実際の OpenAI は呼ばない。ネットワークは conftest の `no_external_network` で遮断済み
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.llm import LLMAdapter, get_llm_adapter
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}
MESSAGES_URL = "/api/v1/chat/messages"
STATUS_URL = "/api/v1/chat/status"


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class ChatCtx:
    """1 つのテストで使う app・クライアント・DB エンジンの束。"""

    engine: AsyncEngine
    _make_app: Callable[..., FastAPI]
    _client_factory: Callable[[FastAPI], httpx.AsyncClient]
    database_url: str

    def build(
        self, adapter: LLMAdapter | None = None, **env: str | None
    ) -> tuple[FastAPI, httpx.AsyncClient]:
        """設定を与えて app を作る。`adapter` があれば台本つきのアダプタに差し替える。"""
        env.setdefault("APP_ENV", "test")
        app = self._make_app(DATABASE_URL=self.database_url, **env)
        if adapter is not None:
            app.dependency_overrides[get_llm_adapter] = lambda: adapter
        return app, self._client_factory(app)

    async def scalar(self, sql: str, **params: Any) -> Any:
        async with self.engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar_one()

    async def rows(self, sql: str, **params: Any) -> list[tuple]:
        async with self.engine.connect() as conn:
            return [tuple(r) for r in (await conn.execute(text(sql), params)).all()]

    async def execute(self, sql: str, **params: Any) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def published_ids(self) -> list[int]:
        return [
            r[0] for r in await self.rows("SELECT id FROM products WHERE published=1 ORDER BY id")
        ]

    async def product_id_by_name(self, fragment: str) -> int:
        return int(
            await self.scalar("SELECT id FROM products WHERE name LIKE :n", n=f"%{fragment}%")
        )

    async def counts(self) -> dict[str, int]:
        return {
            "sessions": await self.scalar("SELECT COUNT(*) FROM chat_sessions"),
            "messages": await self.scalar("SELECT COUNT(*) FROM chat_messages"),
            "user_messages": await self.scalar(
                "SELECT COUNT(*) FROM chat_messages WHERE role='user'"
            ),
        }


async def send(
    client: httpx.AsyncClient,
    message: Any = "黒のパーカーが欲しいです",
    *,
    token: str | None = None,
    product_id: Any = None,
    ip: str | None = None,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    """`POST /chat/messages`。`body` を渡すと本文をそのまま使う（入力検証の確認用）。"""
    h = dict(HEADERS if headers is None else headers)
    if token is not None:
        h["X-Chat-Token"] = token
    if ip is not None:
        h["X-Forwarded-For"] = ip
    payload = body if body is not None else {"message": message}
    if body is None and product_id is not None:
        payload["product_id"] = product_id
    return await client.post(MESSAGES_URL, json=payload, headers=h)


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)
