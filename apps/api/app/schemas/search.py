"""商品検索系の応答（DS-API-004・004a。設計仕様書 P2 追補a 4.1）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.catalog import ProductListItemOut


class RecommendedCategoryOut(BaseModel):
    slug: str
    name: str
    product_count: int = Field(description="公開商品の件数")


class SearchResponse(BaseModel):
    query: str = Field(description="正規化後の検索語")
    items: list[ProductListItemOut]
    page: int
    per_page: int
    total: int
    has_more: bool
    similar_keywords: list[str] = Field(description="0 件のときだけ候補が入る。それ以外は空配列")
    recommended_categories: list[RecommendedCategoryOut] = Field(
        description="0 件のときだけ候補が入る。それ以外は空配列"
    )


class SuggestItemOut(BaseModel):
    id: int
    name: str


class SuggestResponse(BaseModel):
    items: list[SuggestItemOut] = Field(description="商品名の前方一致優先・部分一致補充。最大5件")
