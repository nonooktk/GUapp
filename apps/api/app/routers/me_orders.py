"""注文履歴 API の骨格（DS-API-024・024a。設計仕様書 P2 追補b 4.2・4.8・DS-DEC-77・78）。

担当レーン: ルーターの骨格は A、**中身は C**。BFF の窓口はなく、Server Component が
`X-Session-Token` を付けて直接呼ぶ。他人・ゲスト・不存在・形の不正は区別せず同じ 404。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import not_implemented
from app.core.session import CurrentMember, get_current_member
from app.schemas.order import OrderHistoryOut, OrderOut

router = APIRouter(prefix="/me/orders", tags=["me-orders"])


@router.get("", response_model=OrderHistoryOut, summary="DS-API-024 注文履歴の一覧")
async def list_my_orders(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=50),
    member: CurrentMember = Depends(get_current_member),
    session: AsyncSession = Depends(get_session),
) -> OrderHistoryOut:
    """担当レーン: C。設計書: 4.2 DS-API-024、4.8 DS-PRC-024・024a、DS-DEC-77・78。

    自分の `member_id` の注文だけを `created_at` の新しい順（同時刻は `id` の降順）に返す。
    決済失敗の注文も含め、ゲスト注文は含めない。0 件でも 200。
    範囲外の `page`・`per_page` は 400（このシグネチャの `Query` の制約が担う）。
    """
    raise not_implemented()


@router.get("/{order_number}", response_model=OrderOut, summary="DS-API-024a 注文履歴の詳細")
async def get_my_order(
    order_number: str,
    member: CurrentMember = Depends(get_current_member),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """担当レーン: C。設計書: 4.2 DS-API-024a、4.4（OrderOut）、4.8 DS-PRC-024a。

    `order_number` が `^GU-[0-9]{6}-[A-HJ-NP-Z2-9]{8}$` に合わなければ 400 ではなく 404
    （存在しない・他人・ゲスト・形の不正を区別しない）。
    """
    raise not_implemented()
