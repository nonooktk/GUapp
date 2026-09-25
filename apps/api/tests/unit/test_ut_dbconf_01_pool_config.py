"""UT-DBCONF-01: DB接続プール設定の環境変数上書き確認（設計仕様書追補 8.5・DS-DEC-46）。

`DB_POOL_SIZE`・`DB_MAX_OVERFLOW` を設定した場合・未設定の場合の両方で、
`Settings`（core/config.py）と `build_engine()`（core/db.py）が正しい値を使うことを確認する。
未設定時は既定値 20／10（本編どおり）。設定時（例: 5／5）はその値が使われる。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings
from app.core.db import MAX_OVERFLOW, POOL_SIZE, build_engine

MYSQL_URL = "mysql+asyncmy://user:pass@127.0.0.1:3306/guapp"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_db_pool_defaults_when_unset() -> None:
    """環境変数が無い場合、Settings の既定値は現状どおり 20／10。"""
    settings = Settings(_env_file=None)
    assert settings.DB_POOL_SIZE == 20
    assert settings.DB_MAX_OVERFLOW == 10
    assert settings.DB_POOL_SIZE == POOL_SIZE
    assert settings.DB_MAX_OVERFLOW == MAX_OVERFLOW


def test_settings_db_pool_overridden_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """環境変数を設定すると Settings に反映される（講義サーバー接続時の推奨値 5／5 が例）。"""
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    settings = Settings(_env_file=None)
    assert settings.DB_POOL_SIZE == 5
    assert settings.DB_MAX_OVERFLOW == 5


def test_build_engine_uses_default_pool_when_not_specified() -> None:
    """pool_size/max_overflow を渡さなければ、モジュール既定値（20/10）が使われる。"""
    engine = build_engine(MYSQL_URL)
    try:
        assert engine.pool.size() == POOL_SIZE
        assert engine.pool._max_overflow == MAX_OVERFLOW  # noqa: SLF001
    finally:
        pass


def test_build_engine_honors_explicit_pool_settings() -> None:
    """build_engine() に明示した pool_size/max_overflow がそのままエンジンに使われる。"""
    engine = build_engine(MYSQL_URL, pool_size=5, max_overflow=5)
    assert engine.pool.size() == 5
    assert engine.pool._max_overflow == 5  # noqa: SLF001


def test_get_engine_reads_pool_settings_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_engine() は Settings 経由で DB_POOL_SIZE/DB_MAX_OVERFLOW を読み、build_engine に渡す。"""
    from app.core.db import get_engine, reset_engine_cache

    monkeypatch.setenv("DATABASE_URL", MYSQL_URL)
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    get_settings.cache_clear()
    reset_engine_cache()
    try:
        engine = get_engine()
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 5  # noqa: SLF001
    finally:
        reset_engine_cache()
        get_settings.cache_clear()
