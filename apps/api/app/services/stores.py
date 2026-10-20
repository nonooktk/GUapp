"""受け取り店舗の一覧（DS-API-026。設計仕様書 P2 追補b 4.3）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import stores as stores_repo
from app.schemas.store import StoreListOut, StoreOut


async def list_pickup_stores(session: AsyncSession) -> StoreListOut:
    """郵便番号・内部 ID は返さない。一覧が空でも 200。"""
    stores = await stores_repo.list_pickup_enabled(session)
    return StoreListOut(
        items=[
            StoreOut(code=s.code, name=s.name, prefecture=s.prefecture, address=s.address)
            for s in stores
        ]
    )
