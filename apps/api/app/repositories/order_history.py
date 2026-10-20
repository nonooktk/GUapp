"""注文履歴の読み出し（DS-PRC-024。設計仕様書 P2 追補b 4.2・DS-DEC-77・78）。

索引は `ix_orders_member_id_created_at (member_id, created_at)`。明細はページ内の注文 ID に
対する 1 回の `IN` 取得で求め、注文ごとの N+1 にしない。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderItem


async def list_by_member(
    session: AsyncSession, member_id: int, *, page: int, per_page: int
) -> tuple[list[Order], int]:
    """自分の `member_id` の注文を新しい順（同時刻は id の降順）に。総件数は別の COUNT。

    決済失敗の注文も含める。ゲスト注文（member_id NULL）は含めない（DS-DEC-77）。
    """
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(Order).where(Order.member_id == member_id)
            )
        ).scalar_one()
    )
    rows = await session.execute(
        select(Order)
        .where(Order.member_id == member_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    return list(rows.scalars().all()), total


async def get_by_member_and_number(
    session: AsyncSession, member_id: int, order_number: str
) -> Order | None:
    """`member_id` と注文番号の両方が一致する注文だけ返す（他人・ゲスト・不存在は None）。"""
    return (
        await session.execute(
            select(Order).where(Order.member_id == member_id, Order.order_number == order_number)
        )
    ).scalar_one_or_none()


async def list_items_for_orders(
    session: AsyncSession, order_ids: list[int]
) -> dict[int, list[OrderItem]]:
    """注文 ID → 明細（id 順）。ページ分を 1 回の `IN` 取得で求める（N+1 にしない）。"""
    if not order_ids:
        return {}
    rows = await session.execute(
        select(OrderItem)
        .where(OrderItem.order_id.in_(order_ids))
        .order_by(OrderItem.order_id, OrderItem.id)
    )
    out: dict[int, list[OrderItem]] = {}
    for item in rows.scalars().all():
        out.setdefault(item.order_id, []).append(item)
    return out
