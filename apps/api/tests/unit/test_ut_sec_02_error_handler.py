"""UT-SEC-02 例外ハンドラ（500 は固定文言・詳細はログのみ）と 4.5 のエラー規則。"""

from __future__ import annotations

import logging
from typing import Annotated

import pytest
from fastapi import APIRouter, Body, Depends, FastAPI, Query
from pydantic import BaseModel, EmailStr, Field

from app.core.errors import INTERNAL_ERROR_BODY, AppError, map_reason
from app.core.security import verify_internal_token

SECRET_MSG = "boom: mysql+asyncmy://user:pw@127.0.0.1/guapp Traceback secret-detail"  # pragma: allowlist secret  # noqa: E501


class OrderIn(BaseModel):
    ship_name: str = Field(min_length=1, max_length=50)
    ship_postal_code: str = Field(pattern=r"^\d{7}$")
    guest_email: EmailStr
    quantity: int = Field(ge=1)


def _test_router() -> APIRouter:
    r = APIRouter()

    @r.get("/boom")
    async def boom() -> dict:
        raise RuntimeError(SECRET_MSG)

    @r.post("/orders")
    async def orders(body: OrderIn) -> dict:
        return {"ok": True}

    @r.get("/items")
    async def items(page: Annotated[int, Query(ge=1)] = 1) -> dict:
        return {"page": page}

    @r.post("/stock")
    async def stock(ids: Annotated[list[int], Body()]) -> dict:
        raise AppError(409, "out_of_stock", items=ids)

    @r.get("/limit")
    async def limit() -> dict:
        raise AppError(422, "limit_exceeded", field="quantity", limit=10)

    return r


@pytest.fixture
def test_app(make_app) -> FastAPI:
    app = make_app()
    # テスト用ルーターは内部トークン依存なしで直接付ける（エラー変換の検証が目的）
    app.include_router(_test_router(), prefix="/t")
    return app


@pytest.fixture
def token_headers() -> dict[str, str]:
    from tests.conftest import TEST_INTERNAL_TOKEN

    return {"X-Internal-Token": TEST_INTERNAL_TOKEN}


async def test_ut_sec_02_unhandled_exception_returns_fixed_500(
    test_app: FastAPI, client_factory, caplog: pytest.LogCaptureFixture
) -> None:
    client = client_factory(test_app)
    with caplog.at_level(logging.ERROR):
        res = await client.get("/t/boom")
    assert res.status_code == 500
    assert res.json() == INTERNAL_ERROR_BODY
    body_text = res.text
    assert "Traceback" not in body_text
    assert "secret-detail" not in body_text
    assert "mysql+asyncmy" not in body_text
    assert "RuntimeError" not in body_text
    # ログには詳細（例外種別とスタックトレース）が残る
    assert any(
        "RuntimeError" in (r.exc_text or "") or "未捕捉例外" in r.getMessage()
        for r in caplog.records
    )


async def test_ut_sec_02_unhandled_exception_log_masks_connection_string(
    test_app: FastAPI, client_factory, caplog: pytest.LogCaptureFixture
) -> None:
    """ログ側でも接続文字列のパスワードはマスクされる（UT-SEC-01 と 02 の接点）。"""
    from app.core.logging import SecretMaskFilter

    mask = SecretMaskFilter()
    client = client_factory(test_app)
    with caplog.at_level(logging.ERROR):
        await client.get("/t/boom")
    joined = "\n".join(mask.mask(r.exc_text or r.getMessage()) for r in caplog.records)
    assert "user:pw@" not in joined


async def test_ut_sec_02_validation_required_format_too_long_out_of_range(
    test_app: FastAPI, client_factory
) -> None:
    client = client_factory(test_app)
    res = await client.post(
        "/t/orders",
        json={
            # ship_name 欠落 → required
            "ship_postal_code": "12-3456",  # 形式不正 → format
            "guest_email": "not-an-email",  # 形式不正 → format
            "quantity": 0,  # 範囲外 → out_of_range
        },
    )
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["code"] == "validation_error"
    fields = {f["name"]: f["reason"] for f in body["fields"]}
    assert fields == {
        "ship_name": "required",
        "ship_postal_code": "format",
        "guest_email": "format",
        "quantity": "out_of_range",
    }


