"""管理：注文 API のスキーマ（DS-API-053・053a・053b。設計仕様書 P2 追補c 4.4）。

担当レーン: C-3。

- 応答に内部 ID（注文・会員・店舗・管理者の ID）、受け取りコード（`pickup_code`）、
  完全な電話番号・メールアドレスを出さない（DS-DEC-118・ST-SEC-88）
- 要求の定義外の項目は無視する（Pydantic の既定。mass assignment を許さない。IT-053b-10）
- 型・形式・必須欠落は 400（Pydantic。`validation_error`）、業務の範囲外は 422
  （サービス層。DS-DEC-124）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from app.models import OrderStatus

# 追跡番号の形（DS-API-053b）。全角・空白・51 文字以上は 400
TRACKING_NUMBER_RE = r"^[A-Za-z0-9-]{1,50}$"

ReceiveMethodOut = Literal["delivery", "store"]
CustomerType = Literal["member", "guest"]


class _Out(BaseModel):
    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class AdminOrderListItemOut(_Out):
    """DS-API-053 一覧の 1 行。氏名・電話・住所は出さない。"""

    order_number: str
    ordered_at: datetime
    status: str
    status_label: str
    receive_method: ReceiveMethodOut
    total: int
    item_count: int
    customer_type: CustomerType
    email_masked: str


class TransitionOut(_Out):
    """次に更新できる状態（`available_transitions` の 1 件）。"""

    status: str
    label: str
    accepts_tracking_number: bool


class AdminOrderStoreOut(_Out):
    """受け取り店舗。内部 ID・郵便番号は含めない。"""

    name: str
    prefecture: str
    address: str


class AdminOrderItemOut(_Out):
    """明細（注文時点の値）。"""

    product_name: str
    color: str
    size: str
    unit_price: int
    quantity: int


class AdminPaymentOut(_Out):
    """最新の決済。カード情報は保存していないので出ない。"""

    provider: str
    result: str


class AdminCustomerOut(_Out):
    """注文者。電話は末尾 4 桁だけ、メールはマスク。`postal_code`・`address` は配送のときだけ。"""

    type: CustomerType
    name: str
    email_masked: str
    phone_masked: str
    postal_code: str | None = None
    address: str | None = None

    @model_serializer(mode="wrap")
    def _drop_absent_ship_fields(self, handler: Any) -> dict[str, Any]:
        # 店舗受け取りでは `postal_code`・`address` のキーを出さない（店舗の値のため）
        data = handler(self)
        for key in ("postal_code", "address"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class AdminOrderDetailOut(_Out):
    """DS-API-053a 注文詳細。"""

    order_number: str
    ordered_at: datetime
    status: str
    status_label: str
    receive_method: ReceiveMethodOut
    store: AdminOrderStoreOut | None
    items: list[AdminOrderItemOut]
    subtotal: int
    shipping_fee: int
    discount: int
    total: int
    tax_included: int
    tax_rate: str
    payment: AdminPaymentOut | None
    customer: AdminCustomerOut
    tracking_number: str | None
    available_transitions: list[TransitionOut]


class OrderStatusUpdateIn(BaseModel):
    """DS-API-053b の要求。`status` は 8 値のどれか（列挙外・null・数値は 400）。

    更新先が `preparing`・`shipped`・`delivered` 以外なら、形は正しいのでサービス層が 422。
    `tracking_number` を付けられるのは配送で更新先が `shipped` のときだけ（サービス層が 422）。
    """

    status: OrderStatus
    tracking_number: str | None = Field(default=None, pattern=TRACKING_NUMBER_RE)


class OrderStatusUpdateOut(_Out):
    """DS-API-053b の応答（形は DS-API-053a の該当部分と同じ）。"""

    order_number: str
    status: str
    status_label: str
    tracking_number: str | None
    available_transitions: list[TransitionOut]
