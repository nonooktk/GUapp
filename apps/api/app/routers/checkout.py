"""DS-API-021 確認画面用の金額計算・冪等キー発行。カートは `X-Cart-Token`。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.routers.cart import CartToken
from app.schemas.order import PrepareOut
from app.services import checkout as checkout_service

router = APIRouter(prefix="/checkout", tags=["checkout"])


@router.post("/prepare", response_model=PrepareOut, summary="DS-API-021 金額計算・冪等キー発行")
async def prepare(
    x_cart_token: CartToken = None, session: AsyncSession = Depends(get_session)
) -> PrepareOut:
    return await checkout_service.prepare(session, x_cart_token)
