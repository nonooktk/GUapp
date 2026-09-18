"""DS-API-022 注文確定・DS-API-023 ゲスト注文照会。ルーターは入出力のみ。

- 確定は新規 201／同じカートの既存注文 200 なので `Response.status_code` で切り替える
- 照会はメールを本文で受け（URL に個人情報を載せない）、IP ごとのレート制限を依存関数で掛ける
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.mail import MailAdapter, get_mail_adapter
from app.adapters.payment import PaymentAdapter, get_payment_adapter
from app.core.db import get_session
from app.core.rate_limit import lookup_rate_limit
from app.routers.cart import CartToken
from app.schemas.order import LookupIn, OrderCreateIn, OrderOut
from app.services import orders as orders_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post(
    "",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": OrderOut, "description": "同じ冪等キーの既存注文"}},
    summary="DS-API-022 注文確定（DS-PRC-014-1）",
)
async def create_order(
    body: OrderCreateIn,
    response: Response,
    x_cart_token: CartToken = None,
    session: AsyncSession = Depends(get_session),
    payment: PaymentAdapter = Depends(get_payment_adapter),
    mail: MailAdapter = Depends(get_mail_adapter),
) -> OrderOut:
    http_status, order = await orders_service.create_order(
        session, x_cart_token, body, payment=payment, mail=mail
    )
    response.status_code = http_status
    return order


@router.post(
    "/{order_number}/lookup",
    response_model=OrderOut,
    dependencies=[Depends(lookup_rate_limit)],
    summary="DS-API-023 ゲスト注文照会（番号＋メール一致・100 回/時/IP）",
)
async def lookup_order(
    order_number: str, body: LookupIn, session: AsyncSession = Depends(get_session)
) -> OrderOut:
    return await orders_service.lookup_order(session, order_number, str(body.guest_email))
