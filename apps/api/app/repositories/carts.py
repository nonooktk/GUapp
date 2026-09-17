"""カートの読み書き（DS-TBL-12・13、DS-API-010〜013）。

- 同じ variant の加算は `INSERT … ON DUPLICATE KEY UPDATE quantity = quantity + :n` の 1 文
  （MySQL 方言。IT-011-01）
- 加算後の読み直しはロック読み（FOR UPDATE）で最新値を見る
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Cart, CartItem, CartStatus, Product, ProductImage, Variant
from app.repositories.products import published_filter


async def get_by_token(
    session: AsyncSession, token: str, *, for_update: bool = False
) -> Cart | None:
    stmt = select(Cart).where(Cart.anonymous_token == token)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def detach_token(session: AsyncSession, cart_id: int) -> None:
    """注文済みカートからトークンを外す（UNIQUE を空けて同じトークンで新カートを作るため）。"""
    await session.execute(update(Cart).where(Cart.id == cart_id).values(anonymous_token=None))


async def create_active(session: AsyncSession, token: str) -> Cart | None:
    """トークン付きの active カートを作る。UNIQUE 違反（同時 GET）なら None を返す。"""
    try:
        async with session.begin_nested():
            cart = Cart(anonymous_token=token, status=CartStatus.active)
            session.add(cart)
            await session.flush()
    except IntegrityError:
        return None
    return cart


@dataclass(frozen=True)
class VariantForCart:
    variant_id: int
    product_id: int
    stock: int


async def get_variant_of_published_product(
    session: AsyncSession, variant_id: int
) -> VariantForCart | None:
    """公開商品のバリエーションだけを返す（非公開・不存在は None → 404）。"""
    row = (
        await session.execute(
            select(Variant.id, Variant.product_id, Variant.stock)
            .join(Product, Product.id == Variant.product_id)
            .where(Variant.id == variant_id)
            .where(published_filter())
        )
    ).one_or_none()
    if row is None:
        return None
    return VariantForCart(variant_id=row.id, product_id=row.product_id, stock=row.stock)


async def upsert_item_add(
    session: AsyncSession, cart_id: int, variant_id: int, quantity: int
) -> None:
    """明細を追加。既にあれば数量を加算する（1 文）。"""
    stmt = mysql_insert(CartItem).values(cart_id=cart_id, variant_id=variant_id, quantity=quantity)
    stmt = stmt.on_duplicate_key_update(quantity=CartItem.quantity + quantity)
    await session.execute(stmt)


async def get_line_quantity(session: AsyncSession, cart_id: int, variant_id: int) -> int:
    """加算後の明細数量（ロック読み）。"""
    return int(
        (
            await session.execute(
                select(CartItem.quantity)
                .where(CartItem.cart_id == cart_id, CartItem.variant_id == variant_id)
                .with_for_update()
            )
        ).scalar_one()
    )


async def get_total_quantity(session: AsyncSession, cart_id: int) -> int:
    """カート内の数量合計（ロック読み）。"""
    return int(
        (
            await session.execute(
                select(func.coalesce(func.sum(CartItem.quantity), 0))
                .where(CartItem.cart_id == cart_id)
                .with_for_update()
            )
        ).scalar_one()
    )


async def get_item(session: AsyncSession, cart_id: int, item_id: int) -> CartItem | None:
    """自分のカートの明細だけを返す（他人・不存在は None → 404）。"""
    return (
        await session.execute(
            select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart_id)
        )
    ).scalar_one_or_none()


async def set_item_quantity(session: AsyncSession, item_id: int, quantity: int) -> None:
    await session.execute(update(CartItem).where(CartItem.id == item_id).values(quantity=quantity))


async def delete_item(session: AsyncSession, item_id: int) -> None:
    await session.execute(delete(CartItem).where(CartItem.id == item_id))


@dataclass(frozen=True)
class CartLineRow:
    item_id: int
    variant_id: int
    product_id: int
    product_name: str
    color: str
    size: str
    unit_price: int
    quantity: int
    stock: int
    published: bool
    image_path: str | None


async def fetch_lines(session: AsyncSession, cart_id: int) -> list[CartLineRow]:
    """カート明細＋商品情報を 1 クエリで取る（明細 id 順）。"""
    first_image = (
        select(ProductImage.path)
        .where(ProductImage.product_id == Product.id)
        .order_by(ProductImage.sort_order, ProductImage.id)
        .limit(1)
        .scalar_subquery()
    )
    stmt = (
        select(
            CartItem.id.label("item_id"),
            CartItem.variant_id,
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Variant.color,
            Variant.size,
            Product.price_incl_tax.label("unit_price"),
            CartItem.quantity,
            Variant.stock,
            Product.published,
            first_image.label("image_path"),
        )
        .join(Variant, Variant.id == CartItem.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(CartItem.cart_id == cart_id)
        .order_by(CartItem.id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        CartLineRow(
            item_id=r.item_id,
            variant_id=r.variant_id,
            product_id=r.product_id,
            product_name=r.product_name,
            color=r.color,
            size=r.size,
            unit_price=r.unit_price,
            quantity=r.quantity,
            stock=r.stock,
            published=bool(r.published),
            image_path=r.image_path,
        )
        for r in rows
    ]
