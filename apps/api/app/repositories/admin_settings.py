"""管理：設定（`system_settings`）の読み書き（DS-PRC-052。設計仕様書 P2 追補c 4.3・4.6）。

担当レーン: C-2。公開側の `repositories/settings.py` とは別物。更新するキーの行は
**キー名の昇順**で `FOR UPDATE` する（同時更新どうしの待ちが循環しないよう、順序を固定する）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemSetting


async def fetch_values(session: AsyncSession, keys: Sequence[str]) -> dict[str, Any]:
    """指定キーの現在の値。無いキーは含めない。ロックはしない。"""
    rows = await session.execute(
        select(SystemSetting.key, SystemSetting.value).where(SystemSetting.key.in_(list(keys)))
    )
    return {key: value for key, value in rows.all()}


async def lock_values(session: AsyncSession, keys: Sequence[str]) -> dict[str, Any]:
    """指定キーの行を、キー名の昇順で `FOR UPDATE` して値を返す。無いキーは含めない。"""
    rows = await session.execute(
        select(SystemSetting.key, SystemSetting.value)
        .where(SystemSetting.key.in_(list(keys)))
        .order_by(SystemSetting.key)
        .with_for_update()
    )
    return {key: value for key, value in rows.all()}


async def set_value(session: AsyncSession, key: str, value: Any) -> None:
    await session.execute(update(SystemSetting).where(SystemSetting.key == key).values(value=value))
