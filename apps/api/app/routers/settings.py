"""DS-API-020 公開設定（税率・送料ルール）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.settings import PublicSettingsOut
from app.services.settings import get_public_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/public", response_model=PublicSettingsOut, summary="DS-API-020 公開設定")
async def public_settings(session: AsyncSession = Depends(get_session)) -> PublicSettingsOut:
    s = await get_public_settings(session)
    return PublicSettingsOut(
        tax_rate=s.tax_rate,
        shipping_fee=s.shipping_fee,
        free_shipping_threshold=s.free_shipping_threshold,
    )
