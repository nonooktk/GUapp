"""管理 API 共通のスキーマ（ページ送りの入力と応答。設計仕様書 P2 追補c 4.0・11.3）。

担当レーン: C-1（C-2・C-3 は使うだけで、変更せずコーディネーターに依頼する）。

一覧は `page`（1 以上、既定 1）、`per_page`（1〜100、既定 20）を受け、
`{"items", "page", "per_page", "total", "has_more"}` を返す。0 件でも 200 で `items` は空配列。

使い方（C-2 の商品一覧・C-3 の注文の検索）::

    @router.get("/products", response_model=Page[AdminProductListItemOut])
    async def list_products(
        paging: PageParams = Depends(page_params), ...
    ) -> Page[AdminProductListItemOut]:
        rows, total = await repo.search(..., limit=paging.limit, offset=paging.offset)
        return build_page(rows, paging, total)

範囲外・型違いは 400 `validation_error`（`page`・`per_page` の `out_of_range`／`format`）。
`page` の上限は 32 ビット整数の範囲（桁あふれは 400。DS-DEC-124）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import Query
from pydantic import BaseModel, ConfigDict

DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100
# 4.0「桁あふれ（絶対値が 2,147,483,647 を超える整数）は 400」
INT32_MAX = 2_147_483_647


@dataclass(frozen=True, slots=True)
class PageParams:
    """検証済みのページ送りの入力。"""

    page: int
    per_page: int

    @property
    def limit(self) -> int:
        return self.per_page

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


def page_params(
    page: int = Query(default=1, ge=1, le=INT32_MAX),
    per_page: int = Query(default=DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
) -> PageParams:
    """`Depends(page_params)` で受ける。検証エラーは 400 `validation_error`。"""
    return PageParams(page=page, per_page=per_page)


class Page[T](BaseModel):
    """一覧の応答。`items` の要素の型は `Page[要素の型]` で指定する。"""

    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[T]
    page: int
    per_page: int
    total: int
    has_more: bool


def build_page[T](items: Sequence[T], params: PageParams, total: int) -> Page[T]:
    """`has_more` は `page * per_page < total`。`items` はそのページの行（切り出しは呼び出し側）"""
    return Page[T](
        items=list(items),
        page=params.page,
        per_page=params.per_page,
        total=total,
        has_more=params.page * params.per_page < total,
    )
