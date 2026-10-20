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


@pytest.mark.parametrize("env", ["development", "production"])
async def test_ut_test_routes_absent_outside_test_env(make_app, client_factory, env: str) -> None:
    """`/_test/metrics`・`/_test/reset` は APP_ENV=test 以外では登録されない（404）。"""
    client = client_factory(make_app(APP_ENV=env))
    assert (await client.get("/_test/metrics")).status_code == 404
    assert (await client.post("/_test/reset")).status_code == 404


async def test_ut_test_routes_present_in_test_env(make_app, client_factory) -> None:
    client = client_factory(make_app(APP_ENV="test", TEST_RESERVE_DELAY_MS="7"))
    from app.core import testing_hooks as th

    assert th.get_delay_ms() == 7  # 環境変数から遅延が設定される
    res = await client.get("/_test/metrics")
    assert res.status_code == 200
    assert set(res.json()) == {"inflight_now", "inflight_max"}
    th.allocation_counter.max_seen = 5
    assert (await client.post("/_test/reset")).status_code == 200
    assert (await client.get("/_test/metrics")).json() == {"inflight_now": 0, "inflight_max": 0}
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


def test_ut_models_export_23_tables() -> None:
    from app.models import ALL_TABLES, P1_TABLES, P2A_TABLES, P2B_TABLES, P2D_TABLES, Base

    names = set(Base.metadata.tables)
    # P1（12 表）に P2-a の DS-TBL-22 contents（1 表）、P2-b の 8 表、P2-d の chat_sessions・
    # chat_messages（2 表）を加えて 23 表になった（P2-c は表を増やさない）
    assert P1_TABLES | P2A_TABLES | P2B_TABLES | P2D_TABLES == ALL_TABLES
    assert names == ALL_TABLES
    assert len(P1_TABLES) == 12
    assert len(P2A_TABLES) == 1
    assert len(P2B_TABLES) == 8
    assert len(P2D_TABLES) == 2
    assert len(names) == 23


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
        "pending_payment",
        "accepted",
        "preparing",
        "shipped",
        "delivered",
        "pickup_expired",
        "cancelled",
        "payment_failed",
    }
    # P2-b（設計仕様書 P2 追補b 5.3）: member_id・store_id に外部キーを張った
    assert {fk.column.table.name for fk in t["orders"].c.member_id.foreign_keys} == {"members"}
    assert {fk.column.table.name for fk in t["carts"].c.member_id.foreign_keys} == {"members"}
    assert {fk.column.table.name for fk in t["orders"].c.store_id.foreign_keys} == {"stores"}
    assert t["orders"].c.pickup_code.unique and t["orders"].c.pickup_code.nullable
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
