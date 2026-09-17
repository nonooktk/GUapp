"""Alembic 環境（async・MySQL）。

- 接続 URL は `app.core.config.get_settings().DATABASE_URL`（環境変数）から読む。
  `alembic.ini` には URL を書かない（規定 §3）。
- `target_metadata = Base.metadata`（P1 の 12 表。`app.models` を import すると全表が登録される）
- `compare_type=True`（列型の差分も検出）、`render_as_batch=False`（MySQL は ALTER が使える）
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.models import Base  # noqa: F401  # 全モデルを metadata に登録するために import

config = context.config

if config.config_file_name is not None:
    # 既存ロガー（app.* や pytest の caplog）を無効化しない
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    """接続 URL。`-x url=...` で明示されたときはそれを優先（テストのフィクスチャ用）。"""
    x_args = context.get_x_argument(as_dictionary=True)
    url = x_args.get("url") or get_settings().DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL が未設定です（環境変数で与えてください）")
    return url


def run_migrations_offline() -> None:
    """DB に接続せず SQL を標準出力へ出す（`--sql`）。"""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)
    if connectable is None:
        asyncio.run(run_async_migrations())
    else:
        # テストなど既存の同期 Connection を渡された場合
        do_run_migrations(connectable)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
