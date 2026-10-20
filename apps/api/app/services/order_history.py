"""注文履歴（DS-API-024・024a。設計仕様書 P2 追補b 4.2・4.8 DS-PRC-024・DS-DEC-77・78）。

- 一覧: 自分の `member_id` の注文だけを新しい順に返す。ゲスト注文は含めない。決済失敗も含む
- 詳細: 他人・ゲスト・不存在・形の不正は区別せず同じ 404（IDOR を作らない）
- 表示名・受け取りコード・追跡番号の出し分けは `order_status`（確定・照会と同じ関数）
"""

from __future__ import annotations

from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.session import CurrentMember
from app.models import ReceiveMethod
from app.repositories import order_history as history_repo
from app.schemas.order import OrderHistoryItemOut, OrderHistoryOut, OrderOut
from app.services import order_status
from app.services.order_number import ORDER_NUMBER_RE
from app.services.orders import build_order_response

_ASCII_DIGITS = frozenset("0123456789")


def is_order_number_shape(value: str) -> bool:
    """`^GU-[0-9]{6}-[A-HJ-NP-Z2-9]{8}$` に合うか（全角数字は不可）。"""
    # 既存の ORDER_NUMBER_RE は `\d` を使うため全角数字にも一致する。ASCII 数字に絞って確かめる
    return (
        ORDER_NUMBER_RE.fullmatch(value) is not None
        and value.isascii()
        and all(c in _ASCII_DIGITS for c in value[3:9])
    )


async def list_my_orders(
    session: AsyncSession, member: CurrentMember, *, page: int, per_page: int
) -> OrderHistoryOut:
    orders, total = await history_repo.list_by_member(
        session, member.id, page=page, per_page=per_page
    )
    items_by_order = await history_repo.list_items_for_orders(session, [o.id for o in orders])
    out: list[OrderHistoryItemOut] = []
    for o in orders:
        items = items_by_order.get(o.id, [])
        out.append(
            OrderHistoryItemOut(
                order_number=o.order_number,
                status=o.status.value,
                status_label=order_status.status_label(o.status, ReceiveMethod(o.receive_method)),
                ordered_at=o.created_at.replace(tzinfo=UTC),
                total=o.total,
                receive_method=ReceiveMethod(o.receive_method).value,
                item_count=sum(i.quantity for i in items),
                # 決済失敗の注文は明細を持たない（確定の COMMIT でだけ入れる）ので空文字
                first_item_name=items[0].product_name_at_order if items else "",
            )
        )
    return OrderHistoryOut(
        items=out,
        page=page,
        per_page=per_page,
        total=total,
        has_more=page * per_page < total,
    )


async def get_my_order(session: AsyncSession, member: CurrentMember, order_number: str) -> OrderOut:
    """形が不正でも、存在しなくても、他人・ゲストの注文でも 404 `not_found`（本文も同一）。"""
    if not is_order_number_shape(order_number):
        raise AppError(404, "not_found")
    order = await history_repo.get_by_member_and_number(session, member.id, order_number)
    if order is None:
        raise AppError(404, "not_found")
    return await build_order_response(session, order)
