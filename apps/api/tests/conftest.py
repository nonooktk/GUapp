"""テスト共通フィクスチャ。設定は環境変数で直接与える（.env は使わない）。"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import AsyncIterator, Callable
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import reset_engine_cache
from tests.recording_mail import RecordingMailAdapter

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
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_SSL_CA_PATH",
    "PUBLIC_WEB_BASE_URL",
    "DEMO_EMAIL_DOMAINS",
    "SEED_MEMBER_PASSWORD",
    # F-029 AI アシスタント（P2 追補d 8.1）。手元の環境変数・.env でキーが有効にならないよう必ず消す
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_REASONING_EFFORT",
    "OPENAI_TIMEOUT_SECONDS",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "LLM_PROVIDER",
    "LLM_STUB_SCENARIO",
    "CHAT_ENABLED",
    "CHAT_DAILY_LIMIT",
    "CHAT_IP_LIMIT_PER_HOUR",
    "CHAT_TURN_LIMIT",
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
            # キー無し（空）・自動選択を既定にする。.env に実キーがあっても CI と同じ挙動になる
            "OPENAI_API_KEY": "",
            "LLM_PROVIDER": "auto",
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


@pytest.fixture
def recording_mail() -> RecordingMailAdapter:
    """記録用メールアダプタ。`recording_mail.install(app)` で app に差し替える（設計 4.10）。"""
    return RecordingMailAdapter()


def _allowed_connect_hosts() -> set[str]:
    """外へ出てよい接続先。ループバックと、結合テスト用 DB（`DATABASE_URL_TEST`）のホスト。"""
    hosts = {"127.0.0.1", "::1"}
    url = os.environ.get("DATABASE_URL_TEST", "")
    host = urlsplit(url).hostname if url else None
    if host:
        try:
            hosts |= {str(info[4][0]) for info in socket.getaddrinfo(host, None)}
        except OSError:
            pass
    return hosts


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """テストは外部ネットワークに出ない（P2 追補d テスト設計 1 章 #3・DS-DEC-105）。

    `socket.socket.connect` を、接続先がループバック（127.0.0.1／::1）と結合テスト用 DB 以外なら
    例外にする。OpenAI（api.openai.com）へ誤って届く経路があれば、ここで落ちる。
    """
    real_connect = socket.socket.connect
    allowed = _allowed_connect_hosts()

    def guarded(self: socket.socket, address: object) -> None:
        if isinstance(address, tuple) and address:
            host = str(address[0])
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = host == "localhost"
            if not is_loopback and host not in allowed:
                raise ConnectionRefusedError(f"テスト中の外部接続は禁止です: {host}")
        return real_connect(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded)
