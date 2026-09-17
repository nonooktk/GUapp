"""DS-API-001〜003 カテゴリ・商品。ルーターは入出力のみ（業務判定はサービス層）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Gender
from app.schemas.catalog import (
    PER_PAGE_DEFAULT,
    PER_PAGE_MAX,
    CategoriesResponse,
    ProductDetailOut,
    ProductListResponse,
)
from app.services import catalog as catalog_service

router = APIRouter(tags=["catalog"])


@router.get("/categories", response_model=CategoriesResponse, summary="DS-API-001 カテゴリ階層")
async def get_categories(session: AsyncSession = Depends(get_session)) -> CategoriesResponse:
    return await catalog_service.get_categories(session)


@router.get("/products", response_model=ProductListResponse, summary="DS-API-002 商品一覧")
async def list_products(
    gender: Annotated[Gender | None, Query(description="women / men / kids_teen / all")] = None,
    category: Annotated[str | None, Query(max_length=100, description="カテゴリ slug")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=PER_PAGE_MAX)] = PER_PAGE_DEFAULT,
    session: AsyncSession = Depends(get_session),
) -> ProductListResponse:
    return await catalog_service.list_products(
        session, gender=gender, category_slug=category, page=page, per_page=per_page
    )


@router.get(
    "/products/{product_id}", response_model=ProductDetailOut, summary="DS-API-003 商品詳細"
)
async def get_product(
    product_id: int, session: AsyncSession = Depends(get_session)
) -> ProductDetailOut:
    return await catalog_service.get_product_detail(session, product_id)
