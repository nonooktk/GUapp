"""商品・カテゴリの読み出し（DS-API-001〜003）。

公開商品の条件は `published_filter()` の 1 か所（B7）。一覧・詳細・関連・カート追加は
必ずこれを通す。`sold_out` は variants を 1 回の GROUP BY で集計する（N+1 禁止）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Gender, Product, ProductCategory, ProductImage, Variant


def published_filter() -> ColumnElement[bool]:
    """公開商品の条件。全経路がここを通る。"""
    return Product.published.is_(True)


def published_products() -> Select[tuple[Product]]:
    return select(Product).where(published_filter())


def published_product_ids() -> Select[tuple[int]]:
    return select(Product.id).where(published_filter())


# ── 一覧・関連商品に共通の付帯情報 ──


def _first_image_path_subquery():
    """商品ごとの先頭画像（sort_order → id の順）。相関スカラーサブクエリ。"""
    return (
        select(ProductImage.path)
        .where(ProductImage.product_id == Product.id)
        .order_by(ProductImage.sort_order, ProductImage.id)
        .limit(1)
        .scalar_subquery()
    )


def _stock_summary_subquery():
    """商品ごとの在庫合計（variants を 1 回の GROUP BY で集計）。"""
    return (
        select(
            Variant.product_id.label("product_id"),
            func.coalesce(func.sum(Variant.stock), 0).label("total_stock"),
        )
        .group_by(Variant.product_id)
        .subquery()
    )


@dataclass(frozen=True)
class ProductSummary:
    """一覧・関連商品の 1 行。"""

    id: int
    name: str
    price_incl_tax: int
    image_path: str | None
    sold_out: bool


def _summary_select() -> Select:
    stock = _stock_summary_subquery()
    sold_out = case(
        (func.coalesce(stock.c.total_stock, 0) <= 0, True),
        else_=False,
    )
    return (
        select(
            Product.id,
            Product.name,
            Product.price_incl_tax,
            _first_image_path_subquery().label("image_path"),
            sold_out.label("sold_out"),
        )
        .select_from(Product)
        .outerjoin(stock, stock.c.product_id == Product.id)
        .where(published_filter())
        .order_by(Product.created_at.desc(), Product.id.desc())
    )


def _rows_to_summaries(rows) -> list[ProductSummary]:
    return [
        ProductSummary(
            id=row.id,
            name=row.name,
            price_incl_tax=row.price_incl_tax,
            image_path=row.image_path,
            sold_out=bool(row.sold_out),
        )
        for row in rows
    ]


def _category_scope(gender: Gender | None, category_slug: str | None) -> ColumnElement[bool] | None:
    """gender／category（slug）で商品を絞る条件。どちらも無ければ None。"""
    if gender is None and category_slug is None:
        return None
    scope = select(ProductCategory.product_id).join(
        Category, Category.id == ProductCategory.category_id
    )
    if gender is not None:
        scope = scope.where(Category.gender == gender)
    if category_slug is not None:
        scope = scope.where(Category.slug == category_slug)
    return Product.id.in_(scope)


async def list_published(
    session: AsyncSession,
    *,
    gender: Gender | None,
    category_slug: str | None,
    page: int,
    per_page: int,
) -> tuple[list[ProductSummary], int]:
    """公開商品の一覧（新着順）と総件数。"""
    scope = _category_scope(gender, category_slug)

    count_stmt = select(func.count()).select_from(Product).where(published_filter())
    if scope is not None:
        count_stmt = count_stmt.where(scope)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = _summary_select().offset((page - 1) * per_page).limit(per_page)
    if scope is not None:
        stmt = stmt.where(scope)
    rows = (await session.execute(stmt)).all()
    return _rows_to_summaries(rows), total


async def colors_by_product(session: AsyncSession, product_ids: list[int]) -> dict[int, list[str]]:
    """商品 ID → 色（重複なし・variants の id 順）。ページ分を 1 クエリで取る。"""
    if not product_ids:
        return {}
    rows = await session.execute(
        select(Variant.product_id, Variant.color)
        .where(Variant.product_id.in_(product_ids))
        .order_by(Variant.product_id, Variant.id)
    )
    out: dict[int, list[str]] = {}
    for product_id, color in rows.all():
        colors = out.setdefault(product_id, [])
        if color not in colors:
            colors.append(color)
    return out


async def get_published(session: AsyncSession, product_id: int) -> Product | None:
    return (
        await session.execute(published_products().where(Product.id == product_id))
    ).scalar_one_or_none()


async def list_variants(session: AsyncSession, product_id: int) -> list[Variant]:
    rows = await session.execute(
        select(Variant).where(Variant.product_id == product_id).order_by(Variant.id)
    )
    return list(rows.scalars().all())


async def list_image_paths(session: AsyncSession, product_id: int) -> list[str]:
    rows = await session.execute(
        select(ProductImage.path)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.sort_order, ProductImage.id)
    )
    return list(rows.scalars().all())


async def list_related(
    session: AsyncSession, product_id: int, *, limit: int
) -> list[ProductSummary]:
    """同じカテゴリの公開商品から自分以外を新着順で `limit` 件。"""
    own_categories = select(ProductCategory.category_id).where(
        ProductCategory.product_id == product_id
    )
    same_category = select(ProductCategory.product_id).where(
        ProductCategory.category_id.in_(own_categories)
    )
    stmt = (
        _summary_select()
        .where(Product.id.in_(same_category))
        .where(Product.id != product_id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return _rows_to_summaries(rows)


# ── カテゴリ ──


@dataclass(frozen=True)
class CategoryRow:
    id: int
    slug: str
    name: str
    gender: Gender
    parent_id: int | None
    sort_order: int
    product_count: int


async def list_categories_with_counts(session: AsyncSession) -> list[CategoryRow]:
    """全カテゴリと公開商品数（親→子、sort_order 順）。件数は公開商品のみ。"""
    counts = (
        select(
            ProductCategory.category_id.label("category_id"),
            func.count(func.distinct(ProductCategory.product_id)).label("product_count"),
        )
        .where(ProductCategory.product_id.in_(published_product_ids()))
        .group_by(ProductCategory.category_id)
        .subquery()
    )
    stmt = (
        select(
            Category.id,
            Category.slug,
            Category.name,
            Category.gender,
            Category.parent_id,
            Category.sort_order,
            func.coalesce(counts.c.product_count, 0).label("product_count"),
        )
        .outerjoin(counts, counts.c.category_id == Category.id)
        .order_by(Category.parent_id.is_(None).desc(), Category.sort_order, Category.id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        CategoryRow(
            id=r.id,
            slug=r.slug,
            name=r.name,
            gender=Gender(r.gender),
            parent_id=r.parent_id,
            sort_order=r.sort_order,
            product_count=int(r.product_count),
        )
        for r in rows
    ]
