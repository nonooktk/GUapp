"""integration 共通。安全装置（プラン 4.5 #4、テスト設計書 1.4 #3）:

1. `DATABASE_URL_TEST` が無ければ全件 skip（理由を表示）
2. URL の DB 名が `_test` で終わらなければ即 `pytest.exit`（開発 DB を壊さない）
3. dialect が `mysql` でなければ即 `pytest.exit`（SQLite での偽陽性防止）

schema は `alembic upgrade head` で作る（`create_all` 禁止。テスト設計書 1.4 #4）。
"""

from __future__ import annotations

import argparse
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.seed import seed, truncate_all_tables
from tests.integration import concurrency_helpers
from tests.integration.live_server import live_server  # noqa: F401  # フィクスチャ登録

ENV_KEY = "DATABASE_URL_TEST"
SKIP_REASON = f"integration: 環境変数 {ENV_KEY} が未設定のため未実行（MySQL 未起動）"

API_DIR = Path(__file__).resolve().parents[2]  # apps/api
ALEMBIC_INI = API_DIR / "alembic.ini"


def _validate_test_url(url: str) -> None:
    try:
        parsed = make_url(url)
    except Exception as exc:  # noqa: BLE001
        pytest.exit(f"{ENV_KEY} を解釈できません: {type(exc).__name__}", returncode=3)
    db_name = (parsed.database or "").split("?")[0]
    if not db_name.endswith("_test"):
        pytest.exit(
            f"{ENV_KEY} の DB 名 '{db_name}' が '_test' で終わっていません。"
            " 開発 DB を壊す危険があるため中止します。",
            returncode=3,
        )
    if parsed.get_backend_name() != "mysql":
        pytest.exit(
            f"{ENV_KEY} の dialect が '{parsed.get_backend_name()}' です。"
            " integration は MySQL でのみ実行します（SQLite は競合を直列化し偽陽性になる）。",
            returncode=3,
        )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    url = os.environ.get(ENV_KEY, "")
    here = os.path.dirname(os.path.abspath(__file__))
    integration_items = [i for i in items if str(i.fspath).startswith(here)]
    if not integration_items:
        return
    if not url:
        marker = pytest.mark.skip(reason=SKIP_REASON)
        for item in integration_items:
            item.add_marker(marker)
        return
    _validate_test_url(url)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """同時実行 IT の無効試行（inflight_max < 2 で再試行した回数）を最後に表示する。"""
    if not os.environ.get(ENV_KEY):
        return
    counts = concurrency_helpers.invalid_attempts
    total = sum(counts.values())
    detail = ", ".join(f"{name}={n}" for name, n in sorted(counts.items())) or "なし"
    terminalreporter.write_sep(
        "-", f"同時実行 IT の無効試行（inflight_max < 2 → 再試行）: 合計 {total} 回（{detail}）"
    )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get(ENV_KEY, "")
    if not url:
        pytest.skip(SKIP_REASON)
    _validate_test_url(url)
    return url


def alembic_config(database_url: str) -> Config:
    """テスト DB を向いた Alembic Config。URL は `-x url=` で env.py に渡す。"""
    _validate_test_url(database_url)
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.cmd_opts = argparse.Namespace(x=[f"url={database_url}"])
    return cfg


@pytest.fixture(scope="session")
def migrated_schema(test_database_url: str) -> str:
    """セッション開始時に `alembic upgrade head` を guapp_test に適用する（同期）。"""
    command.upgrade(alembic_config(test_database_url), "head")
    return test_database_url


@pytest.fixture
def it_app(
    make_app: Callable[..., FastAPI], test_database_url: str, migrated_schema: str
) -> FastAPI:
    """MySQL（guapp_test）に接続する本物の app。schema は upgrade head 済み。"""
    return make_app(APP_ENV="test", DATABASE_URL=test_database_url)


@pytest.fixture
async def it_engine(migrated_schema: str) -> AsyncIterator[AsyncEngine]:
    """テスト DB への素の async エンジン（テストごとに作って捨てる）。"""
    engine = create_async_engine(migrated_schema, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def seed_db(it_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """各テストの前に 12 表を空にして seed を投入し、後で TRUNCATE する（Wave 1 の IT 用）。"""
    result = await seed(it_engine, reset=True)
    assert not result.skipped, "reset=True なのに seed が skip された"
    try:
        yield it_engine
    finally:
        async with it_engine.begin() as conn:
            await truncate_all_tables(conn)