async def test_ut_sec_02_validation_too_long(test_app: FastAPI, client_factory) -> None:
    client = client_factory(test_app)
    res = await client.post(
        "/t/orders",
        json={
            "ship_name": "あ" * 51,
            "ship_postal_code": "1234567",
            "guest_email": "test@example.com",
            "quantity": 1,
        },
    )
    assert res.status_code == 400
    assert res.json() == {
        "code": "validation_error",
        "fields": [{"name": "ship_name", "reason": "too_long"}],
    }


async def test_ut_sec_02_validation_type_mismatch_is_format(
    test_app: FastAPI, client_factory
) -> None:
    client = client_factory(test_app)
    res = await client.get("/t/items", params={"page": "abc"})
    assert res.status_code == 400
    assert res.json() == {
        "code": "validation_error",
        "fields": [{"name": "page", "reason": "format"}],
    }
    res2 = await client.get("/t/items", params={"page": "0"})
    assert res2.json()["fields"] == [{"name": "page", "reason": "out_of_range"}]


async def test_ut_sec_02_app_error_409_with_detail(test_app: FastAPI, client_factory) -> None:
    client = client_factory(test_app)
    res = await client.post("/t/stock", json=[1, 2])
    assert res.status_code == 409
    assert res.json() == {"code": "out_of_stock", "items": [1, 2]}


async def test_ut_sec_02_app_error_422_shape(test_app: FastAPI, client_factory) -> None:
    client = client_factory(test_app)
    res = await client.get("/t/limit")
    assert res.status_code == 422
    assert res.json() == {"code": "limit_exceeded", "field": "quantity", "limit": 10}


def test_ut_sec_02_app_error_to_body_direct() -> None:
    err = AppError(409, "out_of_stock", items=[1])
    assert err.to_body() == {"code": "out_of_stock", "items": [1]}
    assert AppError(401, "unauthorized").to_body() == {"code": "unauthorized"}
    # detail は code の後ろに並ぶ（順序固定）
    assert list(AppError(422, "limit_exceeded", field="q", limit=10).to_body()) == [
        "code",
        "field",
        "limit",
    ]


@pytest.mark.parametrize(
    ("ptype", "reason"),
    [
        ("missing", "required"),
        ("string_too_long", "too_long"),
        ("too_long", "too_long"),
        ("greater_than_equal", "out_of_range"),
        ("less_than", "out_of_range"),
        ("string_too_short", "out_of_range"),
        ("string_pattern_mismatch", "format"),
        ("int_parsing", "format"),
        ("value_error", "format"),
        ("enum", "format"),
    ],
)
def test_ut_sec_02_map_reason(ptype: str, reason: str) -> None:
    assert map_reason(ptype) == reason


# ── 内部トークン ─────────────────────────────────────────────────────────────


def _protected_router() -> APIRouter:
    r = APIRouter(dependencies=[Depends(verify_internal_token)])

    @r.get("/secure")
    async def secure() -> dict:
        return {"ok": True}

    return r


async def test_ut_sec_02_internal_token_missing_and_mismatch_401(
    make_app, client_factory, token_headers
) -> None:
    app = make_app()
    app.include_router(_protected_router(), prefix="/api/v1")
    client = client_factory(app)

    res = await client.get("/api/v1/secure")
    assert res.status_code == 401 and res.json() == {"code": "unauthorized"}

    res = await client.get("/api/v1/secure", headers={"X-Internal-Token": "wrong"})
    assert res.status_code == 401 and res.json() == {"code": "unauthorized"}

    res = await client.get("/api/v1/secure", headers=token_headers)
    assert res.status_code == 200 and res.json() == {"ok": True}


async def test_ut_sec_02_internal_token_unset_rejects_everything(make_app, client_factory) -> None:
    """INTERNAL_TOKEN が未設定なら、空文字ヘッダでも素通しにならない。"""
    app = make_app(INTERNAL_TOKEN="")
    app.include_router(_protected_router(), prefix="/api/v1")
    client = client_factory(app)
    res = await client.get("/api/v1/secure", headers={"X-Internal-Token": ""})
    assert res.status_code == 401


async def test_ut_sec_02_health_exempt_from_internal_token(make_app, client_factory) -> None:
    app = make_app()  # SQLite インメモリなので DB ok
    client = client_factory(app)
    res = await client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok"}


async def test_ut_sec_02_health_db_unavailable_503(make_app, client_factory) -> None:
    app = make_app(DATABASE_URL="sqlite+aiosqlite:///Z:/nonexistent_dir/guapp_nope.db")
    client = client_factory(app)
    res = await client.get("/api/v1/health")
    assert res.status_code == 503
    assert res.json() == {"code": "db_unavailable"}
