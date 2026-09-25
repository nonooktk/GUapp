"""商品検索の読み出し（DS-API-004・004a）。

一致判定は商品名・説明・カテゴリ名の部分一致（OR、DS-DEC-33）。公開商品のみ（B7・`published_filter`）。
LIKE のワイルドカード（`%`・`_`）は `.contains(..., autoescape=True)` /
`.startswith(..., autoescape=True)` に任せ、自前のエスケープは書かない（DS-DEC-35）。
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Product, ProductCategory
from app.repositories.products import (
    ProductSummary,
    published_filter,
    rows_to_summaries,
    summary_select,
)


def build_match_condition(term: str) -> ColumnElement[bool]:
    """DS-PRC-004 手順3。商品名・説明・カテゴリ名のいずれかに部分一致する条件。

    カテゴリ名の一致は `product_categories` 経由のサブクエリ（`IN`）で表す。
    """
    category_match = (
        select(ProductCategory.product_id)
        .join(Category, Category.id == ProductCategory.category_id)
        .where(Category.name.contains(term, autoescape=True))
    )
    return (
        Product.name.contains(term, autoescape=True)
        | Product.description.contains(term, autoescape=True)
        | Product.id.in_(category_match)
    )


async def search_published(
    session: AsyncSession, *, term: str, page: int, per_page: int
) -> tuple[list[ProductSummary], int]:
    """DS-PRC-004 手順3〜4。公開商品のうち一致するものを新着順でページングし、総件数も返す。"""
    condition = build_match_condition(term)

    count_stmt = (
        select(func.count(func.distinct(Product.id)))
        .select_from(Product)
        .where(published_filter(), condition)
    )
    total = int((await session.execute(count_stmt)).scalar_one())

    # 4.4 手順3 は「DISTINCT で取得する」とあるが、カテゴリ一致を JOIN ではなく
    # `Product.id.in_(...)` サブクエリで判定しているため行の重複自体が起こらない。
    # MySQL は `SELECT DISTINCT ... ORDER BY <SELECT に無い列>` を許さない
    # （エラー 3065）ため、実装は DISTINCT を付けず一意性を集合演算側で担保する
    # （設計と実装の差分。完了報告で申し送る）。
    stmt = summary_select().where(condition).offset((page - 1) * per_page).limit(per_page)
    rows = (await session.execute(stmt)).all()
    return rows_to_summaries(rows), total


async def count_matches(session: AsyncSession, term: str) -> int:
    """類似キーワード候補（DS-PRC-004 手順5.1）が実際に何件ヒットするか。"""
    condition = build_match_condition(term)
    stmt = (
        select(func.count(func.distinct(Product.id)))
        .select_from(Product)
        .where(published_filter(), condition)
    )
    return int((await session.execute(stmt)).scalar_one())


async def suggest_names(session: AsyncSession, *, term: str, limit: int) -> list[tuple[int, str]]:
    """DS-PRC-004a。商品名の前方一致を優先し、`limit` 未満なら部分一致で補充する（重複除去）。"""
    prefix_stmt = (
        select(Product.id, Product.name)
        .where(published_filter(), Product.name.startswith(term, autoescape=True))
        .order_by(Product.id.asc())
        .limit(limit)
    )
    prefix_rows = (await session.execute(prefix_stmt)).all()
    out: list[tuple[int, str]] = [(r.id, r.name) for r in prefix_rows]
    remaining = limit - len(out)
    if remaining <= 0:
        return out

    exclude_ids = [r.id for r in prefix_rows]
    contains_stmt = select(Product.id, Product.name).where(
        published_filter(), Product.name.contains(term, autoescape=True)
    )
    if exclude_ids:
        contains_stmt = contains_stmt.where(Product.id.notin_(exclude_ids))
    contains_stmt = contains_stmt.order_by(Product.id.asc()).limit(remaining)
    contains_rows = (await session.execute(contains_stmt)).all()
    out.extend((r.id, r.name) for r in contains_rows)
    return out
