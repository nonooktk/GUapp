"""UT-SEARCH-01〜07: DS-PRC-004（商品検索）・DS-PRC-004a（サジェスト）の純粋関数＋軽量 DB 検証。

設計仕様書 P2 追補a 4.4「DS-PRC-004 商品検索」「DS-PRC-004a 検索サジェスト」、
テスト設計書 P2 追補a 5.1 UT-SEARCH-01〜07 に対応する。

UT-SEARCH-05 のみ、テスト設計書に倣い（`tests/unit/test_ut_014_reserve_stock.py` と同じ方式）
SQLite インメモリで repositories.search を検証する（MySQL 固有の挙動は IT-004a で担保）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, Product
from app.repositories import search as search_repo
from app.services.search import (
    EmptySearchTermError,
    RecommendedCategory,
    SearchTermTooLongError,
    build_recommended_categories,
    build_similar_keywords,
    normalize_search_term,
)

# ── UT-SEARCH-01: 空白の整理（正規化・整形のみが目的。一致判定の表記変換は対象外） ──


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("　パーカー　", "パーカー"),  # 前後の全角空白が除去される
        ("パー　カー", "パー カー"),  # 内部の全角空白は半角 1 個に整理される（削除はしない）
        ("パー  カー", "パー カー"),  # 連続する半角空白も 1 個に整理される
        ("  シャツ  ", "シャツ"),
    ],
)
def test_ut_search_01_whitespace_is_trimmed_and_collapsed(raw: str, expected: str) -> None:
    assert normalize_search_term(raw) == expected


# ── UT-SEARCH-02: 空文字・空白のみは例外 ──


@pytest.mark.parametrize("raw", ["", " ", "　", "   "])
def test_ut_search_02_blank_raises_empty_search_term_error(raw: str) -> None:
    with pytest.raises(EmptySearchTermError):
        normalize_search_term(raw)


# ── UT-SEARCH-03: 長さ境界（正規化後の文字数で判定） ──


def test_ut_search_03_length_100_passes_101_fails() -> None:
    assert len(normalize_search_term("あ" * 100)) == 100
    with pytest.raises(SearchTermTooLongError):
        normalize_search_term("あ" * 101)


def test_ut_search_03_nfkc_expansion_changes_effective_length() -> None:
    """ローマ数字（NFKC で 1 文字→4 文字に展開する互換文字）を使い、

    正規化前後で文字数が変わるケースで境界を確認する（ローマ数字8 → "VIII"）。
    raw 25 文字（正規化後 100 文字）は通過、raw 26 文字（正規化後 101 文字）はエラー。
    """
    roman_eight = "Ⅷ"  # ROMAN NUMERAL EIGHT
    assert len(normalize_search_term(roman_eight * 25)) == 100
    with pytest.raises(SearchTermTooLongError):
        normalize_search_term(roman_eight * 25 + "A")


# ── UT-SEARCH-04: LIKE ワイルドカードの自動エスケープ（DS-DEC-35） ──


def _compiled(term: str) -> str:
    condition = search_repo.build_match_condition(term)
    return str(condition.compile(compile_kwargs={"literal_binds": True}))


def test_ut_search_04_percent_is_escaped() -> None:
    sql = _compiled("50%off")
    assert "ESCAPE '/'" in sql
    assert "50/%off" in sql  # 文字どおりの % として扱われる（ワイルドカード展開されない）


def test_ut_search_04_underscore_is_escaped() -> None:
    sql = _compiled("a_b")
    assert "ESCAPE '/'" in sql
    assert "a/_b" in sql


def test_ut_search_04_condition_is_name_or_description_or_category() -> None:
    sql = _compiled("シャツ")
    assert "products.name LIKE" in sql
    assert "products.description LIKE" in sql
    assert "products.id IN" in sql  # カテゴリ名一致（product_categories 経由の IN）


# ── UT-SEARCH-05: サジェスト（前方一致優先・部分一致補充・重複除去） ──


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _add_product(session: AsyncSession, name: str, *, published: bool = True) -> int:
    p = Product(name=name, price_incl_tax=1000, published=published)
    session.add(p)
    await session.flush()
    return p.id


async def test_ut_search_05_prefix_first_then_contains_fills_up_to_5(
    session: AsyncSession,
) -> None:
    # 前方一致 3 件（「パ」始まり）
    p1 = await _add_product(session, "パーカーA")
    p2 = await _add_product(session, "パーカーB")
    p3 = await _add_product(session, "パンツC")
    # 部分一致のみ（前方一致ではない）4 件。うち p3 は前方一致にも含まれるので重複除去対象
    q1 = await _add_product(session, "スウェットパーカーD")
    q2 = await _add_product(session, "イージーパンツE")
    q3 = await _add_product(session, "ロングパーカーF")
    q4 = await _add_product(session, "ワイドパンツG")
    await session.flush()

    pairs = await search_repo.suggest_names(session, term="パ", limit=5)
    ids = [pid for pid, _ in pairs]

    assert ids[:3] == [p1, p2, p3]  # 前方一致 3 件が先頭（id 昇順）
    assert len(ids) == 5  # 部分一致から重複を除いた 2 件を補充して計 5 件
    assert len(set(ids)) == 5  # 重複が無い
    assert set(ids[3:]).issubset({q1, q2, q3, q4})


async def test_ut_search_05_prefix_alone_reaching_limit_skips_contains(
    session: AsyncSession,
) -> None:
    ids_expected = [await _add_product(session, f"パーカー{i}") for i in range(6)]
    pairs = await search_repo.suggest_names(session, term="パ", limit=5)
    ids = [pid for pid, _ in pairs]
    assert ids == ids_expected[:5]
    assert len(set(ids)) == 5


async def test_ut_search_05_unpublished_excluded(session: AsyncSession) -> None:
    await _add_product(session, "非公開パーカー", published=False)
    pairs = await search_repo.suggest_names(session, term="パ", limit=5)
    assert pairs == []


# ── UT-SEARCH-06: 類似キーワード（辞書の候補は 1 件以上ヒットするものだけ残す。DS-DEC-37） ──


async def test_ut_search_06_candidate_with_zero_hits_is_excluded() -> None:
    """辞書に候補があるが検索すると 0 件になる語 → 除外される。"""

    async def zero_hits(_: str) -> int:
        return 0

    out = await build_similar_keywords("ティーシャツ", zero_hits)
    assert out == []


async def test_ut_search_06_candidate_with_hits_is_included() -> None:
    """候補が 1 件以上ヒットする語 → 含まれる。"""

    async def one_hit(candidate: str) -> int:
        return 2 if candidate == "ジーンズ" else 0

    out = await build_similar_keywords("デニムパンツ", one_hit)
    assert out == ["ジーンズ"]


async def test_ut_search_06_unknown_term_has_no_candidates() -> None:
    async def never_called(_: str) -> int:
        raise AssertionError("辞書に無い語では呼ばれてはいけない")

    out = await build_similar_keywords("スニーカー", never_called)
    assert out == []


# ── UT-SEARCH-07: おすすめカテゴリ（product_count 降順、同数は sort_order→id 昇順） ──


def test_ut_search_07_tie_break_by_sort_order_then_id() -> None:
    rows = [
        RecommendedCategory(slug="a", name="A", parent_id=1, sort_order=2, id=10, product_count=3),
        RecommendedCategory(slug="b", name="B", parent_id=1, sort_order=0, id=20, product_count=3),
        RecommendedCategory(slug="c", name="C", parent_id=1, sort_order=0, id=5, product_count=3),
        RecommendedCategory(slug="d", name="D", parent_id=1, sort_order=1, id=1, product_count=4),
    ]
    out = build_recommended_categories(rows)
    # 1位: product_count=4 の d。2位以降は product_count=3 タイ → sort_order 昇順→id 昇順
    assert [r.slug for r in out] == ["d", "c", "b"]


def test_ut_search_07_zero_count_excluded_and_parent_excluded() -> None:
    rows = [
        RecommendedCategory(
            slug="parent", name="親", parent_id=None, sort_order=0, id=1, product_count=99
        ),
        RecommendedCategory(
            slug="zero", name="ゼロ", parent_id=1, sort_order=0, id=2, product_count=0
        ),
        RecommendedCategory(
            slug="one", name="1件", parent_id=1, sort_order=0, id=3, product_count=1
        ),
    ]
    out = build_recommended_categories(rows)
    assert [r.slug for r in out] == ["one"]


def test_ut_search_07_capped_at_3() -> None:
    rows = [
        RecommendedCategory(
            slug=f"c{i}", name=f"C{i}", parent_id=1, sort_order=i, id=i, product_count=10 - i
        )
        for i in range(5)
    ]
    out = build_recommended_categories(rows)
    assert len(out) == 3
    assert [r.slug for r in out] == ["c0", "c1", "c2"]
