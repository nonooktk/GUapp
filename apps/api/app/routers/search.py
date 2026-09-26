"""DS-API-004 商品検索・DS-API-004a 検索サジェスト。

ルーターは入出力のみ（業務判定はサービス層）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.catalog import PER_PAGE_DEFAULT, PER_PAGE_MAX
from app.schemas.search import SearchResponse, SuggestResponse
from app.services import search as search_service
from app.services.search import SEARCH_MAX_LENGTH, SEARCH_MIN_LENGTH

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse, summary="DS-API-004 商品検索")
async def search(
    q: Annotated[str, Query(min_length=SEARCH_MIN_LENGTH, max_length=SEARCH_MAX_LENGTH)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=PER_PAGE_MAX)] = PER_PAGE_DEFAULT,
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    return await search_service.search_products(session, q=q, page=page, per_page=per_page)


@router.get("/search/suggest", response_model=SuggestResponse, summary="DS-API-004a 検索サジェスト")
async def suggest(
    q: Annotated[str, Query(min_length=SEARCH_MIN_LENGTH, max_length=SEARCH_MAX_LENGTH)],
    session: AsyncSession = Depends(get_session),
) -> SuggestResponse:
    return await search_service.suggest_products(session, q=q)
