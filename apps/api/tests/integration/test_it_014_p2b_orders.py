"""IT-014-10〜18（店舗受け取り・会員の紐づけ・受け取りコード）、IT-021-03〜05（prepare の送料）、
IT-023-03（店舗注文の照会）。MySQL・seed 必須・in-process クライアント。

同じ会員の別カートの同時注文（IT-014-19）は live_server を使う
`test_it_014_19_member_concurrency.py`。
"""

from __future__ import annotations

import json
import re
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from app.adapters.payment import StubPaymentAdapter, get_payment_adapter
from tests.integration import order_helpers as oh
from tests.integration import p2b_helpers as ph

PICKUP_CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


@pytest.fixture
async def client(it_app: FastAPI, seed_db: AsyncEngine, client_factory, recording_mail):
    recording_mail.install(it_app)
    return client_factory(it_app)


# ── IT-021-03〜05 prepare の送料（DS-PRC-021a）─────────────────────────────────


@pytest.mark.parametrize(
    ("lines", "subtotal"),
    [(((1, 1),), 1490), (((6, 2),), 4980), (((31, 1),), 4990)],
)
async def test_it_021_03_store_prepare_has_zero_shipping(
    client: httpx.AsyncClient, seed_db: AsyncEngine, lines, subtotal
) -> None:
    _, prepared = await ph.cart_with(client, seed_db, *lines, receive_method="store")
    assert prepared["subtotal"] == subtotal
    assert prepared["shipping_fee"] == 0
    assert prepared["total"] == subtotal
    assert prepared["tax_included"] == subtotal * 10 // 110
    assert prepared["receive_method"] == "store"


