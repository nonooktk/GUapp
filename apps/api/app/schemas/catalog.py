"""商品カタログ系の応答（DS-API-001〜003）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GenderLiteral = Literal["women", "men", "kids_teen", "all"]

# 一覧の 1 ページ件数（契約: 1〜48、既定 24）
PER_PAGE_DEFAULT = 24
PER_PAGE_MAX = 48


class CategoryChildOut(BaseModel):
    slug: str
    name: str
    kind: str | None = Field(
        description="種類（tops など）。性別をまたいで同じ種類を束ねる軸。商品一覧の kind に渡す"
    )
    product_count: int = Field(description="公開商品の件数")


class CategoryOut(BaseModel):
    slug: str
    name: str
    gender: GenderLiteral
    children: list[CategoryChildOut]


class CategoriesResponse(BaseModel):
    categories: list[CategoryOut]


class ProductListItemOut(BaseModel):
    id: int
    name: str
    price_incl_tax: int
    image_path: str | None = Field(description="先頭画像のパス。無ければ null")
    colors: list[str]
    sold_out: bool = Field(description="全バリエーション在庫 0")


class ProductListResponse(BaseModel):
    items: list[ProductListItemOut]
    page: int
    per_page: int
    total: int
    has_more: bool


class VariantOut(BaseModel):
    variant_id: int
    color: str
    size: str
    in_stock: bool


class RelatedProductOut(BaseModel):
    id: int
    name: str
    price_incl_tax: int
    image_path: str | None
    sold_out: bool


class FitSummaryOut(BaseModel):
    """サイズ感の集計（DS-API-003・DS-PRC-003a。設計仕様書 P2 追補b 4.6）。

    元は `reviews` のうち `approved` が真で `fit` が NULL でないもの。`total` は
    `small + just + large` に等しい。割合は返さない（画面が件数を並べる。DS-DEC-81）。
    レビューが 0 件でもキーは常に出す。担当レーン: 型は A、集計は C。
    """

    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total: int = 0
    small: int = 0
    just: int = 0
    large: int = 0


class ProductDetailOut(BaseModel):
    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    description: str
    material: str
    price_incl_tax: int
    images: list[str]
    colors: list[str]
    sizes: list[str]
    variants: list[VariantOut]
    related: list[RelatedProductOut] = Field(
        description="同カテゴリの公開商品。自分以外・最大 4 件"
    )
    # P2-b: C が集計を入れるまでは 0 件（ゼロ埋め）。キーは常に出す
    fit_summary: FitSummaryOut = Field(default_factory=FitSummaryOut)
