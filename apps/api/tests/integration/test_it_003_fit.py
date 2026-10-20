"""IT-003-03〜05 商品詳細のサイズ感の集計（`fit_summary`。DS-API-003・DS-PRC-003a）。

MySQL・seed 必須。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from tests.integration import order_helpers as oh

# 設計仕様書 5.8 の表（承認済みの fit ごとの件数。small, just, large）。seed の定数とは独立に書く
EXPECTED_FIT = {
    1: (2, 6, 2),
    2: (0, 5, 1),
    3: (4, 3, 0),
    4: (1, 1, 1),
    5: (0, 2, 5),
    6: (3, 0, 0),
    7: (1, 4, 0),
    8: (0, 1, 0),
}


@pytest.fixture
async def client(it_app: FastAPI, seed_db: AsyncEngine, client_factory):
    return client_factory(it_app)


async def _product_id(engine: AsyncEngine, number: int) -> int:
    name = seed_data.PRODUCTS[number - 1].name
    return int(await oh.scalar(engine, "SELECT id FROM products WHERE name = :n", n=name))


async def _fit(client: httpx.AsyncClient, product_id: int) -> dict:
    res = await client.get(f"/api/v1/products/{product_id}", headers=oh.h())
    assert res.status_code == 200, res.text
    return res.json()["fit_summary"]


async def _add_review(
    engine: AsyncEngine, product_id: int, fit: str | None, approved: bool, rating: int = 4
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO reviews (product_id, rating, body, fit, approved)"
                " VALUES (:p, :r, 'テスト', :f, :a)"
            ),
            {"p": product_id, "r": rating, "f": fit, "a": approved},
        )


async def test_it_003_03_seed_reviews_match_the_design_table(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    for number, (small, just, large) in EXPECTED_FIT.items():
        summary = await _fit(client, await _product_id(seed_db, number))
        assert summary == {
            "total": small + just + large,
            "small": small,
            "just": just,
            "large": large,
        }, f"商品 {number}"
        assert summary["total"] == summary["small"] + summary["just"] + summary["large"]
    # 商品 1 の未承認の 1 行（fit=large）は数えない（承認済みの large は 2 件のまま）
    assert (
        await oh.scalar(
            seed_db,
            "SELECT COUNT(*) FROM reviews WHERE product_id = :p AND approved = 0 AND fit='large'",
            p=await _product_id(seed_db, 1),
        )
        == 1
    )


async def test_it_003_04_products_without_reviews_still_have_all_keys(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    res = await client.get(f"/api/v1/products/{await _product_id(seed_db, 9)}", headers=oh.h())
    assert res.json()["fit_summary"] == {"total": 0, "small": 0, "just": 0, "large": 0}
    assert await _fit(client, await _product_id(seed_db, 8)) == {
        "total": 1,
        "small": 0,
        "just": 1,
        "large": 0,
    }


async def test_it_003_05_unpublished_and_missing_are_404_and_null_fit_is_not_counted(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    unpublished = await _product_id(seed_db, seed_data.TEST_PRODUCT_NUMBER_UNPUB)
    res = await client.get(f"/api/v1/products/{unpublished}", headers=oh.h())
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    res = await client.get("/api/v1/products/999999", headers=oh.h())
    assert res.status_code == 404

    nine = await _product_id(seed_db, 9)
    await _add_review(seed_db, nine, None, True)  # fit が NULL
    await _add_review(seed_db, nine, "small", False)  # 未承認
    assert await _fit(client, nine) == {"total": 0, "small": 0, "just": 0, "large": 0}
    await _add_review(seed_db, nine, "small", True)  # 対照: 承認済みの fit あり
    assert await _fit(client, nine) == {"total": 1, "small": 1, "just": 0, "large": 0}
