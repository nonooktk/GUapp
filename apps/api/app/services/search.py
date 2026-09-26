"""商品検索（DS-API-004・004a）のサービス。

DS-PRC-004 商品検索・DS-PRC-004a 検索サジェスト（設計仕様書 P2 追補a 4.4）。

- 一致判定は DB の照合順序（`utf8mb4_0900_ai_ci`）にすべて委ねる（DS-DEC-34・案A）。
  `normalize_search_term` はここでは使わない。目的は次の 3 点だけ:
  (a) 前後・連続する空白（全角空白を含む）の整理
  (b) 長さ上限（100 文字）判定を正規化後の文字数で行うこと
  (c) 言い換え辞書（DS-DEC-37）のキー引き当てを 1 通りの表記に統一すること
- `SEARCH_SYNONYMS` は DB 照合で吸収されない「別語」の同義語だけを持つ（DS-DEC-37 訂正）。
  全角半角・ひらがなカタカナ・清濁音の違いは DB 照合が既に同一視するため辞書に入れない。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.repositories import products as products_repo
from app.repositories import search as search_repo
from app.schemas.catalog import ProductListItemOut
from app.schemas.search import (
    RecommendedCategoryOut,
    SearchResponse,
    SuggestItemOut,
    SuggestResponse,
)

SEARCH_MIN_LENGTH = 1
SEARCH_MAX_LENGTH = 100

# サジェストの最大件数（DS-API-004a）
SUGGEST_LIMIT = 5
# 類似キーワードの最大件数（DS-PRC-004 手順5.1）
SIMILAR_KEYWORDS_LIMIT = 5
# おすすめカテゴリの最大件数（DS-PRC-004 手順5.2）
RECOMMENDED_CATEGORIES_LIMIT = 3

_WHITESPACE_RE = re.compile(r"\s+")


class SearchTermError(ValueError):
    """検索語の検証エラー（呼び出し側で 400 validation_error に変換する）。"""


class EmptySearchTermError(SearchTermError):
    """strip・正規化後に空文字になった（DS-PRC-004 手順1・2）。"""


class SearchTermTooLongError(SearchTermError):
    """正規化後の長さが SEARCH_MAX_LENGTH を超えた（DS-PRC-004 手順2(b)）。"""


def normalize_search_term(raw: str) -> str:
    """DS-PRC-004 手順1〜2。strip → 空文字チェック → NFKC 正規化 → 空白整理 → 再チェック。

    一致判定のための表記統一（全角半角・かな種別）はしない（DS-DEC-34）。
    """
    term = raw.strip()
    if term == "":
        raise EmptySearchTermError("検索語が空です")

    term = unicodedata.normalize("NFKC", term)
    term = _WHITESPACE_RE.sub(" ", term).strip()
    if term == "":
        raise EmptySearchTermError("正規化後に検索語が空になりました")
    if len(term) > SEARCH_MAX_LENGTH:
        raise SearchTermTooLongError(f"検索語は{SEARCH_MAX_LENGTH}文字以内にしてください")
    return term


# DS-DEC-37: DB 照合（全角半角・ひらがなカタカナ・清濁音の同一視）では吸収されない「別語」の
# 同義語のみを持つ。ローカル MySQL 8.4・utf8mb4_0900_ai_ci で実際に比較し、
# 別語であること（同一視されないこと）を確認済み（'デニムパンツ'≠'ジーンズ'、'デニム'≠'ジーンズ'、
# 'Tシャツ'≠'ティーシャツ'）。
SEARCH_SYNONYMS: dict[str, tuple[str, ...]] = {
    "デニムパンツ": ("ジーンズ",),
    "デニム": ("ジーンズ",),
    "ジーンズ": ("デニム",),
    "ティーシャツ": ("Tシャツ",),
    "Tシャツ": ("ティーシャツ",),
}


async def build_similar_keywords(term: str, count_fn: Callable[[str], Awaitable[int]]) -> list[str]:
    """DS-PRC-004 手順5.1。辞書の候補のうち、実際に 1 件以上ヒットするものだけを残す。

    `count_fn` は候補語で検索したときのヒット件数を返す非同期関数（DB 依存を外に出す）。
    """
    candidates = SEARCH_SYNONYMS.get(term, ())
    out: list[str] = []
    for candidate in candidates:
        if len(out) >= SIMILAR_KEYWORDS_LIMIT:
            break
        if await count_fn(candidate) > 0:
            out.append(candidate)
    return out


@dataclass(frozen=True)
class RecommendedCategory:
    """おすすめカテゴリ 1 件（`recommended_categories` の組み立て入力）。"""

    slug: str
    name: str
    parent_id: int | None
    sort_order: int
    id: int
    product_count: int


def build_recommended_categories(
    rows: Sequence[RecommendedCategory], *, limit: int = RECOMMENDED_CATEGORIES_LIMIT
) -> list[RecommendedCategory]:
    """DS-PRC-004 手順5.2・DS-DEC-37。子カテゴリを product_count 降順、

    同数は `sort_order` 昇順→`id` 昇順で並べ、0 件を除いた上位 `limit` 件を返す。
    """
    children = [r for r in rows if r.parent_id is not None and r.product_count > 0]
    ordered = sorted(children, key=lambda r: (-r.product_count, r.sort_order, r.id))
    return ordered[:limit]


def _validate_query(q: str) -> str:
    """`normalize_search_term` の例外を DS-API-004/004a の 400 validation_error に変換する。"""
    try:
        return normalize_search_term(q)
    except SearchTermError as exc:
        raise AppError(400, "validation_error", fields=[{"name": "q", "reason": "format"}]) from exc


async def search_products(
    session: AsyncSession, *, q: str, page: int, per_page: int
) -> SearchResponse:
    """DS-API-004・DS-PRC-004。0 件のときだけ類似キーワード・おすすめカテゴリを添える。"""
    term = _validate_query(q)

    summaries, total = await search_repo.search_published(
        session, term=term, page=page, per_page=per_page
    )
    colors = await products_repo.colors_by_product(session, [s.id for s in summaries])
    items = [
        ProductListItemOut(
            id=s.id,
            name=s.name,
            price_incl_tax=s.price_incl_tax,
            image_path=s.image_path,
            colors=colors.get(s.id, []),
            sold_out=s.sold_out,
        )
        for s in summaries
    ]

    similar_keywords: list[str] = []
    recommended_categories: list[RecommendedCategoryOut] = []
    if total == 0:

        async def _count(candidate: str) -> int:
            return await search_repo.count_matches(session, candidate)

        similar_keywords = await build_similar_keywords(term, _count)

        category_rows = await products_repo.list_categories_with_counts(session)
        recommended = build_recommended_categories(
            [
                RecommendedCategory(
                    slug=r.slug,
                    name=r.name,
                    parent_id=r.parent_id,
                    sort_order=r.sort_order,
                    id=r.id,
                    product_count=r.product_count,
                )
                for r in category_rows
            ]
        )
        recommended_categories = [
            RecommendedCategoryOut(slug=r.slug, name=r.name, product_count=r.product_count)
            for r in recommended
        ]

    return SearchResponse(
        query=term,
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        has_more=page * per_page < total,
        similar_keywords=similar_keywords,
        recommended_categories=recommended_categories,
    )


async def suggest_products(session: AsyncSession, *, q: str) -> SuggestResponse:
    """DS-API-004a・DS-PRC-004a。"""
    term = _validate_query(q)
    pairs = await search_repo.suggest_names(session, term=term, limit=SUGGEST_LIMIT)
    return SuggestResponse(items=[SuggestItemOut(id=pid, name=name) for pid, name in pairs])
