"""IT-060-01 内部認証／IT-061-01 health／IT-CORS-01 CORS（MySQL 必須）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.security import verify_internal_token
from tests.conftest import TEST_INTERNAL_TOKEN, TEST_ORIGIN


def _probe_router() -> APIRouter:
    """Wave 1 のルーターが無いため、内部トークン必須の最小ルーターで代替する。"""
    r = APIRouter(dependencies=[Depends(verify_internal_token)])

    @r.get("/probe")
    async def probe() -> dict:
        return {"ok": True}

    return r


async def test_it_setup_engine_is_mysql(test_database_url: str) -> None:
    """テスト設計書 1.4 #3: 接続先が MySQL であることを実接続で assert。"""
    engine = create_async_engine(test_database_url)
    try:
        assert engine.dialect.name == "mysql"
        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT VERSION()"))).scalar_one()
            assert str(version).startswith("8.")
    finally:
        await engine.dispose()


async def test_it_060_01_internal_token_missing_or_invalid_401(
    it_app: FastAPI, client_factory
) -> None:
    it_app.include_router(_probe_router(), prefix="/api/v1")
    client = client_factory(it_app)

    res = await client.get("/api/v1/probe")
    assert res.status_code == 401 and res.json() == {"code": "unauthorized"}

    res = await client.get("/api/v1/probe", headers={"X-Internal-Token": "invalid-value"})
    assert res.status_code == 401 and res.json() == {"code": "unauthorized"}

    res = await client.get("/api/v1/probe", headers={"X-Internal-Token": TEST_INTERNAL_TOKEN})
    assert res.status_code == 200 and res.json() == {"ok": True}


async def test_it_061_01_health_200_with_db_ok(it_app: FastAPI, client_factory) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/health")  # トークン無しで到達できる
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok"}


async def test_it_cors_01_preflight_from_other_origin_not_allowed(
    it_app: FastAPI, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers}
    assert res.status_code == 400  # CORSMiddleware は不許可 preflight に 400 を返す


async def test_it_cors_01_preflight_from_allowed_origin(
    it_app: FastAPI, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.options(
        "/api/v1/health",
        headers={
            "Origin": TEST_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Internal-Token",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == TEST_ORIGIN
    assert res.headers.get("access-control-allow-credentials") == "true"
    assert "x-internal-token" in res.headers.get("access-control-allow-headers", "").lower()
