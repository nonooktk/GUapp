"""管理：注文 API（DS-API-053・053a・053b。設計仕様書 P2 追補c 4.4）。

担当レーン: C-3。認証は `routers/admin/__init__.py` がルーター単位で掛けている（既定拒否）。
管理者を使うルート（詳細・状態の更新。監査ログに残す）だけが `Depends(require_staff)` で受ける。

注文は注文番号（`^GU-[0-9]{6}-[A-HJ-NP-Z2-9]{8}$`）で指し、内部 ID を宛先にしない。
注文状態の更新は `expected_*` を使わず、遷移表で判定する（DS-DEC-113）。
判定の順序は 認証 → 400 → 404 → 422 → 409（DS-DEC-124）。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_session import CurrentStaff, require_staff
from app.core.db import get_session
from app.models import OrderStatus, ReceiveMethod
from app.schemas.admin_common import Page, PageParams, page_params
from app.schemas.admin_orders import (
    AdminOrderDetailOut,
    AdminOrderListItemOut,
    OrderStatusUpdateIn,
    OrderStatusUpdateOut,
)
from app.services import admin_orders as service
from app.services.email_normalize import InvalidEmail, normalize_email
from app.services.order_history import is_order_number_shape

router = APIRouter(tags=["admin-orders"])

_REASON_TYPES = {"required": "missing", "too_long": "string_too_long", "format": "value_error"}

StatusQuery = Literal[
    "all",
    "pending_payment",
    "accepted",
    "preparing",
    "shipped",
    "delivered",
    "pickup_expired",
    "cancelled",
    "payment_failed",
]
ReceiveMethodQuery = Literal["all", "delivery", "store"]


def _invalid(name: str, value: Any, reason: str = "format") -> RequestValidationError:
    """入力の形の違反（400 `validation_error`）。`name` は `fields[].name` に出る。"""
    return RequestValidationError(
        [
            {
                "type": _REASON_TYPES[reason],
                "loc": ("query", name),
                "msg": f"{name}: {reason}",
                "input": value,
            }
        ]
    )


def _parse_date(name: str, raw: str | None) -> date | None:
    """`YYYY-MM-DD`（ASCII 数字・実在する日付。正規化はしない）。空文字・None は条件なし。"""
    if not raw:
        return None
    try:
        return service.parse_ymd(raw)
    except ValueError:
        raise _invalid(name, raw) from None


def order_search_params(
    status: StatusQuery = Query(default="all"),
    receive_method: ReceiveMethodQuery = Query(default="all"),
    date_from: str | None = Query(default=None, alias="from", max_length=64),
    date_to: str | None = Query(default=None, alias="to", max_length=64),
    order_number: str | None = Query(default=None, max_length=64),
    email: str | None = Query(default=None, max_length=1024),
) -> service.OrderSearchParams:
    """検索条件の形の検査と正規化（DS-API-053 の「要求」。違反は 400）。

    - `order_number`: 前後空白除去・大文字化のあと `^GU-[0-9]{6}-[A-HJ-NP-Z2-9]{8}$`
    - `email`: 追補b の DS-API-030 と同じ正規化（NFKC・前後空白除去・小文字化）のあと 254 文字以内
    - 空文字は条件なし。組み合わせの検査（`from` が `to` より後・366 日超）は 422 でサービス層
    """
    number: str | None = None
    if order_number is not None and order_number.strip():
        number = order_number.strip().upper()
        if not is_order_number_shape(number):
            raise _invalid("order_number", order_number)
    normalized_email: str | None = None
    if email is not None and email.strip():
        try:
            normalized_email = normalize_email(email)
        except InvalidEmail as exc:
            raise _invalid("email", email, exc.reason) from None
    return service.OrderSearchParams(
        status=None if status == "all" else OrderStatus(status),
        receive_method=None if receive_method == "all" else ReceiveMethod(receive_method),
        date_from=_parse_date("from", date_from),
        date_to=_parse_date("to", date_to),
        order_number=number,
        email=normalized_email,
    )


@router.get(
    "/orders",
    response_model=Page[AdminOrderListItemOut],
    summary="DS-API-053 注文の検索",
)
async def search_orders(
    params: service.OrderSearchParams = Depends(order_search_params),
    paging: PageParams = Depends(page_params),
    session: AsyncSession = Depends(get_session),
) -> Page[AdminOrderListItemOut]:
    """設計書: 4.4 DS-API-053、4.6 DS-PRC-053。個人情報はマスクしたメールだけ。

    新しい順（同時刻は `id` の降順）。0 件でも 200。`from` が `to` より後は 422
    `unsupported_value`、期間が 366 日を超えると 422 `limit_exceeded`。
    """
    return await service.search_orders(session, params, paging)


@router.get(
    "/orders/{order_number}",
    response_model=AdminOrderDetailOut,
    summary="DS-API-053a 注文詳細",
)
async def get_order(
    order_number: str,
    staff: CurrentStaff = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> AdminOrderDetailOut:
    """設計書: 4.4 DS-API-053a。取得を `admin.order.view` に記録（できなければ 500）。

    形が違う・存在しない番号は同じ 404。受け取りコードは返さない。
    """
    return await service.get_order_detail(session, staff, order_number)


@router.patch(
    "/orders/{order_number}/status",
    response_model=OrderStatusUpdateOut,
    summary="DS-API-053b 注文状態の更新",
)
async def update_order_status(
    order_number: str,
    body: OrderStatusUpdateIn,
    staff: CurrentStaff = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> OrderStatusUpdateOut:
    """設計書: 4.4 DS-API-053b、4.6 DS-PRC-053b。更新先は preparing・shipped・delivered だけ。

    422 `unsupported_value`（未対応の更新先・追跡番号を付けられない）／
    409 `invalid_transition`（遷移表に無い）。顧客へのメールは送らない（DS-DEC-117）。
    """
    return await service.update_order_status(
        session, staff, order_number, body.status, body.tracking_number
    )
