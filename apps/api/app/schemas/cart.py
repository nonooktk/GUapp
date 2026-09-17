"""カート系の要求／応答（DS-API-010〜013）。

カートの識別はヘッダ `X-Cart-Token`（BFF が Cookie から移す）。応答に `cart_id` は出さない
（設計仕様書 7.5）。`item_id` と `variant_id` は契約で許された例外。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StockStatus = Literal["ok", "insufficient", "out_of_stock"]

CART_TOKEN_HEADER = "X-Cart-Token"


class CartItemIn(BaseModel):
    """POST /cart/items。上限（10・50）は業務規則なのでここには書かない（422 で返す）。"""

    variant_id: int
    quantity: int = Field(gt=0)


class CartItemPatchIn(BaseModel):
    """PATCH /cart/items/{item_id}。"""

    quantity: int = Field(gt=0)


class CartLineOut(BaseModel):
    item_id: int
    variant_id: int
    product_id: int
    product_name: str
    color: str
    size: str
    unit_price: int
    quantity: int
    line_total: int
    stock_status: StockStatus
    image_path: str | None


class CartResponse(BaseModel):
    cart_token: str
    items: list[CartLineOut]
    item_count: int = Field(description="数量の合計")
    subtotal: int
    shipping_fee: int
    total: int
    free_shipping_threshold: int
    can_checkout: bool = Field(description="明細 1 件以上かつ全明細が ok")
