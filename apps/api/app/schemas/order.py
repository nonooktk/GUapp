"""注文系の要求／応答（DS-API-021〜023・024・024a）。

- 入力形式は設計仕様書 4.4 の表どおり「形」だけを検証する（業務規則は書かない。4.5）。
  郵便番号・電話はハイフン・空白を除去してから検査する（`mode="before"`）。
- 応答に内部 ID（order id・cart id・variant id・member id・store id）は出さない（7.5）。
- P2-b（設計仕様書 P2 追補b 4.2・4.4）: 店舗受け取り（`store_code`）・会員の注文履歴・
  `OrderOut` の新項目をここに置く。担当レーン: A（型）。値を入れるのは C
  （`status_label`・`pickup_code`・`tracking_number` の判定は
  `services/order_status.py` の 1 か所）。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.cart import CartLineOut

IDEMPOTENCY_KEY_RE = r"^[A-Za-z0-9_-]{43}$"
# Python の `\d` は全角数字にも一致するので、ASCII 数字だけを許す（DB は String(7)／String(11)）
POSTAL_CODE_RE = r"^[0-9]{7}$"
PHONE_RE = r"^[0-9]{10,11}$"
# 店舗コード: ASCII の小文字・数字・ハイフンのみ（`\d` を使わない。設計仕様書 4.4・9.2 観点 5）
STORE_CODE_RE = r"^[a-z0-9-]{1,32}$"
# 受け取り方法。API の入力では未知の値を 422 にするため、OrderCreateIn は str で受ける
ReceiveMethodLiteral = Literal["delivery", "store"]
_STRIP_RE = re.compile(r"[\s\-‐‑–—ー－]")


def _strip_separators(value: object) -> object:
    if isinstance(value, str):
        return _STRIP_RE.sub("", value)
    return value


class PrepareIn(BaseModel):
    """POST /checkout/prepare の本文（DS-API-021。P2-b で任意の本文を受ける）。

    本文が無い呼び出しは従来どおり `delivery`（ルーターは `PrepareIn | None` で受けて
    None を既定値に読み替える。担当レーン: C）。未知の値は 400 `validation_error`。
    """

    receive_method: ReceiveMethodLiteral = "delivery"


class PrepareOut(BaseModel):
    """POST /checkout/prepare（DS-API-021）。金額は DS-PRC-021・021a。"""

    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    idempotency_key: str = Field(description="注文確定に 1 回だけ使う 43 文字の base64url")
    items: list[CartLineOut]
    subtotal: int
    shipping_fee: int
    total: int
    tax_included: int
    tax_rate: str
    free_shipping_threshold: int
    # P2-b: `store` のとき送料 0（DS-PRC-021a）。従来の呼び出しは `delivery`
    receive_method: ReceiveMethodLiteral = "delivery"


class DisplayAmounts(BaseModel):
    """確認画面に表示した金額。確定時に再計算値と照合する（1 円でも違えば 409 price_changed）。"""

    subtotal: int
    shipping_fee: int
    total: int


class OrderCreateIn(BaseModel):
    """POST /orders（DS-API-022）。

    P2-b の条件付き必須（設計仕様書 4.4・4.8 DS-PRC-014-3 手順 0）:
    - `receive_method=delivery`: `ship_postal_code`・`ship_address` が必須（無ければ 400 required）
    - `receive_method=store`: `store_code` が必須（無ければ 400 required）。
      `ship_postal_code`・`ship_address` は**無視する**（入力値は捨てて None にする。店舗の値で
      上書きするので、mass assignment を許さない）。形が不正でも 400 にしない
    - 未知の `receive_method` は形としては正しいので、ここでは条件付き必須を課さず、
      サービス層が 422 `unsupported_value` にする。`delivery` で `store_code` があるときも
      サービス層が 422 `unsupported_value`（field `store_code`）にする（C）

    フィールドの宣言順は意味を持つ（`receive_method` を先に検証し、後続の検証が参照する）。
    """

    idempotency_key: str = Field(pattern=IDEMPOTENCY_KEY_RE)
    ship_name: str = Field(min_length=1, max_length=50)
    # 許容値（delivery／store／card）以外は形としては正しいので 400 にせず、サービス層で 422
    receive_method: str = Field(min_length=1, max_length=20)
    store_code: str | None = Field(default=None, pattern=STORE_CODE_RE, validate_default=True)
    ship_postal_code: str | None = Field(
        default=None, pattern=POSTAL_CODE_RE, validate_default=True
    )
    ship_address: str | None = Field(
        default=None, min_length=1, max_length=200, validate_default=True
    )
    ship_phone: str = Field(pattern=PHONE_RE)
    guest_email: EmailStr = Field(max_length=254)
    payment_method: str = Field(min_length=1, max_length=20)
    display: DisplayAmounts

    @field_validator("ship_phone", mode="before")
    @classmethod
    def _strip_phone(cls, value: object) -> object:
        return _strip_separators(value)

    @field_validator("ship_postal_code", "ship_address", mode="before")
    @classmethod
    def _ship_fields_by_method(cls, value: object, info: ValidationInfo) -> object:
        method = info.data.get("receive_method")
        if method == "store":
            return None  # 店舗受け取りでは無視する
        if info.field_name == "ship_postal_code":
            value = _strip_separators(value)
        if method == "delivery" and value is None:
            raise PydanticCustomError("missing", "配送では必須です")
        return value

    @field_validator("store_code", mode="before")
    @classmethod
    def _store_code_required_for_store(cls, value: object, info: ValidationInfo) -> object:
        if info.data.get("receive_method") == "store" and value is None:
            raise PydanticCustomError("missing", "店舗受け取りでは必須です")
        return value

    @field_validator("ship_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        # 全角スペースも空白扱い（str.strip() は U+3000 を除く）
        if not value.strip():
            # 空白のみは「未入力」。空文字（min_length 違反）と同じ型で投げ、
            # 例外ハンドラが reason=required に揃える（4.5）
            raise PydanticCustomError("string_too_short", "氏名に空白以外の文字を含めてください")
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


class OrderStoreOut(BaseModel):
    """注文の受け取り店舗（店舗受け取りのときだけ）。内部 ID・郵便番号は含めない（4.4）。"""

    name: str
    prefecture: str
    address: str


class OrderOut(BaseModel):
    """注文応答（DS-API-022／023／024a 共通。P2-b の新項目は 4.4）。

    新項目の既定値は、値を入れる前の実装（P1・P2-a のサービス）でも型が通るようにするための
    もの。C が `build_order_response` で必ず実際の値を入れる:
    `status_label` は `services/order_status.py`（DS-PRC-024a）の表示名、`pickup_code`・
    `tracking_number` は同じ関数が決める表示条件を満たすときだけ値、`store` は店舗受け取り
    のときだけ、`is_member_order` は `orders.member_id` が NULL でないか。
    """

    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

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
    receive_method: ReceiveMethodLiteral
    payment_method: str
    ordered_at: datetime = Field(description="ISO 8601（UTC）")
    # ── P2-b（4.4）。担当レーン: 型は A、値は C ──
    status_label: str = Field(
        default="", description="受付から受け取り可能までの区分の表示名（DS-PRC-024a）"
    )
    store: OrderStoreOut | None = Field(default=None, description="店舗受け取りのときだけ")
    pickup_code: str | None = Field(
        default=None,
        description="8 文字。store で状態が accepted・preparing・shipped のときだけ（DS-PRC-024a）",
    )
    tracking_number: str | None = Field(
        default=None,
        description="delivery で状態が shipped・delivered かつ登録済みのときだけ",
    )
    is_member_order: bool = Field(
        default=False, description="注文に会員が紐づいているか（完了画面の案内の出し分け）"
    )


class OrderHistoryItemOut(BaseModel):
    """GET /me/orders の 1 件（DS-API-024）。内部 ID は出さない。"""

    order_number: str
    status: OrderStatusLiteral
    status_label: str
    ordered_at: datetime = Field(description="ISO 8601（UTC）")
    total: int
    receive_method: ReceiveMethodLiteral
    item_count: int = Field(description="数量の合計")
    first_item_name: str


class OrderHistoryOut(BaseModel):
    """GET /me/orders（DS-API-024）。注文が 0 件でも 200 で `items` は空配列。"""

    items: list[OrderHistoryItemOut]
    page: int
    per_page: int
    total: int
    has_more: bool


__all__ = [
    "IDEMPOTENCY_KEY_RE",
    "PHONE_RE",
    "POSTAL_CODE_RE",
    "STORE_CODE_RE",
    "DisplayAmounts",
    "LookupIn",
    "OrderCreateIn",
    "OrderHistoryItemOut",
    "OrderHistoryOut",
    "OrderItemOut",
    "OrderOut",
    "OrderStoreOut",
    "PrepareIn",
    "PrepareOut",
    "ReceiveMethodLiteral",
]
