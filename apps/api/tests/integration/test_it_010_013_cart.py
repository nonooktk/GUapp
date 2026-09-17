"""IT-010-01／IT-010-02／IT-011-01〜04／IT-012-01 カート API（MySQL・seed 必須）。

IT-011-01 は `httpx.AsyncClient` から `asyncio.gather` で同時 2 回送る（テスト設計書 1.4 #1・#3）。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import seed_data
from app.models import Cart, CartItem, CartStatus, Product, Variant
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}
CART_KEYS = {
    "cart_token", "items", "item_count", "subtotal", "shipping_fee", "total",
    "free_shipping_threshold", "can_checkout",
}
LINE_KEYS = {
    "item_id", "variant_id", "product_id", "product_name", "color", "size",
    "unit_price", "quantity", "line_total", "stock_status", "image_path",
}


@pytest.fixture
async def client(it_app: FastAPI, seed_db: AsyncEngine, client_factory):
    return client_factory(it_app)


def _h(token: str | None = None) -> dict[str, str]:
    h = dict(HEADERS)
    if token:
        h["X-Cart-Token"] = token
    return h


async def _variant_id(engine: AsyncEngine, sku: str) -> int:
    async with AsyncSession(engine) as session:
        return (await session.execute(select(Variant.id).where(Variant.sku == sku))).scalar_one()


async def _variant_ids_of_product(engine: AsyncEngine, number: int) -> list[int]:
    name = seed_data.PRODUCTS[number - 1].name
    async with AsyncSession(engine) as session:
        pid = (await session.execute(select(Product.id).where(Product.name == name))).scalar_one()
        rows = await session.execute(
            select(Variant.id).where(Variant.product_id == pid).order_by(Variant.id)
        )
        return list(rows.scalars().all())


async def _stocked_variant_id(engine: AsyncEngine, number: int = 1) -> int:
    """在庫が十分（≥ 5）な公開商品のバリエーション 1 つ。"""
    sku = seed_data.make_sku(number, seed_data.PRODUCTS[number - 1].colors[0], "M")
    assert sku not in seed_data.FIXED_STOCKS
    return await _variant_id(engine, sku)


async def _new_token(client) -> str:
    res = await client.get("/api/v1/cart", headers=_h())
    assert res.status_code == 200
    return res.json()["cart_token"]


# ── IT-010 ────────────────────────────────────────────────────────────────────


async def test_it_010_01_no_token_creates_cart_and_issues_token(client, seed_db) -> None:
    res = await client.get("/api/v1/cart", headers=_h())
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == CART_KEYS
    token = body["cart_token"]
    assert len(token) == 43
    assert body["items"] == [] and body["item_count"] == 0
    assert body["subtotal"] == body["shipping_fee"] == body["total"] == 0
    assert body["free_shipping_threshold"] == 4990
    assert body["can_checkout"] is False
    assert "cart_id" not in body

    # 同じトークンで再取得すると同じカート（新規発行されない）
    res2 = await client.get("/api/v1/cart", headers=_h(token))
    assert res2.json()["cart_token"] == token
    async with AsyncSession(seed_db) as session:
        carts = (await session.execute(select(Cart))).scalars().all()
    assert len(carts) == 1 and carts[0].status == CartStatus.active

    # 未知のトークンは無いものとして新規発行
    res3 = await client.get("/api/v1/cart", headers=_h("A" * 43))
    assert res3.status_code == 200 and res3.json()["cart_token"] != "A" * 43


async def test_it_010_02_ordered_cart_token_moves_to_new_active_cart(client, seed_db) -> None:
    token = await _new_token(client)
    vid = await _stocked_variant_id(seed_db)
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": vid, "quantity": 1}, headers=_h(token)
    )
    assert res.status_code == 201
    async with seed_db.begin() as conn:
        await conn.execute(
            update(Cart).where(Cart.anonymous_token == token).values(status=CartStatus.ordered)
        )
        old_id = (
            await conn.execute(select(Cart.id).where(Cart.anonymous_token == token))
        ).scalar_one()

    res = await client.get("/api/v1/cart", headers=_h(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cart_token"] == token  # 同じトークン
    assert body["items"] == []  # 新しい空カート

    async with AsyncSession(seed_db) as session:
        old = await session.get(Cart, old_id)
        new = (
            await session.execute(select(Cart).where(Cart.anonymous_token == token))
        ).scalar_one()
    assert old is not None and old.status == CartStatus.ordered
    assert old.anonymous_token is None  # 旧カートの token は NULL
    assert new.id != old_id and new.status == CartStatus.active


async def test_it_010_02_concurrent_get_on_ordered_cart_no_500(client, seed_db) -> None:
    """同じ ordered トークンで同時 GET → 両方 200・同じトークン・active カートは 1 つ。"""
    token = await _new_token(client)
    async with seed_db.begin() as conn:
        await conn.execute(
            update(Cart).where(Cart.anonymous_token == token).values(status=CartStatus.ordered)
        )
    r1, r2 = await asyncio.gather(
        client.get("/api/v1/cart", headers=_h(token)),
        client.get("/api/v1/cart", headers=_h(token)),
    )
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert r1.json()["cart_token"] == r2.json()["cart_token"] == token
    async with seed_db.connect() as conn:
        n = (
            await conn.execute(
                text("SELECT COUNT(*) FROM carts WHERE anonymous_token = :t AND status = 'active'"),
                {"t": token},
            )
        ).scalar_one()
    assert n == 1


# ── IT-011 ────────────────────────────────────────────────────────────────────


async def test_it_011_01_concurrent_add_same_variant_merges_into_one_line(
    client, seed_db
) -> None:
    token = await _new_token(client)
    vid = await _stocked_variant_id(seed_db)
    payload = {"variant_id": vid, "quantity": 1}
    r1, r2 = await asyncio.gather(
        client.post("/api/v1/cart/items", json=payload, headers=_h(token)),
        client.post("/api/v1/cart/items", json=payload, headers=_h(token)),
    )
    assert r1.status_code == 201 and r2.status_code == 201, (r1.text, r2.text)

    async with AsyncSession(seed_db) as session:
        lines = (await session.execute(select(CartItem))).scalars().all()
    assert len(lines) == 1
    assert lines[0].quantity == 2

    res = await client.get("/api/v1/cart", headers=_h(token))
    body = res.json()
    assert len(body["items"]) == 1
    line = body["items"][0]
    assert set(line) == LINE_KEYS
    assert line["quantity"] == 2 and line["stock_status"] == "ok"
    assert line["line_total"] == line["unit_price"] * 2
    assert body["item_count"] == 2
    assert body["subtotal"] == line["line_total"]
    assert body["can_checkout"] is True


async def test_it_011_01_add_without_token_creates_cart_then_adds(client, seed_db) -> None:
    vid = await _stocked_variant_id(seed_db)
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": vid, "quantity": 2}, headers=_h()
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert len(body["cart_token"]) == 43
    assert body["items"][0]["quantity"] == 2


async def test_it_011_02_stock0_is_409_and_unpublished_is_404(client, seed_db) -> None:
    token = await _new_token(client)
    stock0 = await _variant_id(seed_db, seed_data.TEST_SKU_STOCK0)
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": stock0, "quantity": 1}, headers=_h(token)
    )
    assert res.status_code == 409
    assert res.json() == {"code": "out_of_stock", "items": [stock0]}

    unpub_vids = await _variant_ids_of_product(seed_db, seed_data.TEST_PRODUCT_NUMBER_UNPUB)
    res = await client.post(
        "/api/v1/cart/items",
        json={"variant_id": unpub_vids[0], "quantity": 1},
        headers=_h(token),
    )
    assert res.status_code == 404 and res.json() == {"code": "not_found"}

    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": 999999, "quantity": 1}, headers=_h(token)
    )
    assert res.status_code == 404 and res.json() == {"code": "not_found"}

    # 何も追加されていない
    res = await client.get("/api/v1/cart", headers=_h(token))
    assert res.json()["items"] == []


async def test_it_011_02_quantity_over_stock_is_allowed_with_insufficient(client, seed_db) -> None:
    """数量 > 在庫 は許す（DS-PRC-011 追記）。stock_status=insufficient・can_checkout=false。"""
    token = await _new_token(client)
    stock1 = await _variant_id(seed_db, seed_data.TEST_SKU_STOCK1)
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": stock1, "quantity": 2}, headers=_h(token)
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["items"][0]["stock_status"] == "insufficient"
    assert body["can_checkout"] is False


async def test_it_011_03_quantity_boundaries(client, seed_db) -> None:
    token = await _new_token(client)
    vid = await _stocked_variant_id(seed_db)

    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": vid, "quantity": 10}, headers=_h(token)
    )
    assert res.status_code == 201, res.text
    assert res.json()["items"][0]["quantity"] == 10

    # 10 → 11 は 422（加算が戻る）
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": vid, "quantity": 1}, headers=_h(token)
    )
    assert res.status_code == 422
    assert res.json() == {"code": "limit_exceeded", "field": "quantity", "limit": 10}
    async with AsyncSession(seed_db) as session:
        qty = (await session.execute(select(CartItem.quantity))).scalar_one()
    assert qty == 10

    # 別カートで 11 を一発 → 422
    token2 = await _new_token(client)
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": vid, "quantity": 11}, headers=_h(token2)
    )
    assert res.status_code == 422
    async with AsyncSession(seed_db) as session:
        n = len((await session.execute(select(CartItem))).scalars().all())
    assert n == 1  # 戻っている

    for bad in (0, -1):
        res = await client.post(
            "/api/v1/cart/items", json={"variant_id": vid, "quantity": bad}, headers=_h(token2)
        )
        assert res.status_code == 400, res.text
        assert res.json() == {
            "code": "validation_error",
            "fields": [{"name": "quantity", "reason": "out_of_range"}],
        }
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": vid, "quantity": "x"}, headers=_h(token2)
    )
    assert res.status_code == 400
    assert res.json()["fields"] == [{"name": "quantity", "reason": "format"}]


async def test_it_011_04_cart_total_50_ok_51_rejected(client, seed_db) -> None:
    token = await _new_token(client)
    # 5 バリエーション × 10 = 50
    vids = await _variant_ids_of_product(seed_db, 1)  # 商品 1（在庫 5〜30・公開）
    assert len(vids) == 6
    for vid in vids[:5]:
        res = await client.post(
            "/api/v1/cart/items", json={"variant_id": vid, "quantity": 10}, headers=_h(token)
        )
        assert res.status_code == 201, res.text
    assert res.json()["item_count"] == 50

    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": vids[5], "quantity": 1}, headers=_h(token)
    )
    assert res.status_code == 422
    assert res.json() == {"code": "limit_exceeded", "field": "quantity", "limit": 50}
    res = await client.get("/api/v1/cart", headers=_h(token))
    assert res.json()["item_count"] == 50 and len(res.json()["items"]) == 5


# ── IT-012 ────────────────────────────────────────────────────────────────────


async def test_it_012_01_patch_and_delete_reflect_and_foreign_item_is_404(
    client, seed_db
) -> None:
    token = await _new_token(client)
    vid = await _stocked_variant_id(seed_db)
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": vid, "quantity": 1}, headers=_h(token)
    )
    item_id = res.json()["items"][0]["item_id"]

    res = await client.patch(
        f"/api/v1/cart/items/{item_id}", json={"quantity": 3}, headers=_h(token)
    )
    assert res.status_code == 200, res.text
    assert res.json()["items"][0]["quantity"] == 3 and res.json()["item_count"] == 3

    # 上限規則は PATCH にも適用
    res = await client.patch(
        f"/api/v1/cart/items/{item_id}", json={"quantity": 11}, headers=_h(token)
    )
    assert res.status_code == 422
    res = await client.patch(
        f"/api/v1/cart/items/{item_id}", json={"quantity": 0}, headers=_h(token)
    )
    assert res.status_code == 400

    # 他人のカートからは 404（PATCH・DELETE とも）
    other = await _new_token(client)
    res = await client.patch(
        f"/api/v1/cart/items/{item_id}", json={"quantity": 2}, headers=_h(other)
    )
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    res = await client.delete(f"/api/v1/cart/items/{item_id}", headers=_h(other))
    assert res.status_code == 404
    res = await client.get("/api/v1/cart", headers=_h(token))
    assert res.json()["items"][0]["quantity"] == 3  # 影響なし

    # 自分のカートから削除 → 空
    res = await client.delete(f"/api/v1/cart/items/{item_id}", headers=_h(token))
    assert res.status_code == 200, res.text
    assert res.json()["items"] == [] and res.json()["total"] == 0
    res = await client.delete(f"/api/v1/cart/items/{item_id}", headers=_h(token))
    assert res.status_code == 404
    res = await client.delete("/api/v1/cart/items/999999", headers=_h(token))
    assert res.status_code == 404


async def test_it_cart_totals_match_pricing_rule(client, seed_db) -> None:
    """1,990 + 2,990 = 4,980 → 送料 550。2,990×2 = 5,980 → 送料 0。"""
    token = await _new_token(client)
    v1990 = await _stocked_variant_id(seed_db, 5)  # イージーワイドパンツ 1,990
    v2990 = await _stocked_variant_id(seed_db, 3)  # オーバーサイズシャツ 2,990
    assert seed_data.PRODUCTS[4].price_incl_tax == 1990
    assert seed_data.PRODUCTS[2].price_incl_tax == 2990
    await client.post(
        "/api/v1/cart/items", json={"variant_id": v1990, "quantity": 1}, headers=_h(token)
    )
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": v2990, "quantity": 1}, headers=_h(token)
    )
    body = res.json()
    assert (body["subtotal"], body["shipping_fee"], body["total"]) == (4980, 550, 5530)

    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": v2990, "quantity": 1}, headers=_h(token)
    )
    body = res.json()
    assert (body["subtotal"], body["shipping_fee"], body["total"]) == (7970, 0, 7970)
