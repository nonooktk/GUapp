"""管理：商品・在庫の読み書き（DS-PRC-051・051b・051c。設計仕様書 P2 追補c 4.6）。

担当レーン: C-2。公開側の `repositories/products.py` とは別物で、非公開の商品も扱う。
更新系は `SELECT … FOR UPDATE` で 1 行だけ読む（`get_*_for_update`）。呼び出し側のサービスが
同じトランザクションで照合・更新・監査ログの INSERT・COMMIT を行う。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, Select, and_, case, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, RestockNotification, Variant

Visibility = Literal["all", "public", "private"]
StockFilter = Literal["all", "out"]


@dataclass(frozen=True)
class ProductListRow:
    product_id: int
    name: str
    price_incl_tax: int
    published: bool
    variant_count: int
    total_stock: int
    out_of_stock_variants: int


@dataclass(frozen=True)
class VariantRow:
    variant_id: int
    sku: str
    color: str
    size: str
    stock: int
    restock_waiting: int


@dataclass(frozen=True)
class ProductDetailRow:
    product_id: int
    name: str
    price_incl_tax: int
    published: bool
    updated_at: datetime


@dataclass(frozen=True)
class ProductLocked:
    """`FOR UPDATE` で読んだ商品の行（値のコピー）。"""

    product_id: int
    published: bool
    price_incl_tax: int
    updated_at: datetime


@dataclass(frozen=True)
class VariantLocked:
    """`FOR UPDATE` で読んだバリエーションの行（値のコピー）。"""

    variant_id: int
    sku: str
    stock: int


def _variant_summary_subquery():
    """商品ごとの集計（variants を 1 回の GROUP BY で数える。N+1 にしない）。"""
    return (
        select(
            Variant.product_id.label("product_id"),
            func.count().label("variant_count"),
            func.coalesce(func.sum(Variant.stock), 0).label("total_stock"),
            func.sum(case((Variant.stock == 0, 1), else_=0)).label("out_of_stock_variants"),
        )
        .group_by(Variant.product_id)
        .subquery()
    )


def build_search_statements(
    *,
    q: str,
    visibility: Visibility,
    stock: StockFilter,
    limit: int,
    offset: int,
) -> tuple[Select[tuple], Select[tuple[int]]]:
    """DS-PRC-051 の本体と件数の SELECT を組み立てる（DB に触れない。UT-ADM-11 が検査する）。

    `q` は商品名の部分一致、または SKU の前方一致（英字は大文字に直す）。LIKE のワイルドカード
    （`%`・`_`）と `\\` は `autoescape` で文字として扱う。SQL を文字列連結で作らない。
    """
    agg = _variant_summary_subquery()
    out_count = func.coalesce(agg.c.out_of_stock_variants, 0)

    conditions: list[ColumnElement[bool]] = []
    if visibility == "public":
        conditions.append(Product.published.is_(True))
    elif visibility == "private":
        conditions.append(Product.published.is_(False))
    if stock == "out":
        conditions.append(out_count >= 1)
    if q:
        sku_match = exists().where(
            and_(
                Variant.product_id == Product.id,
                Variant.sku.startswith(q.upper(), autoescape=True),
            )
        )
        conditions.append(or_(Product.name.contains(q, autoescape=True), sku_match))

    body = (
        select(
            Product.id,
            Product.name,
            Product.price_incl_tax,
            Product.published,
            func.coalesce(agg.c.variant_count, 0),
            func.coalesce(agg.c.total_stock, 0),
            out_count,
        )
        .outerjoin(agg, agg.c.product_id == Product.id)
        .where(*conditions)
        .order_by(Product.id)
        .limit(limit)
        .offset(offset)
    )
    count = (
        select(func.count())
        .select_from(Product)
        .outerjoin(agg, agg.c.product_id == Product.id)
        .where(*conditions)
    )
    return body, count


async def search_products(
    session: AsyncSession,
    *,
    q: str,
    visibility: Visibility,
    stock: StockFilter,
    limit: int,
    offset: int,
) -> tuple[list[ProductListRow], int]:
    """DS-PRC-051。本体 1 回と件数 1 回の合計 2 クエリ。並びは `products.id` の昇順。"""
    body, count = build_search_statements(
        q=q, visibility=visibility, stock=stock, limit=limit, offset=offset
    )
    rows = (await session.execute(body)).all()
    total = int((await session.execute(count)).scalar_one())
    items = [
        ProductListRow(
            product_id=int(r[0]),
            name=r[1],
            price_incl_tax=int(r[2]),
            published=bool(r[3]),
            variant_count=int(r[4]),
            total_stock=int(r[5]),
            out_of_stock_variants=int(r[6]),
        )
        for r in rows
    ]
    return items, total


async def get_product_detail(session: AsyncSession, product_id: int) -> ProductDetailRow | None:
    """商品 1 件（非公開でも返す）。無ければ None。"""
    row = (
        await session.execute(
            select(
                Product.id,
                Product.name,
                Product.price_incl_tax,
                Product.published,
                Product.updated_at,
            ).where(Product.id == product_id)
        )
    ).first()
    if row is None:
        return None
    return ProductDetailRow(
        product_id=int(row[0]),
        name=row[1],
        price_incl_tax=int(row[2]),
        published=bool(row[3]),
        updated_at=row[4],
    )


async def list_variants(session: AsyncSession, product_id: int) -> list[VariantRow]:
    """`variant_id` の昇順。`restock_waiting` は未通知の申込の件数だけ（メールは読まない）。"""
    waiting = (
        select(
            RestockNotification.variant_id.label("variant_id"),
            func.count().label("n"),
        )
        .where(RestockNotification.notified_at.is_(None))
        .group_by(RestockNotification.variant_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Variant.id,
                Variant.sku,
                Variant.color,
                Variant.size,
                Variant.stock,
                func.coalesce(waiting.c.n, 0),
            )
            .outerjoin(waiting, waiting.c.variant_id == Variant.id)
            .where(Variant.product_id == product_id)
            .order_by(Variant.id)
        )
    ).all()
    return [
        VariantRow(
            variant_id=int(r[0]),
            sku=r[1],
            color=r[2],
            size=r[3],
            stock=int(r[4]),
            restock_waiting=int(r[5]),
        )
        for r in rows
    ]


# ── 更新系（FOR UPDATE）────────────────────────────────────────────────────────


async def get_product_for_update(session: AsyncSession, product_id: int) -> ProductLocked | None:
    row = (
        await session.execute(
            select(Product.id, Product.published, Product.price_incl_tax, Product.updated_at)
            .where(Product.id == product_id)
            .with_for_update()
        )
    ).first()
    if row is None:
        return None
    return ProductLocked(
        product_id=int(row[0]),
        published=bool(row[1]),
        price_incl_tax=int(row[2]),
        updated_at=row[3],
    )


async def update_product(
    session: AsyncSession,
    product_id: int,
    *,
    published: bool | None,
    price_incl_tax: int | None,
) -> datetime:
    """変更する項目だけ UPDATE し、DB が更新した `updated_at` を返す（同じトランザクション）。"""
    values: dict[str, object] = {}
    if published is not None:
        values["published"] = published
    if price_incl_tax is not None:
        values["price_incl_tax"] = price_incl_tax
    await session.execute(update(Product).where(Product.id == product_id).values(**values))
    return (
        await session.execute(select(Product.updated_at).where(Product.id == product_id))
    ).scalar_one()


async def get_variant_for_update(session: AsyncSession, variant_id: int) -> VariantLocked | None:
    row = (
        await session.execute(
            select(Variant.id, Variant.sku, Variant.stock)
            .where(Variant.id == variant_id)
            .with_for_update()
        )
    ).first()
    if row is None:
        return None
    return VariantLocked(variant_id=int(row[0]), sku=row[1], stock=int(row[2]))


async def set_variant_stock(session: AsyncSession, variant_id: int, stock: int) -> None:
    """絶対値の SET（差分ではない）。"""
    await session.execute(update(Variant).where(Variant.id == variant_id).values(stock=stock))


async def count_pending_restock(session: AsyncSession, variant_id: int) -> int:
    """未通知の再入荷申込の件数（`restock_waiting`）。"""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(RestockNotification)
                .where(
                    RestockNotification.variant_id == variant_id,
                    RestockNotification.notified_at.is_(None),
                )
            )
        ).scalar_one()
    )
