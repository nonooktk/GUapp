"""カート（DS-API-010〜013・DS-PRC-011）のサービス。

トークンの扱い（DS-API-010）:
- ヘッダ無し／未知 → 新カート＋新トークン発行
- トークンのカートが `ordered` → 旧カートの `anonymous_token` を NULL にし、同じトークンで
  新 `active` カートを作る（同時 GET で UNIQUE 違反したらロック読みで再 SELECT）

数量の上限（10／50）は加算後に検査し、超過なら ROLLBACK して 422（DS-PRC-011）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, internal_error
from app.models import Cart, CartStatus
from app.repositories import carts as carts_repo
from app.schemas.cart import CartLineOut, CartResponse
from app.services import cart_rules
from app.services.pricing import calc_totals
from app.services.settings import get_public_settings


async def resolve_cart(session: AsyncSession, token: str | None) -> Cart:
    """トークンから active カートを得る。無ければ作る（呼び手が commit する）。"""
    token = cart_rules.normalize_token(token)
    reuse_token = False
    if token is not None:
        cart = await carts_repo.get_by_token(session, token)
        if cart is not None and cart.status == CartStatus.active:
            return cart
        if cart is not None:
            # ordered／merged: トークンを外して同じトークンで新カートを作る
            await carts_repo.detach_token(session, cart.id)
            reuse_token = True

    new_token = token if (reuse_token and token is not None) else cart_rules.new_cart_token()
    created = await carts_repo.create_active(session, new_token)
    if created is not None:
        return created
    # 同時 GET で先に作られた（UNIQUE 違反）→ ロック読みで最新を取り直す
    existing = await carts_repo.get_by_token(session, new_token, for_update=True)
    if existing is None or existing.status != CartStatus.active:
        raise internal_error()
    return existing


async def build_cart_response(session: AsyncSession, cart: Cart) -> CartResponse:
    """明細と金額を組み立てる。空カートは金額 0（pricing の empty_cart は呼ばない）。"""
    settings = await get_public_settings(session)
    rows = await carts_repo.fetch_lines(session, cart.id)
    items: list[CartLineOut] = []
    for r in rows:
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
                stock_status=cart_rules.stock_status(
                    stock=r.stock, quantity=r.quantity, published=r.published
                ),
                image_path=r.image_path,
            )
        )
    if items:
        totals = calc_totals([(r.unit_price, r.quantity) for r in rows], settings)
        subtotal, shipping_fee, total = totals.subtotal, totals.shipping_fee, totals.total
    else:
        subtotal = shipping_fee = total = 0
    assert cart.anonymous_token is not None
    return CartResponse(
        cart_token=cart.anonymous_token,
        items=items,
        item_count=sum(i.quantity for i in items),
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=total,
        free_shipping_threshold=settings.free_shipping_threshold,
        can_checkout=bool(items) and all(i.stock_status == "ok" for i in items),
    )


async def get_cart(session: AsyncSession, token: str | None) -> CartResponse:
    cart = await resolve_cart(session, token)
    await session.commit()
    return await build_cart_response(session, cart)


async def add_item(
    session: AsyncSession, token: str | None, *, variant_id: int, quantity: int
) -> CartResponse:
    """明細追加。404（非公開・不存在）→ 409（在庫 0）→ 加算 → 上限 422 の順。"""
    cart = await resolve_cart(session, token)
    variant = await carts_repo.get_variant_of_published_product(session, variant_id)
    if variant is None:
        await session.rollback()
        raise AppError(404, "not_found")
    if variant.stock <= 0:
        await session.rollback()
        raise AppError(409, "out_of_stock", items=[variant_id])

    await carts_repo.upsert_item_add(session, cart.id, variant_id, quantity)
    line_quantity = await carts_repo.get_line_quantity(session, cart.id, variant_id)
    total_quantity = await carts_repo.get_total_quantity(session, cart.id)
    try:
        cart_rules.check_limits(line_quantity=line_quantity, cart_total_quantity=total_quantity)
    except AppError:
        await session.rollback()  # 加算を戻す
        raise
    await session.commit()
    return await build_cart_response(session, cart)


async def update_item(
    session: AsyncSession, token: str | None, *, item_id: int, quantity: int
) -> CartResponse:
    cart = await resolve_cart(session, token)
    item = await carts_repo.get_item(session, cart.id, item_id)
    if item is None:
        await session.rollback()
        raise AppError(404, "not_found")
    others = await carts_repo.get_total_quantity(session, cart.id) - item.quantity
    try:
        cart_rules.check_limits(line_quantity=quantity, cart_total_quantity=others + quantity)
    except AppError:
        await session.rollback()
        raise
    await carts_repo.set_item_quantity(session, item.id, quantity)
    await session.commit()
    return await build_cart_response(session, cart)


async def remove_item(session: AsyncSession, token: str | None, *, item_id: int) -> CartResponse:
    cart = await resolve_cart(session, token)
    item = await carts_repo.get_item(session, cart.id, item_id)
    if item is None:
        await session.rollback()
        raise AppError(404, "not_found")
    await carts_repo.delete_item(session, item.id)
    await session.commit()
    return await build_cart_response(session, cart)
