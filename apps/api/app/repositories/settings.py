"""system_settings の読み出し（DS-TBL-21）。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemSetting


async def fetch_values(session: AsyncSession, keys: Sequence[str]) -> dict[str, object]:
    """指定キーの値を `{key: value}` で返す。無いキーは含めない（呼び手が判定する）。"""
    rows = await session.execute(
        select(SystemSetting.key, SystemSetting.value).where(SystemSetting.key.in_(list(keys)))
    )
    return {key: value for key, value in rows.all()}
