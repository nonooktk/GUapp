"""管理：商品・在庫 API の要求／応答（DS-API-051・051a・051b・051c。P2 追補c 4.2・4.7）。

担当レーン: C-2。400 と 422 の境目（DS-DEC-124）:

- 型・形式・必須欠落・桁あふれ（絶対値が 2,147,483,647 を超える整数）は **400**（このファイル。
  Pydantic が検査し、例外ハンドラが 400 `validation_error` にする）
- 形は正しいが業務の範囲外（在庫 0〜9999、価格 1〜1,000,000）は **422**
  （`services/admin_products.py`）

整数は `StrictInt`（真偽値・文字列・小数・null を通さない）。応答に内部 ID（`product_id`・
`variant_id` を除く）・メールアドレスを出さない。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)
from pydantic_core import InitErrorDetails, ValidationError

from app.core.errors import AppError
from app.schemas.admin_common import INT32_MAX

# 本編 7.7 S7: パスの ID は 1 以上 9223372036854775807 以下（外れたら 400）
ID_MAX = 9223372036854775807
# 一覧の `q` の長さ（NFKC 正規化・前後空白除去のあと）
Q_MAX_LENGTH = 50
# 正規化の前の入力の上限（巨大な文字列を正規化しないための足切り。超えたら too_long）
Q_RAW_MAX_LENGTH = 500


class _Out(BaseModel):
    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


# ── 一覧（DS-API-051）─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProductListParams:
    """検証済みの一覧の絞り込み。`q` は正規化済み（空なら条件なし）。"""

    q: str
    visibility: Literal["all", "public", "private"]
    stock: Literal["all", "out"]


def normalize_q(raw: str) -> str:
    """NFKC 正規化 → 前後空白除去 → 50 文字以内。超えたら 400 `validation_error`（too_long）。"""
    q = unicodedata.normalize("NFKC", raw).strip()
    if len(q) > Q_MAX_LENGTH:
        raise AppError(400, "validation_error", fields=[{"name": "q", "reason": "too_long"}])
    return q


def product_list_params(
    q: str = Query(default="", max_length=Q_RAW_MAX_LENGTH),
    visibility: Literal["all", "public", "private"] = Query(default="all"),
    stock: Literal["all", "out"] = Query(default="all"),
) -> ProductListParams:
    """`Depends(product_list_params)` で受ける。範囲外・列挙外は 400 `validation_error`。"""
    return ProductListParams(q=normalize_q(q), visibility=visibility, stock=stock)


class AdminProductListItemOut(_Out):
    product_id: int
    name: str
    price_incl_tax: int = Field(description="税込・円")
    published: bool
    variant_count: int
    total_stock: int
    out_of_stock_variants: int = Field(description="在庫 0 のバリエーションの数")


# ── 詳細（DS-API-051a）────────────────────────────────────────────────────────


class AdminVariantOut(_Out):
    variant_id: int
    sku: str
    color: str
    size: str
    stock: int
    restock_waiting: int = Field(description="未通知の再入荷申込の件数。メールアドレスは返さない")


class AdminProductDetailOut(_Out):
    product_id: int
    name: str
    price_incl_tax: int = Field(description="税込・円")
    published: bool
    updated_at: datetime = Field(description="ISO 8601（UTC）")
    variants: list[AdminVariantOut]


# ── 商品の更新（DS-API-051b）──────────────────────────────────────────────────


class ProductUpdateIn(BaseModel):
    """`published`・`price_incl_tax` のうち変更するものと、対応する `expected_*`。

    - 変更する項目には対応する `expected_*` が必須（無ければ 400 `required`）
    - 変更する項目が 1 つもなければ 400（`name: "body"`、`required`）
    - 明示的な null は型違い（400）。定義外の項目は無視する（Pydantic の既定）
    - 価格の業務の範囲（1〜1,000,000）はここでは検査しない（サービスが 404 のあとで 422 にする）
    """

    # `default=None` は「送られていない」の印。検証は通さないので、null は型違いで 400 になる
    published: StrictBool = Field(default=None)
    price_incl_tax: StrictInt = Field(default=None, ge=-INT32_MAX, le=INT32_MAX)
    expected_published: StrictBool = Field(default=None)
    expected_price_incl_tax: StrictInt = Field(default=None, ge=0, le=INT32_MAX)

    @model_validator(mode="after")
    def _check_pairs(self) -> ProductUpdateIn:
        errors: list[InitErrorDetails] = []
        if self.published is None and self.price_incl_tax is None:
            errors.append(InitErrorDetails(type="missing", loc=(), input=None))
        if self.published is not None and self.expected_published is None:
            errors.append(InitErrorDetails(type="missing", loc=("expected_published",), input=None))
        if self.price_incl_tax is not None and self.expected_price_incl_tax is None:
            errors.append(
                InitErrorDetails(type="missing", loc=("expected_price_incl_tax",), input=None)
            )
        if errors:
            raise ValidationError.from_exception_data("ProductUpdateIn", errors)
        return self


class ProductUpdateOut(_Out):
    product_id: int
    published: bool
    price_incl_tax: int
    changed: bool = Field(description="値が変わったか。同じ値なら更新も監査ログもしない")
    updated_at: datetime = Field(description="ISO 8601（UTC）")


# ── 在庫の更新（DS-API-051c）──────────────────────────────────────────────────


class StockUpdateIn(BaseModel):
    """絶対値の SET。`stock` の業務の範囲（0〜9999）はサービスが 422 にする。"""

    stock: StrictInt = Field(ge=-INT32_MAX, le=INT32_MAX)
    expected_stock: StrictInt = Field(ge=0, le=INT32_MAX, description="画面が表示していた在庫")


class StockUpdateOut(_Out):
    variant_id: int
    sku: str
    stock: int
    previous_stock: int
    changed: bool
    restock_waiting: int = Field(
        description="在庫が 0 から 1 以上になったときだけ、更新の時点の未通知の申込件数（他は 0）"
    )
