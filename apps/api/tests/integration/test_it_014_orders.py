"""IT-014-01／05〜09・冪等キーの IDOR 注文確定（MySQL・seed 必須・in-process クライアント）。

同時実行（IT-014-02〜04）は live_server を使う別モジュール。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from app.adapters.mail import DEFAULT_OUTBOX_DIR, get_mail_adapter
from app.adapters.payment import StubPaymentAdapter, get_payment_adapter
from app.schemas.order import OrderOut
from tests.integration import order_helpers as oh

ORDER_NUMBER_RE = re.compile(r"^GU-\d{6}-[A-HJ-NP-Z2-9]{8}$")


@pytest.fixture
async def client(it_app: FastAPI, seed_db: AsyncEngine, client_factory):
    return client_factory(it_app)


async def _cart_with(client, engine: AsyncEngine, *lines: tuple[int, int]) -> tuple[str, dict]:
    """(product_number, quantity) の明細を持つカートを作り、(token, prepare 応答) を返す。"""
    token = await oh.new_token(client)
    for number, qty in lines:
        vid = await oh.stocked_variant_id(engine, number)
        await oh.add_item(client, token, vid, qty)
    return token, await oh.prepare(client, token)


def _outbox_file(order_number: str) -> Path:
    return DEFAULT_OUTBOX_DIR / f"{order_number}.txt"


# ── IT-014-01 ────────────────────────────────────────────────────────────────


async def test_it_014_01_happy_path_creates_all_rows_and_mail(client, seed_db) -> None:
    token, prepared = await _cart_with(client, seed_db, (5, 2), (3, 1))  # 1,990×2 + 2,990
    vid_5 = await oh.stocked_variant_id(seed_db, 5)
    vid_3 = await oh.stocked_variant_id(seed_db, 3)
    stock_5, stock_3 = await oh.stock_of(seed_db, vid_5), await oh.stock_of(seed_db, vid_3)
    assert (prepared["subtotal"], prepared["shipping_fee"], prepared["total"]) == (6970, 0, 6970)

    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body) == oh.ORDER_KEYS
    assert ORDER_NUMBER_RE.match(body["order_number"])
    assert body["status"] == "accepted"
    assert len(body["items"]) == 2 and all(set(i) == oh.ORDER_ITEM_KEYS for i in body["items"])
    assert (body["subtotal"], body["shipping_fee"], body["total"]) == (6970, 0, 6970)
    assert body["tax_included"] == 6970 * 10 // 110 == 633
    assert body["ship_postal_code"] == "1000001" and body["ship_phone"] == "09012345678"
    assert body["guest_email"] == "test@example.com"
    assert body["receive_method"] == "delivery" and body["payment_method"] == "card"
    assert body["ordered_at"].endswith("Z") or "+00:00" in body["ordered_at"]
    OrderOut.model_validate(body)
    for hidden in ("id", "cart_id", "variant_id", "order_id"):
        assert hidden not in res.text.split('"items"')[0]

    number = body["order_number"]
    assert await oh.count_rows(seed_db, "orders") == 1
    assert await oh.scalar(seed_db, "SELECT status FROM orders") == "accepted"
    assert await oh.count_rows(seed_db, "order_items") == 2
    assert await oh.count_rows(seed_db, "payments", "provider='stub' AND result='ok'") == 1
    assert (
        await oh.count_rows(
            seed_db, "audit_logs", "action='order.confirm' AND target_id=:n", n=number
        )
        == 1
    )
    assert await oh.count_rows(seed_db, "audit_logs") == 1
    assert await oh.stock_of(seed_db, vid_5) == stock_5 - 2
    assert await oh.stock_of(seed_db, vid_3) == stock_3 - 1
    assert await oh.scalar(seed_db, "SELECT status FROM carts") == "ordered"
    # 確定時単価・商品名が保存されている
    unit = await oh.scalar(
        seed_db, "SELECT unit_price_at_order FROM order_items WHERE variant_id=:v", v=vid_5
    )
    assert unit == 1990

    path = _outbox_file(number)
    try:
        assert path.exists()
        text_ = path.read_text(encoding="utf-8")
        assert number in text_ and "6,970" in text_
    finally:
        path.unlink(missing_ok=True)

    # 注文後に同じトークンで GET /cart → 新しい空カート（IT-010-02）
    res = await client.get("/api/v1/cart", headers=oh.h(token))
    assert res.status_code == 200 and res.json()["items"] == []


# ── IT-014-05 金額改ざん ─────────────────────────────────────────────────────


async def test_it_014_05_tampered_total_is_409_price_changed_and_nothing_persists(
    client, seed_db
) -> None:
    token, prepared = await _cart_with(client, seed_db, (5, 2))
    vid = await oh.stocked_variant_id(seed_db, 5)
    before = await oh.stock_of(seed_db, vid)

    body = oh.order_body(prepared)
    body["display"]["total"] -= 1
    res = await client.post("/api/v1/orders", json=body, headers=oh.h(token))
    assert res.status_code == 409, res.text
    assert res.json() == {
        "code": "price_changed",
        "amounts": {
            "subtotal": prepared["subtotal"],
            "shipping_fee": prepared["shipping_fee"],
            "total": prepared["total"],
        },
    }
    assert await oh.count_rows(seed_db, "orders") == 0
    assert await oh.count_rows(seed_db, "order_items") == 0
    assert await oh.count_rows(seed_db, "payments") == 0
    assert await oh.stock_of(seed_db, vid) == before
    assert await oh.scalar(seed_db, "SELECT status FROM carts") == "active"

    # 価格改定後に古い表示金額で確定 → price_changed（amounts は新価格）
    async with seed_db.begin() as conn:
        await conn.execute(
            text("UPDATE products SET price_incl_tax = 2090 WHERE name = :n"),
            {"n": seed_data.PRODUCTS[4].name},
        )
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    assert res.status_code == 409 and res.json()["code"] == "price_changed"
    assert res.json()["amounts"]["subtotal"] == 4180


# ── IT-014-06 決済 NG ────────────────────────────────────────────────────────


async def test_it_014_06_payment_ng_keeps_failed_order_and_restores_stock_and_cart(
    it_app: FastAPI, client, seed_db
) -> None:
    token, prepared = await _cart_with(client, seed_db, (5, 1))
    vid = await oh.stocked_variant_id(seed_db, 5)
    before = await oh.stock_of(seed_db, vid)

    it_app.dependency_overrides[get_payment_adapter] = lambda: StubPaymentAdapter("ng")
    try:
        res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    finally:
        it_app.dependency_overrides.pop(get_payment_adapter, None)
    assert res.status_code == 409, res.text
    failed = res.json()
    assert failed["code"] == "payment_failed" and ORDER_NUMBER_RE.match(failed["order_number"])

    assert await oh.count_rows(seed_db, "orders", "status='payment_failed'") == 1
    assert await oh.count_rows(seed_db, "orders") == 1
    assert await oh.count_rows(seed_db, "payments", "result='ng'") == 1
    assert await oh.count_rows(seed_db, "order_items") == 0
    assert await oh.count_rows(seed_db, "audit_logs", "action='order.payment_failed'") == 1
    assert await oh.stock_of(seed_db, vid) == before
    assert await oh.scalar(seed_db, "SELECT status FROM carts") == "active"

    # 同じキーの再送は 409 payment_failed（同じ番号）
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    assert res.status_code == 409 and res.json() == failed

    # prepare を呼び直すと新しいキーが出て再注文できる（既定アダプタ = ok）
    prepared2 = await oh.prepare(client, token)
    assert prepared2["idempotency_key"] != prepared["idempotency_key"]
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared2), headers=oh.h(token))
    assert res.status_code == 201, res.text
    assert res.json()["order_number"] != failed["order_number"]
    assert await oh.count_rows(seed_db, "orders", "status='accepted'") == 1
    assert await oh.stock_of(seed_db, vid) == before - 1
    _outbox_file(res.json()["order_number"]).unlink(missing_ok=True)


# ── IT-014-07 引当失敗 ───────────────────────────────────────────────────────


async def test_it_014_07_reserve_failure_rolls_back_and_lists_variants(client, seed_db) -> None:
    stock1 = await oh.variant_id(seed_db, seed_data.TEST_SKU_STOCK1)
    token = await oh.new_token(client)
    await oh.add_item(client, token, stock1, 1)
    vid_ok = await oh.stocked_variant_id(seed_db, 5)
    await oh.add_item(client, token, vid_ok, 1)
    prepared = await oh.prepare(client, token)
    ok_before = await oh.stock_of(seed_db, vid_ok)

    # 確認画面の後に他の誰かが最後の 1 点を買った
    await oh.set_stock(seed_db, stock1, 0)
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    assert res.status_code == 409, res.text
    assert res.json() == {"code": "out_of_stock", "items": [stock1]}
    assert await oh.count_rows(seed_db, "orders") == 0
    assert await oh.count_rows(seed_db, "order_items") == 0
    assert await oh.stock_of(seed_db, vid_ok) == ok_before  # 先に引当した分も戻っている
    assert await oh.scalar(seed_db, "SELECT status FROM carts") == "active"


# ── IT-014-08 確定時単価 ─────────────────────────────────────────────────────


async def test_it_014_08_price_change_after_confirm_does_not_affect_order(
    client, seed_db
) -> None:
    token, prepared = await _cart_with(client, seed_db, (5, 2))
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    assert res.status_code == 201, res.text
    number = res.json()["order_number"]
    _outbox_file(number).unlink(missing_ok=True)

    async with seed_db.begin() as conn:
        await conn.execute(
            text("UPDATE products SET price_incl_tax = 9990, name = '改名後' WHERE name = :n"),
            {"n": seed_data.PRODUCTS[4].name},
        )
    assert await oh.scalar(seed_db, "SELECT unit_price_at_order FROM order_items") == 1990
    assert await oh.scalar(seed_db, "SELECT product_name_at_order FROM order_items") == (
        seed_data.PRODUCTS[4].name
    )
    assert await oh.scalar(seed_db, "SELECT total FROM orders") == prepared["total"]

    res = await client.post(
        f"/api/v1/orders/{number}/lookup",
        json={"guest_email": "test@example.com"},
        headers=oh.h(),
    )
    assert res.status_code == 200
    assert res.json()["items"][0]["unit_price"] == 1990
    assert res.json()["items"][0]["product_name"] == seed_data.PRODUCTS[4].name
    assert res.json()["total"] == prepared["total"]


# ── IT-014-09 メール失敗 ─────────────────────────────────────────────────────


class _BrokenMail:
    async def send_order_confirmation(self, order) -> None:
        raise OSError("outbox unavailable")


async def test_it_014_09_mail_failure_still_201_and_audited(
    it_app: FastAPI, client, seed_db
) -> None:
    token, prepared = await _cart_with(client, seed_db, (5, 1))
    it_app.dependency_overrides[get_mail_adapter] = lambda: _BrokenMail()
    try:
        res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    finally:
        it_app.dependency_overrides.pop(get_mail_adapter, None)
    assert res.status_code == 201, res.text
    number = res.json()["order_number"]
    assert await oh.scalar(seed_db, "SELECT status FROM orders") == "accepted"
    assert await oh.count_rows(seed_db, "audit_logs", "action='order.confirm'") == 1
    mail_failed = await oh.count_rows(
        seed_db, "audit_logs", "action='mail.failed' AND target_id=:n", n=number
    )
    assert mail_failed == 1
    assert not _outbox_file(number).exists()


# ── 冪等キーと所有者（7.5）／422 ─────────────────────────────────────────────


async def test_it_014_idempotency_key_of_other_cart_is_404_and_retry_is_200(
    client, seed_db
) -> None:
    token, prepared = await _cart_with(client, seed_db, (5, 1))
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    assert res.status_code == 201, res.text
    first = res.json()
    _outbox_file(first["order_number"]).unlink(missing_ok=True)

    # 同じカート（ordered 済み）から同じキーを再送 → 200 で同じ注文
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    assert res.status_code == 200, res.text
    assert res.json() == first

    # 別カートのトークンで同じキー → 404（他人の注文は見えない）
    other = await oh.new_token(client)
    vid = await oh.stocked_variant_id(seed_db, 5)
    await oh.add_item(client, other, vid, 1)
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(other))
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    assert await oh.count_rows(seed_db, "orders") == 1

    # 同じカートで異なるキー（直列）→ 409 already_ordered に既存番号
    prepared_b = dict(prepared, idempotency_key="B" * 43)
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared_b), headers=oh.h(token))
    assert res.status_code == 409
    assert res.json() == {"code": "already_ordered", "order_number": first["order_number"]}

    # トークン無し／未知 → 404
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h())
    assert res.status_code == 404
    res = await client.post(
        "/api/v1/orders", json=oh.order_body(prepared), headers=oh.h("Z" * 43)
    )
    assert res.status_code == 404


async def test_it_014_unsupported_receive_or_payment_method_is_422(client, seed_db) -> None:
    token, prepared = await _cart_with(client, seed_db, (5, 1))
    res = await client.post(
        "/api/v1/orders", json=oh.order_body(prepared, receive_method="store"), headers=oh.h(token)
    )
    assert res.status_code == 422
    assert res.json() == {"code": "unsupported_value", "field": "receive_method"}
    res = await client.post(
        "/api/v1/orders", json=oh.order_body(prepared, payment_method="cod"), headers=oh.h(token)
    )
    assert res.status_code == 422
    assert res.json() == {"code": "unsupported_value", "field": "payment_method"}
    assert await oh.count_rows(seed_db, "orders") == 0
    assert await oh.scalar(seed_db, "SELECT status FROM carts") == "active"
