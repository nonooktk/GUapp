"""P2-b レーン C の IT 共通ヘルパー（会員セッション・店舗受け取り注文・注文行の直接投入）。

会員とセッションは DB へ直接入れる（ログイン API はレーン B の担当。ここでは `sessions` の
SHA-256 だけを使う `core/session.py` の仕様に合わせる）。氏名・メールはダミーに限る。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.session import hash_token
from app.services.order_number import generate_order_number
from tests.integration import order_helpers as oh

DEMO_MEMBER_EMAIL = "demo-member1@example.com"  # pragma: allowlist secret
OTHER_MEMBER_EMAIL = "demo-member2@example.com"  # pragma: allowlist secret
NO_ORDER_MEMBER_EMAIL = "demo-member4@example.com"  # pragma: allowlist secret


def utcnow() -> datetime:
    """DB は UTC の naive datetime。"""
    return datetime.now(UTC).replace(tzinfo=None)


async def member_id_of(engine: AsyncEngine, email: str = DEMO_MEMBER_EMAIL) -> int:
    return int(await oh.scalar(engine, "SELECT id FROM members WHERE email = :e", e=email))


async def make_session(
    engine: AsyncEngine,
    member_id: int,
    *,
    ttl: timedelta = timedelta(hours=1),
    subject_type: str = "member",
) -> str:
    """有効（既定）または期限切れ（負の ttl）・staff 種別のセッションを入れ、生の値を返す。"""
    token = secrets.token_urlsafe(32)
    assert len(token) == 43
    now = utcnow()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO sessions (token_hash, subject_type, subject_id, expires_at,"
                " last_seen_at) VALUES (:h, :t, :s, :x, :n)"
            ),
            {
                "h": hash_token(token),
                "t": subject_type,
                "s": member_id,
                "x": now + ttl,
                "n": now,
            },
        )
    return token


def sess(token: str | None, cart_token: str | None = None) -> dict[str, str]:
    """内部トークン + `X-Session-Token`（+ `X-Cart-Token`）。"""
    headers = oh.h(cart_token)
    if token is not None:
        headers["X-Session-Token"] = token
    return headers


async def cart_with(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    *lines: tuple[int, int],
    receive_method: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """(product_number, quantity) の明細を持つカートを作り、(カート token, prepare 応答)。"""
    token = await oh.new_token(client)
    for number, qty in lines:
        await oh.add_item(client, token, await oh.stocked_variant_id(engine, number), qty)
    if receive_method is None:
        return token, await oh.prepare(client, token)
    res = await client.post(
        "/api/v1/checkout/prepare", json={"receive_method": receive_method}, headers=oh.h(token)
    )
    assert res.status_code == 200, res.text
    return token, res.json()


def store_body(prepared: dict[str, Any], store_code: str = "demo-tokyo", **over: Any) -> dict:
    """店舗受け取りの注文本文（`ship_postal_code`・`ship_address` なし）。"""
    body = oh.order_body(prepared, receive_method="store", store_code=store_code)
    body.pop("ship_postal_code")
    body.pop("ship_address")
    body.update(over)
    return body


async def place_order(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    *,
    session_token: str | None = None,
    store_code: str | None = None,
    product_number: int = 5,
    quantity: int = 1,
    **over: Any,
) -> dict[str, Any]:
    """カート作成 → prepare → 注文確定（201 を期待）。応答 JSON を返す。"""
    method = "store" if store_code is not None else None
    token, prepared = await cart_with(
        client, engine, (product_number, quantity), receive_method=method
    )
    body = (
        store_body(prepared, store_code, **over)
        if store_code is not None
        else oh.order_body(prepared, **over)
    )
    res = await client.post("/api/v1/orders", json=body, headers=sess(session_token, token))
    assert res.status_code == 201, res.text
    return res.json()


async def set_order(engine: AsyncEngine, order_number: str, **columns: Any) -> None:
    """注文の列を直接書き換える（状態・追跡番号など）。"""
    assignments = ", ".join(f"`{k}` = :{k}" for k in columns)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE orders SET {assignments} WHERE order_number = :__n"),
            {**columns, "__n": order_number},
        )


async def insert_order(
    engine: AsyncEngine,
    *,
    member_id: int | None,
    status: str = "accepted",
    receive_method: str = "delivery",
    store_code: str | None = None,
    pickup_code: str | None = None,
    tracking_number: str | None = None,
    created_at: datetime | None = None,
    guest_email: str = "test@example.com",
    items: tuple[tuple[str, int], ...] = (("テスト商品", 1),),
    variant_id: int | None = None,
) -> str:
    """カート・注文・明細を直接入れて注文番号を返す（件数や状態を作るための近道）。"""
    created = created_at or utcnow()
    number = generate_order_number()
    price = 1990
    subtotal = sum(price * q for _, q in items)
    async with engine.begin() as conn:
        cart_id = (
            await conn.execute(
                text(
                    "INSERT INTO carts (anonymous_token, status, created_at, updated_at)"
                    " VALUES (:t, 'ordered', :c, :c)"
                ),
                {"t": secrets.token_urlsafe(32), "c": created},
            )
        ).lastrowid
        store_id = None
        postal, address = "1000001", "東京都千代田区千代田1-1 テストビル101"
        if store_code is not None:
            row = (
                await conn.execute(
                    text("SELECT id, postal_code, address FROM stores WHERE code = :c"),
                    {"c": store_code},
                )
            ).one()
            store_id, postal, address = row[0], row[1], row[2]
        order_id = (
            await conn.execute(
                text(
                    "INSERT INTO orders (order_number, idempotency_key, member_id, guest_email,"
                    " status, receive_method, store_id, pickup_code, tracking_number, subtotal,"
                    " shipping_fee, discount, total, tax_rate_at_order, ship_name,"
                    " ship_postal_code, ship_address, ship_phone, cart_id, created_at, updated_at)"
                    " VALUES (:n, :k, :m, :e, :s, :rm, :sid, :pc, :tn, :sub, 0, 0, :sub, '0.10',"
                    " 'テスト 太郎', :pos, :adr, '09012345678', :cid, :c, :c)"
                ),
                {
                    "n": number,
                    "k": secrets.token_urlsafe(32),
                    "m": member_id,
                    "e": guest_email,
                    "s": status,
                    "rm": receive_method,
                    "sid": store_id,
                    "pc": pickup_code,
                    "tn": tracking_number,
                    "sub": subtotal,
                    "pos": postal,
                    "adr": address,
                    "cid": cart_id,
                    "c": created,
                },
            )
        ).lastrowid
        if variant_id is None:
            variant_id = int(
                (await conn.execute(text("SELECT MIN(id) FROM variants"))).scalar_one()
            )
        for name, qty in items:
            await conn.execute(
                text(
                    "INSERT INTO order_items (order_id, variant_id, product_name_at_order, color,"
                    " size, unit_price_at_order, quantity, discount, created_at, updated_at)"
                    " VALUES (:o, :v, :nm, '黒', 'M', :p, :q, 0, :c, :c)"
                ),
                {"o": order_id, "v": variant_id, "nm": name, "p": price, "q": qty, "c": created},
            )
    return number
