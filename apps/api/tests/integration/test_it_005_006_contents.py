"""IT-005-01〜03（DS-API-005 コンテンツ一覧）・IT-006-01〜04（DS-API-006 FAQ・静的ページ）。

設計仕様書 P2 追補a 4.2・4.3、テスト設計書 P2 追補a 4.2 に対応する（MySQL・seed 必須）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import seed_data
from app.models import Content, ContentKind
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}

# ST-SEC-14／IT-005-02／IT-006-04 専用の一時データ用 slug（seed の 8 件とは別枠）
_EXPIRED_NEWS_SLUG = "news-expired-it005-02"  # pragma: allowlist secret  # gitleaks:allow
_FUTURE_STATIC_SLUG = "future-it006-04"  # pragma: allowlist secret  # gitleaks:allow


async def test_it_005_01_news_ordered_by_publish_from_desc(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/contents?kind=news&limit=5", headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    slugs = [i["slug"] for i in body["items"]]
    # news-002（7日前）は news-001（30日前）より新しいので先に来る
    assert slugs == ["news-002", "news-001"]
    assert all(i["kind"] == "news" for i in body["items"])


async def test_it_005_02_expired_publish_to_excluded(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """`publish_to` を過去にした news 行はコンテンツ一覧に含まれない（DS-PRC-005・ST-SEC-14）。"""
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(seed_db, expire_on_commit=False) as session:
        session.add(
            Content(
                kind=ContentKind.news,
                slug=_EXPIRED_NEWS_SLUG,
                title="期限切れお知らせ（テスト専用）",
                body="掲載期間外のため一覧・詳細どちらにも出てはいけない。",
                publish_from=now - timedelta(days=10),
                publish_to=now - timedelta(days=1),
                sort_order=0,
            )
        )
        await session.commit()

    client = client_factory(it_app)
    res = await client.get("/api/v1/contents?kind=news&limit=20", headers=HEADERS)
    assert res.status_code == 200, res.text
    slugs = [i["slug"] for i in res.json()["items"]]
    assert _EXPIRED_NEWS_SLUG not in slugs
    assert slugs == ["news-002", "news-001"]


async def test_it_005_03_feature_ordered_by_sort_order_asc(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/contents?kind=feature", headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [i["slug"] for i in body["items"]] == ["feature-001"]
    assert body["items"][0]["kind"] == "feature"


async def test_it_005_04_kind_out_of_enum_is_400(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/contents?kind=faq", headers=HEADERS)
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "validation_error"


async def test_it_006_01_faq_detail(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/contents/faq", headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    expected = next(c for c in seed_data.CONTENTS if c.slug == "faq")
    assert body == {
        "slug": "faq",
        "kind": "faq",
        "title": expected.title,
        "body": expected.body,
    }


async def test_it_006_02_static_pages_return_200(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    for slug in ("terms", "privacy", "tokushoho", "company"):
        res = await client.get(f"/api/v1/contents/{slug}", headers=HEADERS)
        assert res.status_code == 200, res.text
        body = res.json()
        expected = next(c for c in seed_data.CONTENTS if c.slug == slug)
        assert body["slug"] == slug
        assert body["kind"] == "static"
        assert body["title"] == expected.title
        assert body["body"] == expected.body
    # 特商法・企業情報はダミー事業者であること、演習用デモの明記があることを確認（DS-DEC-41）
    tokushoho = (await client.get("/api/v1/contents/tokushoho", headers=HEADERS)).json()
    company = (await client.get("/api/v1/contents/company", headers=HEADERS)).json()
    for body_text in (tokushoho["body"], company["body"]):
        assert "講義演習用のデモ" in body_text
        for forbidden in ("GU", "ジーユー", "ファーストリテイリング", "ユニクロ"):
            assert forbidden not in body_text


async def test_it_006_03_unknown_slug_is_404_not_found(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/contents/no-such-slug", headers=HEADERS)
    assert res.status_code == 404, res.text
    assert res.json() == {"code": "not_found"}


async def test_it_006_04_future_publish_from_is_404(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """`publish_from` を未来にした static 行は 404（存在しないのと同じコード。DS-PRC-006 手順2）。"""
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(seed_db, expire_on_commit=False) as session:
        session.add(
            Content(
                kind=ContentKind.static,
                slug=_FUTURE_STATIC_SLUG,
                title="未来公開ページ（テスト専用）",
                body="掲載期間前のため 404 になるべき。",
                publish_from=now + timedelta(days=1),
                publish_to=None,
                sort_order=0,
            )
        )
        await session.commit()

    client = client_factory(it_app)
    res = await client.get(f"/api/v1/contents/{_FUTURE_STATIC_SLUG}", headers=HEADERS)
    assert res.status_code == 404, res.text
    assert res.json() == {"code": "not_found"}


async def test_it_006_05_slug_pattern_mismatch_is_400(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    """slug が `^[a-z0-9-]{1,100}$` に一致しない（大文字）場合は 400（本編 4.5 の判定順序）。"""
    client = client_factory(it_app)
    res = await client.get("/api/v1/contents/FAQ", headers=HEADERS)
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "validation_error"
