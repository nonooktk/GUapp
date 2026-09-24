"""IT-001-01／IT-002-01／IT-002-02／IT-003-01／IT-003-02 カタログ API（MySQL・seed 必須）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import seed_data
from app.models import Product, Variant
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}


@pytest.fixture
async def client(it_app: FastAPI, seed_db: AsyncEngine, client_factory):
    return client_factory(it_app)


async def _product_id_by_name(engine: AsyncEngine, name: str) -> int:
    async with AsyncSession(engine) as session:
        return (await session.execute(select(Product.id).where(Product.name == name))).scalar_one()


def _published_count(gender: str | None = None) -> int:
    return sum(
        1 for p in seed_data.PRODUCTS if p.published and (gender is None or p.gender == gender)
    )


async def test_it_001_01_categories_hierarchy(client) -> None:
    res = await client.get("/api/v1/categories", headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    parents = body["categories"]
    assert [p["slug"] for p in parents] == ["women", "men", "kids-teen"]
    assert [p["gender"] for p in parents] == ["women", "men", "kids_teen"]
    by_slug = {p["slug"]: p for p in parents}
    # 子カテゴリは seed の定義と同じ順・同じ数
    women_children = [c.slug for c in seed_data.CATEGORIES if c.parent_slug == "women"]
    assert [c["slug"] for c in by_slug["women"]["children"]] == women_children
    # product_count は公開商品のみ（P-UNPUB は kids-teen-inner-goods に属し数えない）
    kids_inner = next(
        c for c in by_slug["kids-teen"]["children"] if c["slug"] == "kids-teen-inner-goods"
    )
    expected = sum(
        1
        for p in seed_data.PRODUCTS
        if p.published and p.category_slug == "kids-teen-inner-goods"
    )
    assert kids_inner["product_count"] == expected
    total_count = sum(c["product_count"] for p in parents for c in p["children"])
    assert total_count == _published_count()
    # 親には内部 ID を出さない
    assert "id" not in parents[0]


async def test_it_002_01_products_first_page_24_and_total(client) -> None:
    res = await client.get("/api/v1/products", params={"page": 1}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["page"] == 1 and body["per_page"] == 24
    assert body["total"] == _published_count() == 30
    assert len(body["items"]) == 24
    assert body["has_more"] is True
    names = {i["name"] for i in body["items"]}
    assert seed_data.TEST_PRODUCT_NAME_UNPUB not in names
    item = body["items"][0]
    assert set(item) == {"id", "name", "price_incl_tax", "image_path", "colors", "sold_out"}
    assert item["image_path"] and item["image_path"].startswith("products/")
    assert len(item["colors"]) == 2

    # 2 ページ目に残り 6 件（公開 30 − 24）。P-ALL0 は sold_out=true
    res2 = await client.get("/api/v1/products", params={"page": 2}, headers=HEADERS)
    body2 = res2.json()
    assert len(body2["items"]) == _published_count() - 24 == 6 and body2["has_more"] is False
    all_items = body["items"] + body2["items"]
    all0 = next(i for i in all_items if i["name"] == seed_data.TEST_PRODUCT_NAME_ALL0)
    assert all0["sold_out"] is True
    assert sum(1 for i in all_items if i["sold_out"]) == 1


async def test_it_002_01_filter_by_gender_and_category(client) -> None:
    res = await client.get("/api/v1/products", params={"gender": "women"}, headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["total"] == _published_count("women") == 10

    res = await client.get(
        "/api/v1/products", params={"category": "men-outer"}, headers=HEADERS
    )
    assert res.status_code == 200
    expected = sum(1 for p in seed_data.PRODUCTS if p.published and p.category_slug == "men-outer")
    # メンズ・アウターは MA-1／ボアフリース／ライトジャケット（AT-08 用 4,990 円）の 3 点
    assert res.json()["total"] == expected == 3

    res = await client.get("/api/v1/products", params={"gender": "unicorn"}, headers=HEADERS)
    assert res.status_code == 400
    assert res.json()["fields"] == [{"name": "gender", "reason": "format"}]


async def test_it_002_02_page_0_is_400_and_beyond_last_is_empty(client) -> None:
    res = await client.get("/api/v1/products", params={"page": 0}, headers=HEADERS)
    assert res.status_code == 400
    assert res.json() == {
        "code": "validation_error",
        "fields": [{"name": "page", "reason": "out_of_range"}],
    }

    res = await client.get("/api/v1/products", params={"page": 3}, headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == [] and body["total"] == 30 and body["has_more"] is False

    res = await client.get("/api/v1/products", params={"per_page": 49}, headers=HEADERS)
    assert res.status_code == 400


async def test_it_003_01_product_detail_variants_and_related(client, seed_db) -> None:
    # V-STOCK0 を含む商品（公開）。在庫 0 のバリエーションだけ in_stock=false
    async with AsyncSession(seed_db) as session:
        v = (
            await session.execute(select(Variant).where(Variant.sku == seed_data.TEST_SKU_STOCK0))
        ).scalar_one()
    res = await client.get(f"/api/v1/products/{v.product_id}", headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {
        "id", "name", "description", "material", "price_incl_tax",
        "images", "colors", "sizes", "variants", "related",
    }
    assert body["id"] == v.product_id
    assert len(body["variants"]) == 6
    assert body["sizes"] == list(seed_data.SIZES)
    assert len(body["colors"]) == 2
    assert len(body["images"]) == 1
    by_id = {x["variant_id"]: x for x in body["variants"]}
    assert by_id[v.id]["in_stock"] is False
    assert sum(1 for x in body["variants"] if not x["in_stock"]) == 1
    # 関連: 同カテゴリ（kids-teen-inner-goods）の公開商品は自分と P-UNPUB だけ → 0 件
    assert body["related"] == []

    # women-tops は公開 3 点 → 自分以外の 2 件
    pid = await _product_id_by_name(seed_db, seed_data.PRODUCTS[0].name)  # women-tops
    res = await client.get(f"/api/v1/products/{pid}", headers=HEADERS)
    related = res.json()["related"]
    assert len(related) == 2
    assert pid not in {r["id"] for r in related}
    assert set(related[0]) == {"id", "name", "price_incl_tax", "image_path", "sold_out"}


async def test_it_003_01_related_capped_at_4(client, seed_db) -> None:
    # seed で最多の men-tops（公開 4 点）→ 自分以外 3 件。5 点以上のカテゴリは seed に無いので
    # 上限 4 は「4 以下」であることと RELATED_LIMIT 定数で確認する
    from app.services.catalog import RELATED_LIMIT

    tops = [p for p in seed_data.PRODUCTS if p.published and p.category_slug == "men-tops"]
    assert len(tops) == 4
    pid = await _product_id_by_name(seed_db, tops[0].name)
    res = await client.get(f"/api/v1/products/{pid}", headers=HEADERS)
    related = res.json()["related"]
    assert len(related) == min(RELATED_LIMIT, len(tops) - 1) == 3
    assert RELATED_LIMIT == 4


async def test_it_003_02_unpublished_and_missing_are_404(client, seed_db) -> None:
    unpub_id = await _product_id_by_name(seed_db, seed_data.TEST_PRODUCT_NAME_UNPUB)
    res = await client.get(f"/api/v1/products/{unpub_id}", headers=HEADERS)
    assert res.status_code == 404 and res.json() == {"code": "not_found"}

    res = await client.get("/api/v1/products/999999", headers=HEADERS)
    assert res.status_code == 404 and res.json() == {"code": "not_found"}

    # 内部トークン無しは 401 が先（4.5 順序 1）
    res = await client.get(f"/api/v1/products/{unpub_id}")
    assert res.status_code == 401
