"""DB エンジンとセッション（SQLAlchemy 2.0 async ＋ asyncmy）。

プールは既定 20 本＋オーバーフロー 10（テスト設計書 1.4 #1「プールは 20 以上」）。
環境変数 `DB_POOL_SIZE`・`DB_MAX_OVERFLOW` で上書きできる
（設計仕様書追補 P2-a 8.5・DS-DEC-46。UT-DBCONF-01）。共用の講義サーバーに
繋ぐときは既定値のままだと gunicorn の複数ワーカー分で接続上限を圧迫するため、
5／5 に絞ることを想定している。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

POOL_SIZE = 20
MAX_OVERFLOW = 10


def build_engine(
    database_url: str,
    *,
    pool_size: int = POOL_SIZE,
    max_overflow: int = MAX_OVERFLOW,
) -> AsyncEngine:
    """接続 URL からエンジンを作る。SQLite（UT 用）はプール引数を受け付けないので分岐する。"""
    if database_url.startswith("sqlite"):
        return create_async_engine(database_url, pool_pre_ping=True)
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return build_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


def reset_engine_cache() -> None:
    """テストで設定を差し替えた後に呼ぶ。"""
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


async def get_session(
    _: Settings = Depends(get_settings),
) -> AsyncIterator[AsyncSession]:
    """FastAPI 依存。1 リクエスト 1 セッション。"""
    async with get_sessionmaker()() as session:
        yield session
