"""商品カタログ系の応答（DS-API-001〜003）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GenderLiteral = Literal["women", "men", "kids_teen", "all"]

# 一覧の 1 ページ件数（契約: 1〜48、既定 24）
PER_PAGE_DEFAULT = 24
PER_PAGE_MAX = 48


class CategoryChildOut(BaseModel):
    slug: str
    name: str
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


class ProductDetailOut(BaseModel):
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
