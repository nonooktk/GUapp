"""DS-API-010〜013 カート。カートの識別はヘッダ `X-Cart-Token`（URL・クエリには載せない）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.cart import CART_TOKEN_HEADER, CartItemIn, CartItemPatchIn, CartResponse
from app.services import cart as cart_service

router = APIRouter(prefix="/cart", tags=["cart"])

CartToken = Annotated[
    str | None,
    Header(
        alias=CART_TOKEN_HEADER,
        description="匿名カートトークン（BFF が Cookie から移す）。無ければ新規発行",
    ),
]


@router.get("", response_model=CartResponse, summary="DS-API-010 カート取得")
async def get_cart(
    x_cart_token: CartToken = None, session: AsyncSession = Depends(get_session)
) -> CartResponse:
    return await cart_service.get_cart(session, x_cart_token)


@router.post(
    "/items",
    response_model=CartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="DS-API-011 明細追加",
)
async def add_item(
    body: CartItemIn,
    x_cart_token: CartToken = None,
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    return await cart_service.add_item(
        session, x_cart_token, variant_id=body.variant_id, quantity=body.quantity
    )


@router.patch("/items/{item_id}", response_model=CartResponse, summary="DS-API-012 数量変更")
async def update_item(
    item_id: int,
    body: CartItemPatchIn,
    x_cart_token: CartToken = None,
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    return await cart_service.update_item(
        session, x_cart_token, item_id=item_id, quantity=body.quantity
    )


@router.delete("/items/{item_id}", response_model=CartResponse, summary="DS-API-013 明細削除")
async def remove_item(
    item_id: int,
    x_cart_token: CartToken = None,
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    return await cart_service.remove_item(session, x_cart_token, item_id=item_id)
