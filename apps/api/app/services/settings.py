"""公開設定（DS-API-020）。`system_settings` を読んで型を確定させる。

キー欠落・型不正は設定投入漏れ（運用事故）なので 500 `internal_error` にし、詳細はログへ。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import internal_error
from app.repositories import settings as settings_repo
from app.services.pricing import PricingSettings, tax_rate_basis_points

logger = logging.getLogger("app.services.settings")

PUBLIC_SETTING_KEYS: tuple[str, ...] = ("tax_rate", "shipping_fee", "free_shipping_threshold")


def _to_int(key: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        logger.error("system_settings.%s が整数ではありません（%s）", key, type(value).__name__)
        raise internal_error()
    return value


def _to_tax_rate(value: object) -> str:
    if not isinstance(value, str):
        logger.error("system_settings.tax_rate が文字列ではありません（%s）", type(value).__name__)
        raise internal_error()
    try:
        tax_rate_basis_points(value)
    except ValueError:
        logger.error("system_settings.tax_rate を数値として解釈できません")
        raise internal_error() from None
    return value


async def get_public_settings(session: AsyncSession) -> PricingSettings:
    """3 キーだけを返す。`payment_timeout_minutes` など内部設定は含めない（IT-020-01）。"""
    raw = await settings_repo.fetch_values(session, PUBLIC_SETTING_KEYS)
    missing = [k for k in PUBLIC_SETTING_KEYS if k not in raw]
    if missing:
        logger.error("system_settings にキーがありません: %s", missing)
        raise internal_error()
    return PricingSettings(
        tax_rate=_to_tax_rate(raw["tax_rate"]),
        shipping_fee=_to_int("shipping_fee", raw["shipping_fee"]),
        free_shipping_threshold=_to_int(
            "free_shipping_threshold", raw["free_shipping_threshold"]
        ),
    )
