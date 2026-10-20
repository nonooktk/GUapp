"""IT-052・052a: 管理：設定 API（DS-API-052・052a）の結合テスト。MySQL・seed 必須。

テスト設計書 P2 追補c 4.3 / 設計仕様書 P2 追補c 4.3・4.6・5.4・DS-DEC-119。担当レーン: C-2。
設定の初期値は seed のとおり（税率 "0.10"・送料 550・送料無料の下限 4990・決済待ち 30）。
同時実行（IT-052a-06）は MySQL・`alembic upgrade head`・プール 20 以上で行い、同時に処理中の
件数の最大値が 2 以上であることを assert する（本編 1.4 #1〜#5）。10 回の有効試行を通す。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.repositories import admin_settings as settings_repo
from tests.integration import admin_helpers as ah
from tests.integration import order_helpers as oh
from tests.integration import p2b_helpers as ph
from tests.integration.test_it_051_admin_products import track_inflight
from tests.recording_mail import RecordingMailAdapter

PATH = "/api/v1/admin/settings"
KEYS = ["tax_rate", "shipping_fee", "free_shipping_threshold", "payment_timeout_minutes"]


@pytest.fixture
def admin_app(
    make_app: Callable[..., FastAPI],
    test_database_url: str,
    migrated_schema: str,
    recording_mail: RecordingMailAdapter,
) -> FastAPI:
    app = make_app(APP_ENV="test", DATABASE_URL=test_database_url)
    recording_mail.install(app)
    return app


@pytest.fixture
async def client(
    admin_app: FastAPI,
    seed_db: AsyncEngine,
    client_factory: Callable[[FastAPI], httpx.AsyncClient],
) -> httpx.AsyncClient:
    return client_factory(admin_app)


@pytest.fixture
def engine(seed_db: AsyncEngine) -> AsyncEngine:
    return seed_db


@pytest.fixture
async def token(engine: AsyncEngine) -> str:
    staff_id = await ah.create_staff(engine, "staff-c2")
    return await ah.make_admin_session(engine, staff_id)


async def sql(engine: AsyncEngine, statement: str, **params: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return list(result.all()) if result.returns_rows else []


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def stored(engine: AsyncEngine) -> dict[str, Any]:
    rows = await sql(engine, "SELECT `key`, value FROM system_settings")
    return {r[0]: _json(r[1]) for r in rows}


async def audit(engine: AsyncEngine) -> list[dict[str, Any]]:
    rows = await sql(
        engine,
        "SELECT actor_type, actor_id, target_type, target_id, detail FROM audit_logs"
        " WHERE action = 'admin.settings.update' ORDER BY id",
    )
    return [
        {
            "actor_type": r[0],
            "actor_id": r[1],
            "target_type": r[2],
            "target_id": r[3],
            "detail": _json(r[4]),
        }
        for r in rows
    ]


async def get(client: httpx.AsyncClient, token: str | None) -> httpx.Response:
    return await client.get(PATH, headers=ah.admin_headers(token))


async def patch(client: httpx.AsyncClient, token: str | None, body: Any) -> httpx.Response:
    return await client.patch(PATH, json=body, headers=ah.admin_headers(token))


# ══════════════════════════════════════════════════════════════════════════
# IT-052 設定の取得
# ══════════════════════════════════════════════════════════════════════════


async def test_it_052_01_four_items_in_order_with_types_and_ranges(
    client: httpx.AsyncClient, token: str
) -> None:
    res = await get(client, token)
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    items = res.json()["items"]
    assert [i["key"] for i in items] == KEYS
    by_key = {i["key"]: i for i in items}
    assert by_key["tax_rate"]["value"] == "0.10"
    assert isinstance(by_key["tax_rate"]["value"], str)
    assert (by_key["tax_rate"]["min"], by_key["tax_rate"]["max"]) == ("0.00", "0.30")
    assert by_key["shipping_fee"]["value"] == 550
    assert (by_key["shipping_fee"]["min"], by_key["shipping_fee"]["max"]) == (0, 5000)
    assert by_key["free_shipping_threshold"]["value"] == 4990
    assert (
        by_key["free_shipping_threshold"]["min"],
        by_key["free_shipping_threshold"]["max"],
    ) == (0, 100000)
    assert by_key["payment_timeout_minutes"]["value"] == 30
    assert [i["editable"] for i in items] == [True, True, True, False]
    assert by_key["payment_timeout_minutes"]["min"] is None
    for i in items:
        assert set(i) == {"key", "label", "value", "editable", "unit", "min", "max"}
        assert i["label"]
    assert (
        by_key["shipping_fee"]["unit"] == "円" and by_key["payment_timeout_minutes"]["unit"] == "分"
    )
    for key in ("shipping_fee", "free_shipping_threshold", "payment_timeout_minutes"):
        assert type(by_key[key]["value"]) is int


async def test_it_052_02_missing_row_is_500_with_fixed_message(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str, caplog: pytest.LogCaptureFixture
) -> None:
    await sql(engine, "DELETE FROM system_settings WHERE `key` = 'shipping_fee'")
    res = await get(client, token)
    assert res.status_code == 500
    assert res.json() == {"code": "internal_error", "message": "処理中にエラーが発生しました"}
    # 更新も、変更するキーの行が無ければ 500（投入漏れ）
    res = await patch(client, token, {"shipping_fee": 660, "expected_shipping_fee": 550})
    assert res.status_code == 500 and res.json()["code"] == "internal_error"
    assert await audit(engine) == []


async def test_it_052_03_member_session_is_403(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    member_token = await ph.make_session(engine, await ph.member_id_of(engine))
    assert (await get(client, member_token)).status_code == 403
    res = await patch(client, member_token, {"shipping_fee": 660, "expected_shipping_fee": 550})
    assert res.status_code == 403
    assert (await get(client, None)).status_code == 401
    assert (await stored(engine))["shipping_fee"] == 550


# ══════════════════════════════════════════════════════════════════════════
# IT-052a 設定の更新
# ══════════════════════════════════════════════════════════════════════════


async def test_it_052a_01_each_key_and_all_together(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    res = await patch(client, token, {"shipping_fee": 660, "expected_shipping_fee": 550})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["changed"] == ["shipping_fee"]
    assert [i["key"] for i in body["items"]] == KEYS
    assert {i["key"]: i["value"] for i in body["items"]}["shipping_fee"] == 660
    assert (await stored(engine))["shipping_fee"] == 660
    res = await patch(
        client, token, {"free_shipping_threshold": 5990, "expected_free_shipping_threshold": 4990}
    )
    assert res.status_code == 200 and res.json()["changed"] == ["free_shipping_threshold"]
    res = await patch(client, token, {"tax_rate": "0.08", "expected_tax_rate": "0.10"})
    assert res.status_code == 200 and res.json()["changed"] == ["tax_rate"]
    assert (await stored(engine))["tax_rate"] == "0.08"
    assert len(await audit(engine)) == 3
    # 3 キーを同時に: 監査ログは 1 行（全キーを detail に持つ）
    await sql(engine, "DELETE FROM audit_logs")
    res = await patch(
        client,
        token,
        {
            "tax_rate": "0.10",
            "expected_tax_rate": "0.08",
            "shipping_fee": 550,
            "expected_shipping_fee": 660,
            "free_shipping_threshold": 4990,
            "expected_free_shipping_threshold": 5990,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["changed"] == ["tax_rate", "shipping_fee", "free_shipping_threshold"]
    assert await stored(engine) == {
        "tax_rate": "0.10",
        "shipping_fee": 550,
        "free_shipping_threshold": 4990,
        "payment_timeout_minutes": 30,
    }
    (row,) = await audit(engine)
    staff_id = (await sql(engine, "SELECT id FROM staff WHERE login_id='staff-c2'"))[0][0]
    assert row["actor_type"] == "staff" and row["actor_id"] == staff_id
    assert (row["target_type"], row["target_id"]) == ("setting", "tax_rate")
    assert row["detail"] == {
        "tax_rate": {"before": "0.08", "after": "0.10"},
        "shipping_fee": {"before": 660, "after": 550},
        "free_shipping_threshold": {"before": 5990, "after": 4990},
    }


@pytest.mark.parametrize(
    ("body", "status", "payload"),
    [
        # 税率
        ({"tax_rate": "0.00", "expected_tax_rate": "0.10"}, 200, None),
        ({"tax_rate": "0.30", "expected_tax_rate": "0.10"}, 200, None),
        (
            {"tax_rate": "0.31", "expected_tax_rate": "0.10"},
            422,
            {"code": "limit_exceeded", "field": "tax_rate", "limit": "0.30"},
        ),
        (
            {"tax_rate": "1.00", "expected_tax_rate": "0.10"},
            422,
            {"code": "limit_exceeded", "field": "tax_rate", "limit": "0.30"},
        ),
        ({"tax_rate": "0.1", "expected_tax_rate": "0.10"}, 400, None),
        ({"tax_rate": "10%", "expected_tax_rate": "0.10"}, 400, None),
        ({"tax_rate": "abc", "expected_tax_rate": "0.10"}, 400, None),
        ({"tax_rate": 0.1, "expected_tax_rate": "0.10"}, 400, None),
        ({"tax_rate": "0.10\n", "expected_tax_rate": "0.10"}, 400, None),
        # 送料
        ({"shipping_fee": 0, "expected_shipping_fee": 550}, 200, None),
        ({"shipping_fee": 5000, "expected_shipping_fee": 550}, 200, None),
        (
            {"shipping_fee": 5001, "expected_shipping_fee": 550},
            422,
            {"code": "limit_exceeded", "field": "shipping_fee", "limit": 5000},
        ),
        (
            {"shipping_fee": -1, "expected_shipping_fee": 550},
            422,
            {"code": "unsupported_value", "field": "shipping_fee"},
        ),
        ({"shipping_fee": "550", "expected_shipping_fee": 550}, 400, None),
        ({"shipping_fee": 5.5, "expected_shipping_fee": 550}, 400, None),
        ({"shipping_fee": True, "expected_shipping_fee": 550}, 400, None),
        ({"shipping_fee": 2147483648, "expected_shipping_fee": 550}, 400, None),
        # 送料無料の下限
        ({"free_shipping_threshold": 0, "expected_free_shipping_threshold": 4990}, 200, None),
        ({"free_shipping_threshold": 100000, "expected_free_shipping_threshold": 4990}, 200, None),
        (
            {"free_shipping_threshold": 100001, "expected_free_shipping_threshold": 4990},
            422,
            {"code": "limit_exceeded", "field": "free_shipping_threshold", "limit": 100000},
        ),
        (
            {"free_shipping_threshold": -1, "expected_free_shipping_threshold": 4990},
            422,
            {"code": "unsupported_value", "field": "free_shipping_threshold"},
        ),
    ],
)
async def test_it_052a_02_boundaries(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    body: dict[str, Any],
    status: int,
    payload: dict | None,
) -> None:
    before = await stored(engine)
    res = await patch(client, token, body)
    assert res.status_code == status, res.text
    if payload is not None:
        assert res.json() == payload
    if status == 400:
        assert res.json()["code"] == "validation_error"
    if status != 200:
        assert await stored(engine) == before  # 失敗時は DB が変わらない
        assert await audit(engine) == []


async def test_it_052a_03_stale_expected_names_the_first_mismatch(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    res = await patch(client, token, {"shipping_fee": 660, "expected_shipping_fee": 100})
    assert res.status_code == 409
    assert res.json() == {"code": "stale_data", "field": "shipping_fee", "current": 550}
    # 2 キーのうち 1 つだけ違う: 全体を更新しない
    before = await stored(engine)
    res = await patch(
        client,
        token,
        {
            "tax_rate": "0.08",
            "expected_tax_rate": "0.10",
            "free_shipping_threshold": 6000,
            "expected_free_shipping_threshold": 1,
        },
    )
    assert res.status_code == 409
    assert res.json() == {"code": "stale_data", "field": "free_shipping_threshold", "current": 4990}
    assert await stored(engine) == before and await audit(engine) == []
    # 型が違う expected も不一致（"0.1" と "0.10" は別）
    res = await patch(client, token, {"tax_rate": "0.08", "expected_tax_rate": "0.1"})
    assert res.status_code == 409 and res.json()["current"] == "0.10"


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"shipping_fee": 660}, [{"name": "expected_shipping_fee", "reason": "required"}]),
        ({"tax_rate": "0.08"}, [{"name": "expected_tax_rate", "reason": "required"}]),
        (
            {"free_shipping_threshold": 1},
            [{"name": "expected_free_shipping_threshold", "reason": "required"}],
        ),
        ({}, [{"name": "body", "reason": "required"}]),
        (
            {"payment_timeout_minutes": 60, "expected_payment_timeout_minutes": 30},
            [{"name": "body", "reason": "required"}],
        ),
        (
            {"expected_shipping_fee": 550, "expected_tax_rate": "0.10"},
            [{"name": "body", "reason": "required"}],
        ),
    ],
)
async def test_it_052a_04_missing_pairs_and_no_key_are_400(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    body: dict[str, Any],
    fields: list[dict],
) -> None:
    res = await patch(client, token, body)
    assert res.status_code == 400, res.text
    assert res.json() == {"code": "validation_error", "fields": fields}
    assert (await stored(engine))["payment_timeout_minutes"] == 30


async def test_it_052a_05_timeout_and_unknown_keys_are_ignored(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    count = len(await sql(engine, "SELECT 1 FROM system_settings"))
    res = await patch(
        client,
        token,
        {
            "shipping_fee": 660,
            "expected_shipping_fee": 550,
            "payment_timeout_minutes": 99,
            "foo": 1,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["changed"] == ["shipping_fee"]
    values = await stored(engine)
    assert values["shipping_fee"] == 660 and values["payment_timeout_minutes"] == 30
    assert "foo" not in values and len(values) == count


async def test_it_052a_06_ten_parallel_updates_one_wins(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同じ `expected_shipping_fee` で、値が互いに違う送料を 10 並列に更新する。"""
    inflight = track_inflight(monkeypatch, settings_repo, "lock_values", hold=0.03)
    for round_no in range(10):
        await sql(
            engine,
            "UPDATE system_settings SET value = CAST(550 AS JSON) WHERE `key` = 'shipping_fee'",
        )
        await sql(engine, "DELETE FROM audit_logs")
        inflight.max = 0
        results = await asyncio.gather(
            *(
                patch(client, token, {"shipping_fee": 600 + i, "expected_shipping_fee": 550})
                for i in range(10)
            )
        )
        assert inflight.max >= 2, f"同時性が成立していない（無効試行）: {inflight.max}"
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [409] * 9, (round_no, [(r.status_code, r.text) for r in results])
        assert all(r.json()["code"] == "stale_data" for r in results if r.status_code == 409)
        winner = next(r for r in results if r.status_code == 200)
        assert (await stored(engine))["shipping_fee"] in {600 + i for i in range(10)}
        assert {i["key"]: i["value"] for i in winner.json()["items"]}["shipping_fee"] == (
            (await stored(engine))["shipping_fee"]
        )
        assert len(await audit(engine)) == 1, round_no


