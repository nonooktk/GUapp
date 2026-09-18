"""テスト共通フィクスチャ。設定は環境変数で直接与える（.env は使わない）。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import reset_engine_cache

# テスト用のダミー値（実在しない）。秘匿値ではない
TEST_INTERNAL_TOKEN = "test-internal-token-0123456789"
TEST_ORIGIN = "http://localhost:3000"
SQLITE_MEMORY_URL = "sqlite+aiosqlite:///:memory:"

_SETTING_KEYS = (
    "APP_ENV",
    "DATABASE_URL",
    "INTERNAL_TOKEN",
    "CORS_ALLOW_ORIGIN",
    "PAYMENT_STUB_RESULT",
    "IMAGE_BASE_URL",
    "TEST_RESERVE_DELAY_MS",
)


def _reset_caches() -> None:
    get_settings.cache_clear()
    reset_engine_cache()


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """環境変数を差し替えて設定キャッシュを捨てる。"""

    def _apply(**env: str | None) -> None:
        for key in _SETTING_KEYS:
            monkeypatch.delenv(key, raising=False)
        defaults: dict[str, str] = {
            "APP_ENV": "test",
            "DATABASE_URL": SQLITE_MEMORY_URL,
            "INTERNAL_TOKEN": TEST_INTERNAL_TOKEN,
            "CORS_ALLOW_ORIGIN": TEST_ORIGIN,
        }
        defaults.update({k: v for k, v in env.items() if v is not None})
        for key, value in defaults.items():
            monkeypatch.setenv(key, value)
        _reset_caches()

    yield _apply
    _reset_caches()


@pytest.fixture
def make_app(app_env: Callable[..., None]) -> Callable[..., FastAPI]:
    """環境変数を与えて `create_app()` を作る。"""

    def _make(**env: str | None) -> FastAPI:
        app_env(**env)
        from app.main import create_app

        return create_app()

    return _make


@pytest.fixture
async def client_factory() -> AsyncIterator[Callable[[FastAPI], httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []

    def _factory(app: FastAPI) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
        clients.append(client)
        return client

    yield _factory
    for client in clients:
        await client.aclose()
