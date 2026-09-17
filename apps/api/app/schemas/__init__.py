"""要求／応答スキーマ（Pydantic）。API 契約の正本は `apps/api/openapi.json`。

- 応答は `response_model` で白リスト化する（設計仕様書 7.5）。内部 ID・外部キーは
  契約で許されたもの（商品 `id`・`variant_id`・カート明細 `item_id`）だけを出す。
- 要求には「形」の検証だけを書く（業務上限は書かない。設計仕様書 4.5）。
"""

from app.schemas.cart import CartItemIn, CartItemPatchIn, CartLineOut, CartResponse
from app.schemas.catalog import (
    CategoriesResponse,
    CategoryChildOut,
    CategoryOut,
    ProductDetailOut,
    ProductListItemOut,
    ProductListResponse,
    RelatedProductOut,
    VariantOut,
)
from app.schemas.settings import PublicSettingsOut

__all__ = [
    "CartItemIn",
    "CartItemPatchIn",
    "CartLineOut",
    "CartResponse",
    "CategoriesResponse",
    "CategoryChildOut",
    "CategoryOut",
    "ProductDetailOut",
    "ProductListItemOut",
    "ProductListResponse",
    "PublicSettingsOut",
    "RelatedProductOut",
    "VariantOut",
]
