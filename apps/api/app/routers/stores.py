"""受け取り店舗 API の骨格（DS-API-026。設計仕様書 P2 追補b 4.3・DS-DEC-79）。

担当レーン: ルーターの骨格は A、**中身は C**。BFF の窓口はなく、注文手続きのページが
Server Component で取得してフォームへ props で渡す。認証不要。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import not_implemented
from app.schemas.store import StoreListOut

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("", response_model=StoreListOut, summary="DS-API-026 受け取り店舗の一覧")
async def list_stores(session: AsyncSession = Depends(get_session)) -> StoreListOut:
    """担当レーン: C。設計書: 4.3 DS-API-026、5.2 DS-TBL-10。

    `pickup_enabled` が真の店舗を `sort_order`・`id` の順に返す。郵便番号・内部 ID は返さない。
    一覧が空でも 200。
    """
    raise not_implemented()
