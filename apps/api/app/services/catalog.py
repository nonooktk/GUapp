"""カタログ（DS-API-001〜003）のサービス。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Gender
from app.repositories import products as products_repo
from app.schemas.catalog import (
    CategoriesResponse,
    CategoryChildOut,
    CategoryOut,
    ProductDetailOut,
    ProductListItemOut,
    ProductListResponse,
    RelatedProductOut,
    VariantOut,
)

RELATED_LIMIT = 4


async def get_categories(session: AsyncSession) -> CategoriesResponse:
    """親（parent_id NULL）→ 子の階層。`product_count` は公開商品のみ。"""
    rows = await products_repo.list_categories_with_counts(session)
    parents = [r for r in rows if r.parent_id is None]
    children_by_parent: dict[int, list[CategoryChildOut]] = {}
    for r in rows:
        if r.parent_id is not None:
            children_by_parent.setdefault(r.parent_id, []).append(
                CategoryChildOut(slug=r.slug, name=r.name, product_count=r.product_count)
            )
    return CategoriesResponse(
        categories=[
            CategoryOut(
                slug=p.slug,
                name=p.name,
                gender=p.gender.value,
                children=children_by_parent.get(p.id, []),
            )
            for p in parents
        ]
    )


async def list_products(
    session: AsyncSession,
    *,
    gender: Gender | None,
    category_slug: str | None,
    page: int,
    per_page: int,
) -> ProductListResponse:
    summaries, total = await products_repo.list_published(
        session, gender=gender, category_slug=category_slug, page=page, per_page=per_page
    )
    colors = await products_repo.colors_by_product(session, [s.id for s in summaries])
    items = [
        ProductListItemOut(
            id=s.id,
            name=s.name,
            price_incl_tax=s.price_incl_tax,
            image_path=s.image_path,
            colors=colors.get(s.id, []),
            sold_out=s.sold_out,
        )
        for s in summaries
    ]
    return ProductListResponse(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=page * per_page < total,
    )


def _unique_in_order(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


async def get_product_detail(session: AsyncSession, product_id: int) -> ProductDetailOut:
    """非公開・不存在は 404 `not_found`（区別しない）。"""
    product = await products_repo.get_published(session, product_id)
    if product is None:
        raise AppError(404, "not_found")
    variants = await products_repo.list_variants(session, product_id)
    images = await products_repo.list_image_paths(session, product_id)
    related = await products_repo.list_related(session, product_id, limit=RELATED_LIMIT)
    return ProductDetailOut(
        id=product.id,
        name=product.name,
        description=product.description,
        material=product.material,
        price_incl_tax=product.price_incl_tax,
        images=images,
        colors=_unique_in_order([v.color for v in variants]),
        sizes=_unique_in_order([v.size for v in variants]),
        variants=[
            VariantOut(variant_id=v.id, color=v.color, size=v.size, in_stock=v.stock > 0)
            for v in variants
        ],
        related=[
            RelatedProductOut(
                id=r.id,
                name=r.name,
                price_incl_tax=r.price_incl_tax,
                image_path=r.image_path,
                sold_out=r.sold_out,
            )
            for r in related
        ],
    )
