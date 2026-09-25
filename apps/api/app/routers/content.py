"""DS-API-005・006 コンテンツ一覧・詳細。ルーターは入出力のみ（業務判定はサービス層）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.content import (
    CONTENT_LIMIT_DEFAULT,
    CONTENT_LIMIT_MAX,
    ContentDetailOut,
    ContentListKindLiteral,
    ContentsResponse,
)
from app.services import content as content_service
from app.services.content import CONTENT_SLUG_PATTERN

router = APIRouter(tags=["content"])


@router.get("/contents", response_model=ContentsResponse, summary="DS-API-005 コンテンツ一覧")
async def list_contents(
    kind: Annotated[ContentListKindLiteral, Query(description="feature / news")],
    limit: Annotated[int, Query(ge=1, le=CONTENT_LIMIT_MAX)] = CONTENT_LIMIT_DEFAULT,
    session: AsyncSession = Depends(get_session),
) -> ContentsResponse:
    return await content_service.list_contents(session, kind=kind, limit=limit)


@router.get(
    "/contents/{slug}", response_model=ContentDetailOut, summary="DS-API-006 FAQ・静的ページ"
)
async def get_content(
    slug: Annotated[str, Path(pattern=CONTENT_SLUG_PATTERN.pattern)],
    session: AsyncSession = Depends(get_session),
) -> ContentDetailOut:
    return await content_service.get_content_detail(session, slug)
