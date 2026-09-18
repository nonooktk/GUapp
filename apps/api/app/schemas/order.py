"""注文系の要求／応答（DS-API-021〜023）。

- 入力形式は設計仕様書 4.4 の表どおり「形」だけを検証する（業務規則は書かない。4.5）。
  郵便番号・電話はハイフン・空白を除去してから検査する（`mode="before"`）。
- 応答に内部 ID（order id・cart id・variant id）は出さない（7.5）。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.cart import CartLineOut

IDEMPOTENCY_KEY_RE = r"^[A-Za-z0-9_-]{43}$"
# Python の `\d` は全角数字にも一致するので、ASCII 数字だけを許す（DB は String(7)／String(11)）
POSTAL_CODE_RE = r"^[0-9]{7}$"
PHONE_RE = r"^[0-9]{10,11}$"
_STRIP_RE = re.compile(r"[\s\-‐‑–—ー－]")


def _strip_separators(value: object) -> object:
    if isinstance(value, str):
        return _STRIP_RE.sub("", value)
    return value


class PrepareOut(BaseModel):
    """POST /checkout/prepare（DS-API-021）。金額は DS-PRC-021。"""

    idempotency_key: str = Field(description="注文確定に 1 回だけ使う 43 文字の base64url")
    items: list[CartLineOut]
    subtotal: int
    shipping_fee: int
    total: int
    tax_included: int
    tax_rate: str
    free_shipping_threshold: int


class DisplayAmounts(BaseModel):
    """確認画面に表示した金額。確定時に再計算値と照合する（1 円でも違えば 409 price_changed）。"""

    subtotal: int
    shipping_fee: int
    total: int


class OrderCreateIn(BaseModel):
    """POST /orders（DS-API-022）。"""

    idempotency_key: str = Field(pattern=IDEMPOTENCY_KEY_RE)
    ship_name: str = Field(min_length=1, max_length=50)
    ship_postal_code: str = Field(pattern=POSTAL_CODE_RE)
    ship_address: str = Field(min_length=1, max_length=200)
    ship_phone: str = Field(pattern=PHONE_RE)
    guest_email: EmailStr = Field(max_length=254)
    # 許容値（delivery／card）以外は形としては正しいので 400 にせず、サービス層で 422
    receive_method: str = Field(min_length=1, max_length=20)
    payment_method: str = Field(min_length=1, max_length=20)
    display: DisplayAmounts

    @field_validator("ship_postal_code", "ship_phone", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return _strip_separators(value)

    @field_validator("ship_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        # 全角スペースも空白扱い（str.strip() は U+3000 を除く）
        if not value.strip():
            raise ValueError("氏名に空白以外の文字を含めてください")
        return value


class LookupIn(BaseModel):
    """POST /orders/{order_number}/lookup（DS-API-023）。メールは本文で受ける。"""

    guest_email: EmailStr = Field(max_length=254)


class OrderItemOut(BaseModel):
    product_name: str
    color: str
    size: str
    unit_price: int
    quantity: int
    line_total: int


OrderStatusLiteral = Literal[
    "pending_payment",
    "accepted",
    "preparing",
    "shipped",
    "delivered",
    "pickup_expired",
    "cancelled",
    "payment_failed",
]


class OrderOut(BaseModel):
    """注文応答（DS-API-022／023 共通）。"""

    order_number: str
    status: OrderStatusLiteral
    items: list[OrderItemOut]
    subtotal: int
    shipping_fee: int
    total: int
    tax_included: int
    tax_rate: str
    ship_name: str
    ship_postal_code: str
    ship_address: str
    ship_phone: str
    guest_email: str
    receive_method: str
    payment_method: str
    ordered_at: datetime = Field(description="ISO 8601（UTC）")


__all__ = [
    "IDEMPOTENCY_KEY_RE",
    "PHONE_RE",
    "POSTAL_CODE_RE",
    "DisplayAmounts",
    "LookupIn",
    "OrderCreateIn",
    "OrderItemOut",
    "OrderOut",
    "PrepareOut",
]
