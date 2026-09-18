"""確認画面用の金額計算と冪等キー発行（DS-API-021・DS-PRC-021）。

- カート無し／未知 → 404、`ordered` → 409 already_ordered
- 空カート → 409 empty_cart、`stock_status` が ok 以外の明細 → 409 out_of_stock {items}
- 金額は `services/pricing`（カート応答と同じ計算）。冪等キーは 32 バイト乱数の base64url（43 文字）
"""

from __future__ import annotations

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Cart, CartStatus
from app.repositories import carts as carts_repo
from app.repositories import orders as orders_repo
from app.schemas.cart import CartLineOut
from app.schemas.order import PrepareOut
from app.services import cart_rules
from app.services.pricing import calc_totals
from app.services.settings import get_public_settings


def new_idempotency_key() -> str:
    return secrets.token_urlsafe(32)


async def resolve_existing_cart(session: AsyncSession, token: str | None) -> Cart:
    """既存カートだけを返す（新規発行はしない）。無い／未知 → 404。"""
    normalized = cart_rules.normalize_token(token)
    cart = await carts_repo.get_by_token(session, normalized) if normalized else None
    if cart is None:
        raise AppError(404, "not_found")
    return cart


async def prepare(session: AsyncSession, token: str | None) -> PrepareOut:
    cart = await resolve_existing_cart(session, token)
    if cart.status != CartStatus.active:
        number = await orders_repo.get_latest_order_number_of_cart(session, cart.id)
        raise AppError(409, "already_ordered", order_number=number)

    settings = await get_public_settings(session)
    rows = await carts_repo.fetch_lines(session, cart.id)
    if not rows:
        raise AppError(409, "empty_cart")

    items: list[CartLineOut] = []
    not_ok: list[int] = []
    for r in rows:
        status = cart_rules.stock_status(stock=r.stock, quantity=r.quantity, published=r.published)
        if status != "ok":
            not_ok.append(r.variant_id)
        items.append(
            CartLineOut(
                item_id=r.item_id,
                variant_id=r.variant_id,
                product_id=r.product_id,
                product_name=r.product_name,
                color=r.color,
                size=r.size,
                unit_price=r.unit_price,
                quantity=r.quantity,
                line_total=r.unit_price * r.quantity,
                stock_status=status,
                image_path=r.image_path,
            )
        )
    if not_ok:
        raise AppError(409, "out_of_stock", items=not_ok)

    totals = calc_totals([(r.unit_price, r.quantity) for r in rows], settings)
    return PrepareOut(
        idempotency_key=new_idempotency_key(),
        items=items,
        subtotal=totals.subtotal,
        shipping_fee=totals.shipping_fee,
        total=totals.total,
        tax_included=totals.tax_included,
        tax_rate=settings.tax_rate,
        free_shipping_threshold=settings.free_shipping_threshold,
    )
