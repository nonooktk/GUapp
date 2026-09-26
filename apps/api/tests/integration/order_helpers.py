"""注文系 IT の共通ヘルパー（in-process クライアントと live_server の両方で使う）。

配送先はすべてダミー（テスト設計書 1.3。実在の個人情報ではない）。
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from app.models import Variant
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}

DUMMY_SHIPPING: dict[str, str] = {
    "ship_name": "テスト 太郎",
    "ship_postal_code": "100-0001",
    "ship_address": "東京都千代田区千代田1-1 テストビル101",
    "ship_phone": "090-1234-5678",
    "guest_email": "test@example.com",
}

ORDER_KEYS = {
    "order_number",
    "status",
    "items",
    "subtotal",
    "shipping_fee",
    "total",
    "tax_included",
    "tax_rate",
    "ship_name",
    "ship_postal_code",
    "ship_address",
    "ship_phone",
    "guest_email",
    "receive_method",
    "payment_method",
    "ordered_at",
}
ORDER_ITEM_KEYS = {"product_name", "color", "size", "unit_price", "quantity", "line_total"}


def h(token: str | None = None) -> dict[str, str]:
    headers = dict(HEADERS)
    if token:
        headers["X-Cart-Token"] = token
    return headers


def order_body(prepared: dict[str, Any], **over: Any) -> dict[str, Any]:
    """prepare の応答から注文本文を作る。"""
    body: dict[str, Any] = {
        "idempotency_key": prepared["idempotency_key"],
        **DUMMY_SHIPPING,
        "receive_method": "delivery",
        "payment_method": "card",
        "display": {
            "subtotal": prepared["subtotal"],
            "shipping_fee": prepared["shipping_fee"],
            "total": prepared["total"],
        },
    }
    body.update(over)
    return body


async def new_token(client: httpx.AsyncClient) -> str:
    res = await client.get("/api/v1/cart", headers=h())
    assert res.status_code == 200, res.text
    return res.json()["cart_token"]


async def add_item(client: httpx.AsyncClient, token: str, variant_id: int, quantity: int) -> None:
    res = await client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": quantity},
        headers=h(token),
    )
    assert res.status_code == 201, res.text


async def prepare(client: httpx.AsyncClient, token: str) -> dict[str, Any]:
    res = await client.post("/api/v1/checkout/prepare", headers=h(token))
    assert res.status_code == 200, res.text
    return res.json()


async def variant_id(engine: AsyncEngine, sku: str) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(select(Variant.id).where(Variant.sku == sku))).scalar_one())


async def stocked_variant_id(engine: AsyncEngine, number: int) -> int:
    """在庫が十分（≥ 5）な公開商品のバリエーション（色 1・サイズ M）。"""
    sku = seed_data.make_sku(number, seed_data.PRODUCTS[number - 1].colors[0], "M")
    assert sku not in seed_data.FIXED_STOCKS
    return await variant_id(engine, sku)


async def stock_of(engine: AsyncEngine, vid: int) -> int:
    async with engine.connect() as conn:
        stmt = select(Variant.stock).where(Variant.id == vid)
        return int((await conn.execute(stmt)).scalar_one())


async def set_stock(engine: AsyncEngine, vid: int, stock: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE variants SET stock = :s WHERE id = :id"), {"s": stock, "id": vid}
        )


async def count_rows(engine: AsyncEngine, table: str, where: str = "1=1", **params: Any) -> int:
    assert table in {"orders", "order_items", "payments", "audit_logs", "carts", "cart_items"}
    async with engine.connect() as conn:
        return int(
            (
                await conn.execute(text(f"SELECT COUNT(*) FROM `{table}` WHERE {where}"), params)
            ).scalar_one()
        )


async def scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one_or_none()


def order_total(unit_prices_and_quantities: list[tuple[int, int]]) -> tuple[int, int, int]:
    """テスト側で独立に計算した (小計, 送料, 合計)。API の値と突き合わせる。"""
    subtotal = sum(p * q for p, q in unit_prices_and_quantities)
    shipping = 0 if subtotal >= 4990 else 550
    return subtotal, shipping, subtotal + shipping


__all__ = ["func"]
