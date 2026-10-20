"""受け取り店舗の読み出し（DS-TBL-10 stores。DS-API-026・DS-PRC-014-3 手順 0.5）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Store


async def list_pickup_enabled(session: AsyncSession) -> list[Store]:
    """`pickup_enabled` が真の店舗を `sort_order`・`id` の順に返す。"""
    rows = await session.execute(
        select(Store).where(Store.pickup_enabled.is_(True)).order_by(Store.sort_order, Store.id)
    )
    return list(rows.scalars().all())


async def get_pickup_enabled_by_code(session: AsyncSession, code: str) -> Store | None:
    """`code` かつ `pickup_enabled` の店舗。無ければ None（呼び手は 409 invalid_reference）。"""
    return (
        await session.execute(
            select(Store).where(Store.code == code, Store.pickup_enabled.is_(True))
        )
    ).scalar_one_or_none()


async def get_by_id(session: AsyncSession, store_id: int) -> Store | None:
    """注文の `store_id` から店舗を引く（応答の `store` 用。受け取り停止中の店舗も引く）。"""
    return await session.get(Store, store_id)
