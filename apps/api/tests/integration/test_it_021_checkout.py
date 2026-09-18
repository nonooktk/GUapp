"""IT-021-01／02 確認画面用の金額計算・冪等キー発行（MySQL・seed 必須）。"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from app.services.pricing import PricingSettings, calc_totals
from tests.integration import order_helpers as oh

PREPARE_KEYS = {
    "idempotency_key", "items", "subtotal", "shipping_fee", "total", "tax_included",
    "tax_rate", "free_shipping_threshold",
}
LINE_KEYS = {
    "item_id", "variant_id", "product_id", "product_name", "color", "size",
    "unit_price", "quantity", "line_total", "stock_status", "image_path",
}


@pytest.fixture
async def client(it_app: FastAPI, seed_db: AsyncEngine, client_factory):
    return client_factory(it_app)


async def test_it_021_01_amounts_match_pricing_and_key_is_43_chars(client, seed_db) -> None:
    token = await oh.new_token(client)
    v1990 = await oh.stocked_variant_id(seed_db, 5)  # 1,990
    v2990 = await oh.stocked_variant_id(seed_db, 3)  # 2,990
    await oh.add_item(client, token, v1990, 1)
    await oh.add_item(client, token, v2990, 1)

    body = await oh.prepare(client, token)
    assert set(body) == PREPARE_KEYS
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", body["idempotency_key"])
    assert len(body["items"]) == 2 and all(set(i) == LINE_KEYS for i in body["items"])
    assert all(i["stock_status"] == "ok" for i in body["items"])

    expected = calc_totals(
        [(1990, 1), (2990, 1)],
        PricingSettings(tax_rate="0.10", shipping_fee=550, free_shipping_threshold=4990),
    )
    assert (body["subtotal"], body["shipping_fee"], body["total"]) == (4980, 550, 5530)
    assert body["tax_included"] == expected.tax_included == 502
    assert body["tax_rate"] == "0.10" and body["free_shipping_threshold"] == 4990

    # 呼ぶたびに新しいキー（同じ金額）
    body2 = await oh.prepare(client, token)
    assert body2["idempotency_key"] != body["idempotency_key"]
    assert body2["total"] == body["total"]

    # 送料無料の境界: 2,990 を足して 7,970 → 送料 0
    await oh.add_item(client, token, v2990, 1)
    body3 = await oh.prepare(client, token)
    assert (body3["subtotal"], body3["shipping_fee"], body3["total"]) == (7970, 0, 7970)
    assert "cart_id" not in body3


async def test_it_021_02_empty_cart_and_out_of_stock_are_409(client, seed_db) -> None:
    token = await oh.new_token(client)
    res = await client.post("/api/v1/checkout/prepare", headers=oh.h(token))
    assert res.status_code == 409 and res.json() == {"code": "empty_cart"}

    # 在庫 1 に数量 2（insufficient）→ out_of_stock に variant_id
    stock1 = await oh.variant_id(seed_db, seed_data.TEST_SKU_STOCK1)
    await oh.add_item(client, token, stock1, 2)
    res = await client.post("/api/v1/checkout/prepare", headers=oh.h(token))
    assert res.status_code == 409, res.text
    assert res.json() == {"code": "out_of_stock", "items": [stock1]}

    # 追加後に非公開になった商品も out_of_stock 扱い
    token2 = await oh.new_token(client)
    vid = await oh.stocked_variant_id(seed_db, 1)
    await oh.add_item(client, token2, vid, 1)
    async with seed_db.begin() as conn:
        await conn.execute(
            text(
                "UPDATE products SET published = 0"
                " WHERE id = (SELECT product_id FROM variants WHERE id = :v)"
            ),
            {"v": vid},
        )
    res = await client.post("/api/v1/checkout/prepare", headers=oh.h(token2))
    assert res.status_code == 409 and res.json() == {"code": "out_of_stock", "items": [vid]}


async def test_it_021_02_no_or_unknown_token_is_404_and_ordered_is_409(client, seed_db) -> None:
    res = await client.post("/api/v1/checkout/prepare", headers=oh.h())
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    res = await client.post("/api/v1/checkout/prepare", headers=oh.h("A" * 43))
    assert res.status_code == 404

    token = await oh.new_token(client)
    async with seed_db.begin() as conn:
        await conn.execute(
            text("UPDATE carts SET status = 'ordered' WHERE anonymous_token = :t"), {"t": token}
        )
    res = await client.post("/api/v1/checkout/prepare", headers=oh.h(token))
    assert res.status_code == 409 and res.json()["code"] == "already_ordered"