async def test_it_021_04_delivery_prepare_keeps_the_threshold_with_or_without_body(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    for lines, subtotal, fee in ((((6, 2),), 4980, 550), (((31, 1),), 4990, 0)):
        token = await oh.new_token(client)
        for number, qty in lines:
            await oh.add_item(client, token, await oh.stocked_variant_id(seed_db, number), qty)
        for body in (None, {"receive_method": "delivery"}, {}):
            kwargs = {} if body is None else {"json": body}
            res = await client.post("/api/v1/checkout/prepare", headers=oh.h(token), **kwargs)
            assert res.status_code == 200, (body, res.text)
            out = res.json()
            assert out["subtotal"] == subtotal and out["shipping_fee"] == fee, body
            assert out["receive_method"] == "delivery", body


@pytest.mark.parametrize("value", ["pickup", "", 1])
async def test_it_021_05_unknown_receive_method_is_400_format(
    client: httpx.AsyncClient, seed_db: AsyncEngine, value
) -> None:
    token, _ = await ph.cart_with(client, seed_db, (5, 1))
    res = await client.post(
        "/api/v1/checkout/prepare", json={"receive_method": value}, headers=oh.h(token)
    )
    assert res.status_code == 400, res.text
    assert res.json() == {
        "code": "validation_error",
        "fields": [{"name": "receive_method", "reason": "format"}],
    }


# ── IT-014-10 店舗受け取りの注文 ─────────────────────────────────────────────


async def test_it_014_10_store_pickup_order_copies_store_and_zero_shipping(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    vid = await oh.stocked_variant_id(seed_db, 5)
    before = await oh.stock_of(seed_db, vid)
    token, prepared = await ph.cart_with(client, seed_db, (5, 2), receive_method="store")
    assert prepared["shipping_fee"] == 0
    # 入力された郵便番号・住所・member_id は無視される（mass assignment を許さない）
    body = ph.store_body(
        prepared,
        ship_postal_code="9999999",
        ship_address="攻撃者が指定した住所",
        member_id=1,
        pickup_code="AAAAAAAA",
    )
    res = await client.post("/api/v1/orders", json=body, headers=oh.h(token))
    assert res.status_code == 201, res.text
    out = res.json()

    tokyo = seed_data.STORES[0]
    assert out["status"] == "accepted" and out["receive_method"] == "store"
    assert out["shipping_fee"] == 0 and out["total"] == out["subtotal"] == 3980
    assert out["ship_postal_code"] == tokyo.postal_code and out["ship_address"] == tokyo.address
    assert out["store"] == {
        "name": tokyo.name,
        "prefecture": tokyo.prefecture,
        "address": tokyo.address,
    }
    assert PICKUP_CODE_RE.match(out["pickup_code"]) and out["pickup_code"] != "AAAAAAAA"
    assert out["is_member_order"] is False and out["status_label"] == "受付済"
    assert set(out) == oh.ORDER_KEYS

    async with seed_db.connect() as conn:
        rec = (
            await conn.execute(
                text(
                    "SELECT o.store_id, s.code, o.ship_postal_code, o.ship_address, o.shipping_fee,"
                    " o.pickup_code, o.status, o.member_id, o.receive_method FROM orders o"
                    " JOIN stores s ON s.id = o.store_id"
                )
            )
        ).one()
    assert rec[1] == "demo-tokyo" and rec[2] == tokyo.postal_code and rec[3] == tokyo.address
    assert rec[4] == 0 and rec[5] == out["pickup_code"] and rec[6] == "accepted"
    assert rec[7] is None and rec[8] == "store"
    assert await oh.count_rows(seed_db, "orders") == 1
    assert await oh.count_rows(seed_db, "order_items") == 1
    assert await oh.count_rows(seed_db, "payments", "result='ok'") == 1
    assert await oh.count_rows(seed_db, "audit_logs") == 1
    assert await oh.stock_of(seed_db, vid) == before - 2

    # 監査ログ: receive_method と member_linked を足す。メール・氏名・受け取りコードは書かない
    detail = await oh.scalar(seed_db, "SELECT detail FROM audit_logs WHERE action='order.confirm'")
    detail = json.loads(detail) if isinstance(detail, str) else detail
    assert detail["receive_method"] == "store" and detail["member_linked"] is False
    dumped = json.dumps(detail, ensure_ascii=False)
    for secret in (out["pickup_code"], "test@example.com", "テスト 太郎"):
        assert secret not in dumped


async def test_it_014_10_confirmation_mail_branches_on_store(
    client: httpx.AsyncClient, seed_db: AsyncEngine, recording_mail
) -> None:
    placed = await ph.place_order(client, seed_db, store_code="demo-osaka")
    (mail,) = recording_mail.of_kind("order_confirmation")
    from app.adapters.mail import render_order_confirmation

    text_ = render_order_confirmation(mail.args["order"])
    assert placed["pickup_code"] in text_
    assert seed_data.STORES[1].name in text_ and seed_data.STORES[1].address in text_


# ── IT-014-11〜13 店舗コード・受け取り方法の異常系 ────────────────────────────


async def test_it_014_11_unknown_or_disabled_store_is_409_invalid_reference(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    async with seed_db.begin() as conn:
        await conn.execute(text("UPDATE stores SET pickup_enabled = 0 WHERE code = 'demo-osaka'"))
    vid = await oh.stocked_variant_id(seed_db, 5)
    before = await oh.stock_of(seed_db, vid)
    token, prepared = await ph.cart_with(client, seed_db, (5, 1), receive_method="store")
    for code in ("no-such-store", "demo-osaka"):
        res = await client.post(
            "/api/v1/orders", json=ph.store_body(prepared, code), headers=oh.h(token)
        )
        assert res.status_code == 409, (code, res.text)
        assert res.json() == {"code": "invalid_reference", "field": "store_code"}
        assert await oh.count_rows(seed_db, "orders") == 0
        assert await oh.stock_of(seed_db, vid) == before
        assert await oh.scalar(seed_db, "SELECT status FROM carts") == "active"


async def test_it_014_12_store_code_shape_errors_are_400(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    token, prepared = await ph.cart_with(client, seed_db, (5, 1), receive_method="store")
    missing = ph.store_body(prepared)
    missing.pop("store_code")
    res = await client.post("/api/v1/orders", json=missing, headers=oh.h(token))
    assert res.status_code == 400, res.text
    assert {"name": "store_code", "reason": "required"} in res.json()["fields"]

    for bad in ("", "DEMO-TOKYO", "a" * 33, "ｄｅｍｏ-ｔｏｋｙｏ", "demo_tokyo"):
        res = await client.post(
            "/api/v1/orders", json=ph.store_body(prepared, bad), headers=oh.h(token)
        )
        assert res.status_code == 400, (bad, res.text)
        assert {"name": "store_code", "reason": "format"} in res.json()["fields"], bad
    assert await oh.count_rows(seed_db, "orders") == 0


async def test_it_014_13_delivery_with_store_code_and_unknown_method_are_422(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    token, prepared = await ph.cart_with(client, seed_db, (5, 1))
    res = await client.post(
        "/api/v1/orders",
        json=oh.order_body(prepared, store_code="demo-tokyo"),
        headers=oh.h(token),
    )
    assert res.status_code == 422, res.text
    assert res.json() == {"code": "unsupported_value", "field": "store_code"}
    res = await client.post(
        "/api/v1/orders", json=oh.order_body(prepared, receive_method="pickup"), headers=oh.h(token)
    )
    assert res.status_code == 422
    assert res.json() == {"code": "unsupported_value", "field": "receive_method"}
    assert await oh.count_rows(seed_db, "orders") == 0


# ── IT-014-14〜15 会員の紐づけ ───────────────────────────────────────────────


async def test_it_014_14_valid_session_links_the_order_to_the_member(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    member_id = await ph.member_id_of(seed_db)
    tok = await ph.make_session(seed_db, member_id)
    placed = await ph.place_order(client, seed_db, session_token=tok, member_id=999999)
    assert placed["is_member_order"] is True
    assert await oh.scalar(seed_db, "SELECT member_id FROM orders") == member_id
    detail = await oh.scalar(seed_db, "SELECT detail FROM audit_logs WHERE action='order.confirm'")
    detail = json.loads(detail) if isinstance(detail, str) else detail
    assert detail["member_linked"] is True
    res = await client.get("/api/v1/me/orders", headers=ph.sess(tok))
    assert [i["order_number"] for i in res.json()["items"]] == [placed["order_number"]]


async def test_it_014_15_invalid_session_places_a_guest_order_without_error(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    member_id = await ph.member_id_of(seed_db)
    expired = await ph.make_session(seed_db, member_id, ttl=timedelta(seconds=-5))
    staff = await ph.make_session(seed_db, member_id, subject_type="staff")
    for token in ("A" * 43, expired, staff, "short", "!" * 43):
        placed = await ph.place_order(client, seed_db, session_token=token)
        assert placed["is_member_order"] is False, token
        number = placed["order_number"]
        assert (
            await oh.scalar(seed_db, "SELECT member_id FROM orders WHERE order_number=:n", n=number)
            is None
        )


# ── IT-014-16 受け取りコードの衝突 ───────────────────────────────────────────


async def test_it_014_16_pickup_code_collision_regenerates_once(
    client: httpx.AsyncClient, seed_db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await ph.place_order(client, seed_db, store_code="demo-tokyo")
    taken = first["pickup_code"]

    codes = iter([taken, "ZZZZZZZZ"])
    monkeypatch.setattr("app.repositories.orders.generate_pickup_code", lambda: next(codes))
    second = await ph.place_order(client, seed_db, store_code="demo-tokyo")
    assert second["pickup_code"] == "ZZZZZZZZ", "1 回だけ再生成して成立する"
    assert await oh.count_rows(seed_db, "orders") == 2

    # 2 回続けて衝突したら 500 internal_error（注文は作られず、カートは active のまま）
    monkeypatch.setattr("app.repositories.orders.generate_pickup_code", lambda: taken)
    token, prepared = await ph.cart_with(client, seed_db, (5, 1), receive_method="store")
    res = await client.post("/api/v1/orders", json=ph.store_body(prepared), headers=oh.h(token))
    assert res.status_code == 500 and res.json()["code"] == "internal_error"
    assert await oh.count_rows(seed_db, "orders") == 2
    assert (
        await oh.scalar(seed_db, "SELECT status FROM carts WHERE anonymous_token=:t", t=token)
        == "active"
    )


# ── IT-014-17 冪等キーの再送 ─────────────────────────────────────────────────


async def test_it_014_17_store_order_resend_returns_the_same_order_and_code(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    token, prepared = await ph.cart_with(client, seed_db, (5, 1), receive_method="store")
    body = ph.store_body(prepared)
    res = await client.post("/api/v1/orders", json=body, headers=oh.h(token))
    assert res.status_code == 201, res.text
    first = res.json()
    # 受け取りを止めた後の再送でも、既存注文を返す（店舗の再検索で失敗させない）
    async with seed_db.begin() as conn:
        await conn.execute(text("UPDATE stores SET pickup_enabled = 0"))
    res = await client.post("/api/v1/orders", json=body, headers=oh.h(token))
    assert res.status_code == 200, res.text
    assert res.json() == first
    assert res.json()["pickup_code"] == first["pickup_code"]
    assert await oh.count_rows(seed_db, "orders") == 1


# ── IT-014-18 決済 NG ────────────────────────────────────────────────────────


async def test_it_014_18_payment_ng_store_order_hides_pickup_code(
    it_app: FastAPI, client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    member_id = await ph.member_id_of(seed_db)
    tok = await ph.make_session(seed_db, member_id)
    vid = await oh.stocked_variant_id(seed_db, 5)
    before = await oh.stock_of(seed_db, vid)
    token, prepared = await ph.cart_with(client, seed_db, (5, 1), receive_method="store")

    it_app.dependency_overrides[get_payment_adapter] = lambda: StubPaymentAdapter("ng")
    try:
        res = await client.post(
            "/api/v1/orders", json=ph.store_body(prepared), headers=ph.sess(tok, token)
        )
    finally:
        it_app.dependency_overrides.pop(get_payment_adapter, None)
    assert res.status_code == 409 and res.json()["code"] == "payment_failed", res.text
    number = res.json()["order_number"]
    assert "pickup_code" not in res.text

    assert await oh.scalar(seed_db, "SELECT status FROM orders") == "payment_failed"
    assert await oh.scalar(seed_db, "SELECT pickup_code FROM orders") is not None, "DB には残る"
    assert await oh.stock_of(seed_db, vid) == before
    assert (
        await oh.scalar(seed_db, "SELECT status FROM carts WHERE anonymous_token=:t", t=token)
        == "active"
    )

    res = await client.get(f"/api/v1/me/orders/{number}", headers=ph.sess(tok))
    assert res.status_code == 200
    assert res.json()["pickup_code"] is None and res.json()["status_label"] == "決済失敗"


# ── IT-023-03 店舗注文の照会 ─────────────────────────────────────────────────


async def test_it_023_03_lookup_of_store_order_returns_code_only_on_match(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    placed = await ph.place_order(client, seed_db, store_code="demo-fukuoka")
    number = placed["order_number"]
    res = await client.post(
        f"/api/v1/orders/{number}/lookup", json={"guest_email": "test@example.com"}, headers=oh.h()
    )
    assert res.status_code == 200, res.text
    assert res.json()["pickup_code"] == placed["pickup_code"]
    assert res.json()["store"]["name"] == seed_data.STORES[2].name
    res = await client.post(
        f"/api/v1/orders/{number}/lookup", json={"guest_email": "other@example.com"}, headers=oh.h()
    )
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    assert placed["pickup_code"] not in res.text