async def test_it_052a_07_public_settings_and_checkout_use_new_values(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    vid = await oh.stocked_variant_id(engine, 1)  # 商品 1: 税込 1,490 円（送料の対象）

    async def prepared_totals() -> dict[str, Any]:
        cart = await oh.new_token(client)
        await oh.add_item(client, cart, vid, 1)
        return await oh.prepare(client, cart)

    before = await prepared_totals()
    assert before["shipping_fee"] == 550 and before["total"] == before["subtotal"] + 550
    res = await patch(
        client,
        token,
        {
            "shipping_fee": 660,
            "expected_shipping_fee": 550,
            "tax_rate": "0.08",
            "expected_tax_rate": "0.10",
        },
    )
    assert res.status_code == 200, res.text
    public = (await client.get("/api/v1/settings/public", headers=oh.h())).json()
    assert public == {"tax_rate": "0.08", "shipping_fee": 660, "free_shipping_threshold": 4990}
    after = await prepared_totals()
    assert after["shipping_fee"] == 660 and after["total"] == after["subtotal"] + 660
    assert after["tax_included"] == after["total"] * 8 // 108
    # 送料無料の下限を小計の下に下げると、送料は 0
    res = await patch(
        client,
        token,
        {"free_shipping_threshold": 1000, "expected_free_shipping_threshold": 4990},
    )
    assert res.status_code == 200
    free = await prepared_totals()
    assert free["shipping_fee"] == 0 and free["total"] == free["subtotal"]


async def test_it_052a_08_all_or_nothing_on_invalid_range(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    before = await stored(engine)
    res = await patch(
        client,
        token,
        {
            "tax_rate": "0.08",
            "expected_tax_rate": "0.10",
            "shipping_fee": 5001,
            "expected_shipping_fee": 550,
        },
    )
    assert res.status_code == 422
    assert res.json() == {"code": "limit_exceeded", "field": "shipping_fee", "limit": 5000}
    assert await stored(engine) == before
    assert await audit(engine) == []


async def test_it_052a_09_same_values_change_nothing(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    before = await sql(engine, "SELECT `key`, updated_at FROM system_settings ORDER BY `key`")
    res = await patch(
        client,
        token,
        {
            "tax_rate": "0.10",
            "expected_tax_rate": "0.10",
            "shipping_fee": 550,
            "expected_shipping_fee": 550,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["changed"] == []
    assert [i["key"] for i in res.json()["items"]] == KEYS
    assert await audit(engine) == []
    assert (
        await sql(engine, "SELECT `key`, updated_at FROM system_settings ORDER BY `key`") == before
    )
    # 片方だけ変える: 変えたキーだけ記録される
    res = await patch(
        client,
        token,
        {
            "tax_rate": "0.10",
            "expected_tax_rate": "0.10",
            "shipping_fee": 700,
            "expected_shipping_fee": 550,
        },
    )
    assert res.status_code == 200 and res.json()["changed"] == ["shipping_fee"]
    (row,) = await audit(engine)
    assert row["target_id"] == "shipping_fee"
    assert row["detail"] == {"shipping_fee": {"before": 550, "after": 700}}
