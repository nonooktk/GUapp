"""IT-024（注文履歴の一覧）・IT-024a（詳細）・IT-026（受け取り店舗）。MySQL・seed 必須。

会員とセッションは DB へ直接入れる（ログイン API はレーン B）。他人・ゲストの注文は 404 / 一覧に
出ない（IDOR を作らない。DS-DEC-77・78）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from tests.integration import order_helpers as oh
from tests.integration import p2b_helpers as ph

FORBIDDEN_KEYS = {"id", "member_id", "order_id", "store_id", "cart_id", "idempotency_key"}
HISTORY_ITEM_KEYS = {
    "order_number",
    "status",
    "status_label",
    "ordered_at",
    "total",
    "receive_method",
    "item_count",
    "first_item_name",
}
ALL_STATUSES = [
    "pending_payment",
    "accepted",
    "preparing",
    "shipped",
    "delivered",
    "pickup_expired",
    "cancelled",
    "payment_failed",
]


@pytest.fixture
async def client(it_app: FastAPI, seed_db: AsyncEngine, client_factory, recording_mail):
    recording_mail.install(it_app)
    return client_factory(it_app)


def all_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in all_keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in all_keys(v)}
    return set()


async def _login(engine: AsyncEngine, email: str = ph.DEMO_MEMBER_EMAIL) -> tuple[int, str]:
    member_id = await ph.member_id_of(engine, email)
    return member_id, await ph.make_session(engine, member_id)


# ── IT-024 注文履歴の一覧 ────────────────────────────────────────────────────


async def test_it_024_01_lists_delivery_and_store_orders_newest_first(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    member_id, tok = await _login(seed_db)
    delivery = await ph.place_order(
        client, seed_db, session_token=tok, product_number=5, quantity=2
    )
    store = await ph.place_order(
        client, seed_db, session_token=tok, store_code="demo-tokyo", product_number=3
    )
    assert delivery["is_member_order"] is True and store["is_member_order"] is True
    await ph.set_order(seed_db, delivery["order_number"], status="shipped")
    await ph.set_order(seed_db, store["order_number"], status="shipped")

    res = await client.get("/api/v1/me/orders", headers=ph.sess(tok))
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["page"], body["per_page"], body["total"], body["has_more"]) == (1, 10, 2, False)
    first, second = body["items"]
    assert [first["order_number"], second["order_number"]] == [
        store["order_number"],
        delivery["order_number"],
    ]
    assert set(first) == HISTORY_ITEM_KEYS
    assert first["receive_method"] == "store" and first["status"] == "shipped"
    assert first["status_label"] == "店舗に到着（受け取り可能）"
    assert first["item_count"] == 1 and first["first_item_name"] == seed_data.PRODUCTS[2].name
    assert second["receive_method"] == "delivery"
    assert second["status_label"] == "出荷済（配送中）"
    assert second["item_count"] == 2, "数量の合計"
    assert second["first_item_name"] == seed_data.PRODUCTS[4].name
    assert second["total"] == delivery["total"]
    assert second["ordered_at"].endswith("Z") or "+00:00" in second["ordered_at"]


async def test_it_024_01_payment_failed_order_is_listed_with_label(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    """決済失敗の注文も一覧に含める（明細は持たないので件数 0・商品名は空）。"""
    member_id, tok = await _login(seed_db)
    number = await ph.insert_order(seed_db, member_id=member_id, status="payment_failed")
    res = await client.get("/api/v1/me/orders", headers=ph.sess(tok))
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["order_number"] == number
    assert item["status"] == "payment_failed" and item["status_label"] == "決済失敗"


async def test_it_024_02_no_orders_is_200_with_empty_items(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    _, tok = await _login(seed_db, ph.NO_ORDER_MEMBER_EMAIL)
    res = await client.get("/api/v1/me/orders", headers=ph.sess(tok))
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == [] and body["total"] == 0 and body["has_more"] is False


async def test_it_024_03_pagination_boundaries(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    member_id, tok = await _login(seed_db)
    base = ph.utcnow() - timedelta(days=1)
    numbers = [
        await ph.insert_order(seed_db, member_id=member_id, created_at=base + timedelta(minutes=i))
        for i in range(11)
    ]
    newest_first = list(reversed(numbers))
    h = ph.sess(tok)

    res = await client.get("/api/v1/me/orders", params={"page": 1}, headers=h)
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 10 and body["has_more"] is True and body["total"] == 11
    assert [i["order_number"] for i in body["items"]] == newest_first[:10]

    res = await client.get("/api/v1/me/orders", params={"page": 2}, headers=h)
    assert [i["order_number"] for i in res.json()["items"]] == newest_first[10:]
    assert res.json()["has_more"] is False

    res = await client.get("/api/v1/me/orders", params={"page": 3}, headers=h)
    assert res.status_code == 200 and res.json()["items"] == [] and res.json()["total"] == 11

    for per_page, expect in ((1, 1), (50, 11)):
        res = await client.get("/api/v1/me/orders", params={"per_page": per_page}, headers=h)
        assert res.status_code == 200 and len(res.json()["items"]) == expect
    for params in ({"per_page": 51}, {"per_page": 0}, {"page": 0}):
        res = await client.get("/api/v1/me/orders", params=params, headers=h)
        assert res.status_code == 400, params
        assert res.json()["code"] == "validation_error"


async def test_it_024_04_missing_or_invalid_session_is_401(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    member_id = await ph.member_id_of(seed_db)
    expired = await ph.make_session(seed_db, member_id, ttl=timedelta(seconds=-5))
    staff = await ph.make_session(seed_db, member_id, subject_type="staff")
    for token in (None, "short", "A" * 43, expired, staff):
        res = await client.get("/api/v1/me/orders", headers=ph.sess(token))
        assert res.status_code == 401, token
        assert res.json() == {"code": "unauthorized"}
        res = await client.get("/api/v1/me/orders/GU-261020-ABCDEFGH", headers=ph.sess(token))
        assert res.status_code == 401, token


async def test_it_024_05_other_members_and_guest_orders_are_not_listed(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    a_id, a_tok = await _login(seed_db, ph.DEMO_MEMBER_EMAIL)
    b_id = await ph.member_id_of(seed_db, ph.OTHER_MEMBER_EMAIL)
    await ph.insert_order(seed_db, member_id=b_id)
    # ゲスト注文（member_id NULL）は、A と同じ連絡先メールでも A の一覧に出ない
    await ph.insert_order(seed_db, member_id=None, guest_email=ph.DEMO_MEMBER_EMAIL)
    mine = await ph.insert_order(seed_db, member_id=a_id)
    res = await client.get("/api/v1/me/orders", headers=ph.sess(a_tok))
    assert res.status_code == 200
    assert [i["order_number"] for i in res.json()["items"]] == [mine]
    assert res.json()["total"] == 1


async def test_it_024_06_response_has_no_internal_ids(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    _, tok = await _login(seed_db)
    placed = await ph.place_order(client, seed_db, session_token=tok, store_code="demo-osaka")
    res = await client.get("/api/v1/me/orders", headers=ph.sess(tok))
    assert not (all_keys(res.json()) & FORBIDDEN_KEYS)
    res = await client.get(f"/api/v1/me/orders/{placed['order_number']}", headers=ph.sess(tok))
    assert res.status_code == 200
    assert not (all_keys(res.json()) & FORBIDDEN_KEYS)


# ── IT-024a 注文履歴の詳細 ───────────────────────────────────────────────────


async def test_it_024a_01_detail_matches_the_confirmed_order_even_after_price_change(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    _, tok = await _login(seed_db)
    placed = await ph.place_order(client, seed_db, session_token=tok, quantity=2)
    async with seed_db.begin() as conn:
        await conn.execute(text("UPDATE products SET price_incl_tax = 9999"))
    res = await client.get(f"/api/v1/me/orders/{placed['order_number']}", headers=ph.sess(tok))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == placed, "確定時単価・金額・お届け先・日時が注文時のまま"
    assert body["items"][0]["unit_price"] == 1990 and body["items"][0]["quantity"] == 2
    assert body["is_member_order"] is True and body["status_label"] == "受付済"


async def test_it_024a_02_other_guest_missing_and_malformed_numbers_are_identical_404(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    a_id, a_tok = await _login(seed_db, ph.DEMO_MEMBER_EMAIL)
    b_id = await ph.member_id_of(seed_db, ph.OTHER_MEMBER_EMAIL)
    b_order = await ph.insert_order(seed_db, member_id=b_id)
    guest_order = await ph.insert_order(seed_db, member_id=None, guest_email=ph.DEMO_MEMBER_EMAIL)
    mine = await ph.insert_order(seed_db, member_id=a_id)
    assert (
        await client.get(f"/api/v1/me/orders/{mine}", headers=ph.sess(a_tok))
    ).status_code == 200

    candidates = [
        b_order,
        guest_order,
        "GU-261020-ZZZZZZZZ",  # 形は正しいが存在しない
        "GU-261020-ABCDEFG",  # 7 文字
        "gu-261020-abcdefgh",
        "GU-２６１０２０-ABCDEFGH",  # 全角数字
        "GU-261020-ABCDEFGO",  # 使わない文字（O）
        "not-an-order",
    ]
    responses = [
        await client.get(f"/api/v1/me/orders/{n}", headers=ph.sess(a_tok)) for n in candidates
    ]
    assert {r.status_code for r in responses} == {404}
    assert {r.text for r in responses} == {'{"code":"not_found"}'}


async def test_it_024a_03_pickup_code_is_shown_only_for_three_statuses(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    _, tok = await _login(seed_db)
    placed = await ph.place_order(client, seed_db, session_token=tok, store_code="demo-tokyo")
    number = placed["order_number"]
    code = await oh.scalar(seed_db, "SELECT pickup_code FROM orders")
    assert code and placed["pickup_code"] == code
    shown = {"accepted", "preparing", "shipped"}
    for status in ALL_STATUSES:
        await ph.set_order(seed_db, number, status=status)
        res = await client.get(f"/api/v1/me/orders/{number}", headers=ph.sess(tok))
        assert res.status_code == 200, status
        expected = code if status in shown else None
        assert res.json()["pickup_code"] == expected, status
        assert res.json()["status"] == status


async def test_it_024a_04_tracking_number_only_for_shipped_and_delivered_delivery_orders(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    _, tok = await _login(seed_db)
    placed = await ph.place_order(client, seed_db, session_token=tok)
    number = placed["order_number"]
    await ph.set_order(seed_db, number, tracking_number="TRACK-0001")
    expected = {"preparing": None, "shipped": "TRACK-0001", "delivered": "TRACK-0001"}
    for status, tracking in expected.items():
        await ph.set_order(seed_db, number, status=status)
        res = await client.get(f"/api/v1/me/orders/{number}", headers=ph.sess(tok))
        assert res.json()["tracking_number"] == tracking, status
        assert res.json()["pickup_code"] is None, "配送の注文に受け取りコードは無い"


async def test_it_024a_05_store_field_has_only_three_keys(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    _, tok = await _login(seed_db)
    store_order = await ph.place_order(
        client, seed_db, session_token=tok, store_code="demo-fukuoka"
    )
    delivery_order = await ph.place_order(client, seed_db, session_token=tok)
    res = await client.get(f"/api/v1/me/orders/{store_order['order_number']}", headers=ph.sess(tok))
    store = res.json()["store"]
    assert set(store) == {"name", "prefecture", "address"}
    fukuoka = seed_data.STORES[2]
    assert store == {
        "name": fukuoka.name,
        "prefecture": fukuoka.prefecture,
        "address": fukuoka.address,
    }
    res = await client.get(
        f"/api/v1/me/orders/{delivery_order['order_number']}", headers=ph.sess(tok)
    )
    assert res.json()["store"] is None


# ── IT-026 受け取り店舗 ──────────────────────────────────────────────────────


async def test_it_026_01_lists_seed_stores_in_sort_order(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    res = await client.get("/api/v1/stores", headers=oh.h())
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [i["code"] for i in items] == ["demo-tokyo", "demo-osaka", "demo-fukuoka"]
    assert all(set(i) == {"code", "name", "prefecture", "address"} for i in items)
    assert items[0]["name"] == seed_data.STORES[0].name
    assert "postal_code" not in res.text and "0000001" not in res.text
    # 認証不要（内部トークンだけ）。内部トークンが無ければ 401
    assert (await client.get("/api/v1/stores")).status_code == 401


async def test_it_026_02_disabled_stores_are_hidden_and_empty_list_is_200(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    async with seed_db.begin() as conn:
        await conn.execute(text("UPDATE stores SET pickup_enabled = 0 WHERE code = 'demo-osaka'"))
    res = await client.get("/api/v1/stores", headers=oh.h())
    assert [i["code"] for i in res.json()["items"]] == ["demo-tokyo", "demo-fukuoka"]
    async with seed_db.begin() as conn:
        await conn.execute(text("UPDATE stores SET pickup_enabled = 0"))
    res = await client.get("/api/v1/stores", headers=oh.h())
    assert res.status_code == 200 and res.json() == {"items": []}
