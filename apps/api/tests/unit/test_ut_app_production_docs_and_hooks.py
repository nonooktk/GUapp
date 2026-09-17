"""本番モードでの Swagger 無効化、testing_hooks の no-op、モデルの export。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Enum, UniqueConstraint

API_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_ut_app_production_docs_disabled(make_app, client_factory, path: str) -> None:
    app = make_app(APP_ENV="production")
    client = client_factory(app)
    res = await client.get(path)
    assert res.status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
async def test_ut_app_development_docs_enabled(make_app, client_factory, path: str) -> None:
    app = make_app(APP_ENV="development")
    client = client_factory(app)
    res = await client.get(path)
    assert res.status_code == 200


async def test_ut_hooks_noop_when_not_test(app_env) -> None:
    app_env(APP_ENV="development")
    from app.core import testing_hooks as th

    th.reset_all()
    th.set_delay_ms(500)
    assert th.get_delay_ms() == 0
    async with th.allocation_counter.track():
        assert th.allocation_counter.current == 0
    assert th.allocation_counter.max_seen == 0
    await th.maybe_delay()  # 即 return（待たない）


async def test_ut_hooks_active_when_test(app_env) -> None:
    import asyncio

    app_env(APP_ENV="test")
    from app.core import testing_hooks as th

    th.reset_all()
    th.set_delay_ms(5)
    assert th.get_delay_ms() == 5

    async def work() -> None:
        async with th.allocation_counter.track():
            await asyncio.sleep(0.01)

    await asyncio.gather(work(), work(), work())
    assert th.allocation_counter.max_seen >= 2
    assert th.allocation_counter.current == 0
    th.reset_all()


def test_ut_hooks_not_imported_by_production_path() -> None:
    """`app.main` を import しただけでは testing_hooks が読み込まれない（別プロセスで確認）。"""
    code = (
        "import os, sys; os.environ['APP_ENV']='production'; os.environ['INTERNAL_TOKEN']='x';"
        "os.environ['DATABASE_URL']='sqlite+aiosqlite:///:memory:';"
        "import app.main; print('app.core.testing_hooks' in sys.modules)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=API_ROOT, capture_output=True, text=True, check=True
    )
    assert proc.stdout.strip() == "False", proc.stdout + proc.stderr


def test_ut_models_export_13_tables() -> None:
    from app.models import P1_TABLES, Base

    names = set(Base.metadata.tables)
    assert names == P1_TABLES
    # 設計書 5.2 は「13 表」と書くが、DS-TBL-05〜09・12〜16・21・23 を数えると 12 表
    assert len(names) == 12


def test_ut_models_key_constraints() -> None:
    from app.models import Base

    t = Base.metadata.tables
    # UNIQUE
    assert t["variants"].c.sku.unique
    assert t["orders"].c.order_number.unique and t["orders"].c.idempotency_key.unique
    assert t["orders"].c.stripe_session_id.unique and t["orders"].c.stripe_session_id.nullable
    assert t["carts"].c.anonymous_token.unique and t["carts"].c.anonymous_token.nullable
    assert t["system_settings"].c.key.unique
    assert t["categories"].c.slug.unique
    uq_cols = {
        tuple(c.name for c in cons.columns)
        for tbl in ("product_categories", "cart_items")
        for cons in t[tbl].constraints
        if isinstance(cons, UniqueConstraint)
    }
    assert ("product_id", "category_id") in uq_cols
    assert ("cart_id", "variant_id") in uq_cols
    # 長さ
    assert t["orders"].c.ship_name.type.length == 50
    assert t["orders"].c.ship_address.type.length == 200
    assert t["orders"].c.ship_phone.type.length == 11
    assert t["orders"].c.guest_email.type.length == 254
    assert t["orders"].c.order_number.type.length == 20
    # Enum 8 値
    status_type = t["orders"].c.status.type
    assert isinstance(status_type, Enum)
    assert set(status_type.enums) == {
        "pending_payment", "accepted", "preparing", "shipped",
        "delivered", "pickup_expired", "cancelled", "payment_failed",
    }
    # P1 では member_id に FK 無し
    assert not t["orders"].c.member_id.foreign_keys
    assert not t["carts"].c.member_id.foreign_keys
    # 索引
    assert any(ix.columns.keys() == ["at"] for ix in t["audit_logs"].indexes)
    assert any(ix.columns.keys() == ["published"] for ix in t["products"].indexes)


async def test_ut_models_create_all_on_sqlite() -> None:
    """DDL が生成できることの確認（IT は Alembic を使う。ここは型・制約の整合チェックのみ）。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
