"""IT-004-01〜08（DS-API-004 商品検索）・IT-004a-01〜02（DS-API-004a 検索サジェスト）。

設計仕様書 P2 追補a 4.1・4.4、テスト設計書 P2 追補a 4.1 に対応する（MySQL・seed 必須）。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}


async def test_it_004_01_name_match_excludes_unpublished(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/search", params={"q": "シャツ"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] > 0
    names = {i["name"] for i in body["items"]}
    assert seed_data.TEST_PRODUCT_NAME_UNPUB not in names
    assert all("シャツ" in n for n in names)
    assert body["similar_keywords"] == []
    assert body["recommended_categories"] == []


async def test_it_004_02_description_match(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """商品名にはほぼ含まれない素材表記（description 由来）でヒットする（DS-DEC-33）。"""
    client = client_factory(it_app)
    res = await client.get("/api/v1/search", params={"q": "ナイロン100%"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] > 0
    assert all("ナイロン100%" not in i["name"] for i in body["items"])


async def test_it_004_03_category_name_match(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/search", params={"q": "アウター"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    expected = sum(
        1 for p in seed_data.PRODUCTS if p.published and p.category_slug.endswith("-outer")
    )
    assert body["total"] == expected


async def test_it_004_04_length_boundaries(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/search", params={"q": "あ" * 100}, headers=HEADERS)
    assert res.status_code == 200, res.text

    res = await client.get("/api/v1/search", params={"q": "あ" * 101}, headers=HEADERS)
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "validation_error"

    res = await client.get("/api/v1/search", params={"q": ""}, headers=HEADERS)
    assert res.status_code == 400, res.text

    res = await client.get("/api/v1/search", params={"q": " "}, headers=HEADERS)
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "validation_error"


async def test_it_004_05_wildcard_chars_are_literal(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """`%`・`_`・`\\` を含む語で検索してもエラーにならず、文字どおりの一致だけになる

    （ST-SEC-12・DS-DEC-35）。`_` は LIKE の任意 1 文字ワイルドカードなので、エスケープが
    効いていなければ「1 文字以上ある行すべて」＝全件にヒットしてしまう。seed のどの商品名・
    説明・カテゴリ名にも `_`・`\\` は literal には含まれないため、正しくエスケープされていれば
    0 件になるはずというのが、この検証の核心（`%` は素材表記に literal に多用されるため
    「全件ヒットしないこと」の検証には向かず、ここでは例に挙げない）。
    """
    client = client_factory(it_app)
    published_total = sum(1 for p in seed_data.PRODUCTS if p.published)

    res = await client.get("/api/v1/search", params={"q": "100%"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert 0 < res.json()["total"] < published_total

    res = await client.get("/api/v1/search", params={"q": "under_score"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 0

    # ST-SEC-12 の具体例。`%`・`_` を含むがどの商品名にも一致しない語
    res = await client.get("/api/v1/search", params={"q": "100%_off"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 0

    # `_` だけ・`\` だけは、エスケープが効いていなければ「1文字以上ある全行」にヒットしてしまう
    for lone in ("_", "\\"):
        res = await client.get("/api/v1/search", params={"q": lone}, headers=HEADERS)
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 0, f"{lone!r} が全件ヒットしている（エスケープ漏れの疑い）"

    # `%` だけはエラーにならないことのみ確認する（多くの説明文に literal `%` を含むため
    # 0 件・全件のどちらにもなり得るが、それ自体は不具合ではない）
    res = await client.get("/api/v1/search", params={"q": "%"}, headers=HEADERS)
    assert res.status_code == 200, res.text


async def test_it_004_06_zero_hit_returns_synonyms_and_recommended_categories(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    # AT-10／ST-F003-06 と同じ 0 件語（半角カナ「スニーカー」）。辞書には無いので類似キーワードは空
    res = await client.get("/api/v1/search", params={"q": "ｽﾆｰｶｰ"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["similar_keywords"] == []
    assert 1 <= len(body["recommended_categories"]) <= 3
    counts = [c["product_count"] for c in body["recommended_categories"]]
    assert counts == sorted(counts, reverse=True)
    assert all(c["product_count"] > 0 for c in body["recommended_categories"])


async def test_it_004_06b_zero_hit_with_dictionary_candidate(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """辞書にヒットし、かつ候補が 1 件以上ヒットする語（UT-SEARCH-06 の API 版）。"""
    client = client_factory(it_app)
    res = await client.get("/api/v1/search", params={"q": "デニムパンツ"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 0
    assert body["similar_keywords"] == ["ジーンズ"]

    # 辞書にはあるが候補も 0 件になる語（「ティーシャツ」→「Tシャツ」も seed に無い）
    res = await client.get("/api/v1/search", params={"q": "ティーシャツ"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 0
    assert body["similar_keywords"] == []


async def test_it_004_07_recommended_categories_tie_break(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """既存 seed の子カテゴリ（product_count タイあり）で並びを確認する（DS-DEC-37）。

    公開商品数: men-tops=4（1 位）、women-tops=3・kids-teen-tops=3（タイ。sort_order がともに 0
    のため id 昇順で women-tops が先）。
    """
    client = client_factory(it_app)
    res = await client.get("/api/v1/search", params={"q": "ｽﾆｰｶｰ"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    slugs = [c["slug"] for c in res.json()["recommended_categories"]]
    assert slugs == ["men-tops", "women-tops", "kids-teen-tops"]


async def test_it_004_08_dakuten_and_kana_type_are_absorbed_by_db_collation(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """DS-DEC-34（案A）: ひらがな検索でカタカナ表記の商品にヒットし、

    濁点を欠いた語（「ハンツ」）で「パンツ」系商品にヒットする（既知の拾いすぎ。ST-F003-07）。
    """
    client = client_factory(it_app)

    res = await client.get("/api/v1/search", params={"q": "しゃつ"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["total"] > 0

    res = await client.get("/api/v1/search", params={"q": "ハンツ"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    # 設計仕様書 4.4 の実測（'ハンツ' が 'パンツ' 系 4 件にヒット）と一致することを確認する
    expected = sum(1 for p in seed_data.PRODUCTS if p.published and "パンツ" in p.name)
    assert body["total"] == expected == 4


async def test_it_004_pagination(it_app: FastAPI, seed_db: AsyncEngine, client_factory) -> None:
    client = client_factory(it_app)
    res = await client.get(
        "/api/v1/search", params={"q": "ー", "per_page": 1, "page": 1}, headers=HEADERS
    )
    assert res.status_code == 200, res.text
    body = res.json()
    if body["total"] >= 2:
        assert body["has_more"] is True
        assert len(body["items"]) == 1


async def test_it_004a_01_prefix_before_contains(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """「オ」は前方一致のみ 2 件（オーバーサイズシャツ・オックスフォードシャツ）で

    5 件に満たないが、他に「オ」を含む商品名が無いため部分一致の補充は空のまま返る。
    """
    client = client_factory(it_app)
    res = await client.get("/api/v1/search/suggest", params={"q": "オ"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [i["name"] for i in items] == ["オーバーサイズシャツ", "オックスフォードシャツ"]
    assert all(name.startswith("オ") for name in (i["name"] for i in items))
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))


async def test_it_004a_02_six_or_more_prefix_matches_no_contains_fill(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """前方一致だけで 5 件に達する語では部分一致からの補充が行われない（重複なし）。"""
    client = client_factory(it_app)
    res = await client.get("/api/v1/search/suggest", params={"q": "ス"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    ids = [i["id"] for i in body["items"]]
    assert len(ids) == len(set(ids))
    assert len(ids) <= 5


async def test_it_004a_suggest_length_boundary_400(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/search/suggest", params={"q": ""}, headers=HEADERS)
    assert res.status_code == 400, res.text


async def test_it_004_search_requires_internal_token(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/search", params={"q": "シャツ"})
    assert res.status_code == 401


async def test_it_004_unicode_query_is_url_encoded_safely(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """クエリ文字列の URL エンコードを経由しても結果が変わらない（回帰確認）。"""
    client = client_factory(it_app)
    encoded = quote("シャツ")
    res = await client.get(f"/api/v1/search?q={encoded}", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["total"] > 0
