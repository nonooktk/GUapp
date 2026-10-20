"""再入荷通知の申込 API（DS-API-007。設計仕様書 P2 追補b 4.5・DS-DEC-80）。

通知の送信（DS-PRC-007a `notify_restock`）は `services/restock.py`・`app/restock_notify.py`（CLI）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.rate_limit import ip_rate_limit
from app.core.session import CurrentMember, get_optional_member
from app.schemas.restock import RestockIn, RestockOut
from app.services import restock as restock_service

router = APIRouter(prefix="/restock-notifications", tags=["restock"])


@router.post(
    "",
    response_model=RestockOut,
    dependencies=[Depends(ip_rate_limit("restock"))],
    summary="DS-API-007 再入荷通知の申込（IP ごとに 20 回/時）",
)
async def register_restock(
    body: RestockIn,
    member: CurrentMember | None = Depends(get_optional_member),
    session: AsyncSession = Depends(get_session),
) -> RestockOut:
    """設計書: 4.5 DS-API-007、4.8 DS-PRC-007、5.6（再入荷の申込）、DS-DEC-80。

    `member` が有効なら `restock_notifications.member_id` を記録する（無効でもエラーにしない）。
    エラー: 400／404 `not_found`／409 `in_stock`／422 `limit_exceeded`・`unsupported_value`／429。
    """
    await restock_service.register(
        session, variant_id=body.variant_id, email=body.email, member=member
    )
    return RestockOut()
