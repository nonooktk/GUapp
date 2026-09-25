"""UT-SEC-03 FastAPI／Starlette 内部の HTTPException も 4.5 の `{code}` 形で返す。

ST 検収（`docs/05_検収/ST実施記録_異常境界_20260924.md`）の指摘: 未定義ルートの 404 が
FastAPI 既定の `{"detail": "Not Found"}` になっていた。405・本番 `/docs` 無効化も同じ形に揃える。
"""

from __future__ import annotations

import pytest

from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}


@pytest.mark.parametrize("path", ["/api/v1/nope", "/nope", "/api/v1/products/1/nope"])
async def test_ut_sec_03_unknown_route_is_404_not_found(
    make_app, client_factory, path: str
) -> None:
    client = client_factory(make_app())
    res = await client.get(path, headers=HEADERS)
    assert res.status_code == 404
    assert res.json() == {"code": "not_found"}
    assert "detail" not in res.text


async def test_ut_sec_03_unknown_route_without_token_is_still_404(make_app, client_factory) -> None:
    """ルート不一致は依存関数（内部トークン）より先に判定される（トークン無しでも 404 の形）。"""
    client = client_factory(make_app())
    res = await client.get("/api/v1/nope")
    assert res.status_code == 404
    assert res.json() == {"code": "not_found"}


async def test_ut_sec_03_wrong_method_is_405_method_not_allowed(make_app, client_factory) -> None:
    client = client_factory(make_app())
    # POST 専用ルートに GET
    res = await client.get("/api/v1/orders", headers=HEADERS)
    assert res.status_code == 405
    assert res.json() == {"code": "method_not_allowed"}
    # Starlette が付ける Allow ヘッダは保持する
    assert "POST" in res.headers.get("allow", "")


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_ut_sec_03_production_docs_404_same_shape(
    make_app, client_factory, path: str
) -> None:
    client = client_factory(make_app(APP_ENV="production"))
    res = await client.get(path)
    assert res.status_code == 404
    assert res.json() == {"code": "not_found"}


async def test_ut_sec_03_health_still_ok(make_app, client_factory) -> None:
    """ハンドラ追加で正常系が壊れていないこと。"""
    client = client_factory(make_app())
    res = await client.get("/api/v1/health")
    assert res.status_code == 200
