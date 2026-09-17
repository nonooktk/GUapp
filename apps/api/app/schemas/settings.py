"""公開設定の応答（DS-API-020）。この 3 キーだけを返す（payment_timeout_minutes は出さない）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PublicSettingsOut(BaseModel):
    tax_rate: str = Field(description='税率。"0.10" 形式の文字列（DS-DEC-31）')
    shipping_fee: int
    free_shipping_threshold: int
