"""IT-ADM-01〜05: 管理 API 共通の結合テスト（既定拒否・ヘッダー・拒否ログ）。MySQL 必須。

テスト設計書 P2 追補c 4.1 / 設計仕様書 P2 追補c 4.0・7.1・DS-DEC-107・109。

管理ルートは `app.openapi()` から**実行時に列挙**する（ルートを足したときも自動で対象になる。
FastAPI の新しい版はルーターを入れ子のまま持つため、`app.routes` の直接の走査では足りない）。
管理用セッションを要しない開放ルートは、ログインとログアウトの 2 本だけ
（`routers.admin.OPEN_ADMIN_ROUTES`）。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import AppError
from app.routers.admin import OPEN_ADMIN_ROUTES
from app.seed import count_rows
from tests.conftest import TEST_INTERNAL_TOKEN
from tests.integration import admin_helpers as ah
from tests.integration import p2b_helpers as ph

ADMIN_PREFIX = "/api/v1/admin"
# パス変数に入れるサンプル値（形が違っても、認証は本文・パスの検査より前に判定される）
SAMPLE_PATH_VALUES = {
    "product_id": "1",
    "variant_id": "1",
    "order_number": "GU-260101-AAAAAAAA",
}
# 状態が変わらないことを確かめる表
WATCHED_TABLES = (
    "staff",
    "sessions",
    "audit_logs",
    "login_attempts",
    "products",
    "variants",
    "orders",
    "system_settings",
)


@pytest.fixture
def admin_app(
    make_app: Callable[..., FastAPI], test_database_url: str, migrated_schema: str
) -> FastAPI:
    return make_app(APP_ENV="test", DATABASE_URL=test_database_url)


@pytest.fixture
async def client(
    admin_app: FastAPI,
    seed_db: AsyncEngine,
    client_factory: Callable[[FastAPI], httpx.AsyncClient],
) -> httpx.AsyncClient:
    return client_factory(admin_app)


@pytest.fixture
def engine(seed_db: AsyncEngine) -> AsyncEngine:
    return seed_db


def admin_routes(app: FastAPI) -> list[tuple[str, str]]:
    """(メソッド, 変数を埋めたパス) の一覧。OpenAPI から実行時に列挙する。"""
    routes: list[tuple[str, str]] = []
    for path, item in app.openapi()["paths"].items():
        if not path.startswith(ADMIN_PREFIX):
            continue
        concrete = re.sub(r"\{(\w+)\}", lambda m: SAMPLE_PATH_VALUES[m.group(1)], path)
        for method in item:
            routes.append((method.upper(), concrete))
    return routes


def guarded_routes(app: FastAPI) -> list[tuple[str, str]]:
    """開放ルート（ログイン・ログアウト）以外の管理ルート。"""
    return [r for r in admin_routes(app) if r not in OPEN_ADMIN_ROUTES]


async def call(client: httpx.AsyncClient, method: str, path: str, headers: dict[str, str]):
    kwargs = {"json": {}} if method in {"POST", "PATCH", "PUT"} else {}
    return await client.request(method, path, headers=headers, **kwargs)


async def counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as conn:
        return await count_rows(conn, WATCHED_TABLES)


def test_route_discovery_finds_the_expected_admin_routes(admin_app: FastAPI) -> None:
    """列挙が空振りしていないことの確認（空なら IT-ADM-01〜03 は何も検査しない）。"""
    routes = set(admin_routes(admin_app))
    assert OPEN_ADMIN_ROUTES <= routes, "開放ルートの宣言と実際のルートが一致する"
    guarded = set(guarded_routes(admin_app))
    assert {
        ("GET", f"{ADMIN_PREFIX}/me"),
        ("GET", f"{ADMIN_PREFIX}/products"),
        ("GET", f"{ADMIN_PREFIX}/products/1"),
        ("PATCH", f"{ADMIN_PREFIX}/products/1"),
        ("PATCH", f"{ADMIN_PREFIX}/variants/1/stock"),
        ("GET", f"{ADMIN_PREFIX}/settings"),
        ("PATCH", f"{ADMIN_PREFIX}/settings"),
        ("GET", f"{ADMIN_PREFIX}/orders"),
        ("GET", f"{ADMIN_PREFIX}/orders/GU-260101-AAAAAAAA"),
        ("PATCH", f"{ADMIN_PREFIX}/orders/GU-260101-AAAAAAAA/status"),
    } <= guarded
    assert not (guarded & OPEN_ADMIN_ROUTES)


async def test_it_adm_01_every_guarded_route_is_401_without_a_session(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_app: FastAPI
) -> None:
    """内部トークンだけで呼ぶと、ログイン・ログアウト以外のすべての管理ルートが 401。"""
    before = await counts(engine)
    for method, path in guarded_routes(admin_app):
        res = await call(client, method, path, ah.admin_headers())
        assert res.status_code == 401, (method, path, res.status_code, res.text)
        assert res.json() == {"code": "unauthorized"}, (method, path)
    assert await counts(engine) == before


async def test_it_adm_01b_malformed_expired_and_unknown_sessions_are_401_everywhere(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_app: FastAPI
) -> None:
    staff_id = await ah.create_staff(engine, "staff-a")
    expired = await ah.make_admin_session(engine, staff_id, ttl=timedelta(seconds=-1))
    for token in ("short", "A" * 43, expired):
        for method, path in guarded_routes(admin_app):
            res = await call(client, method, path, ah.admin_headers(token))
            assert res.status_code == 401, (method, path, token, res.status_code)


async def test_it_adm_02_member_session_is_403_on_every_guarded_route(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_app: FastAPI
) -> None:
    """会員の有効なトークンを `X-Admin-Session-Token` に付けてすべて呼ぶと 403。DB は変わらない。"""
    member_token = await ph.make_session(engine, await ph.member_id_of(engine))
    before = await counts(engine)
    for method, path in guarded_routes(admin_app):
        res = await call(client, method, path, ah.admin_headers(member_token))
        assert res.status_code == 403, (method, path, res.status_code, res.text)
        assert res.json() == {"code": "forbidden"}, (method, path)
    assert await counts(engine) == before


async def test_it_adm_02b_a_valid_staff_session_passes_the_gate(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_app: FastAPI
) -> None:
    """管理者のセッションなら門を通る（骨格は 501。`/me` は 200）。C-2・C-3 が埋めるまでの状態。"""
    staff_id = await ah.create_staff(engine, "staff-a")
    token = await ah.make_admin_session(engine, staff_id)
    for method, path in guarded_routes(admin_app):
        res = await call(client, method, path, ah.admin_headers(token))
        # 注文 API（C-3）は実装済み。空の本文は 400、存在しない注文番号は 404 になる
        allowed = {200, 501} | ({400, 404} if f"{ADMIN_PREFIX}/orders" in path else set())
        # 商品・在庫・設定 API（C-2）も実装済み。PATCH の空の本文は 400
        if any(f"{ADMIN_PREFIX}{seg}" in path for seg in ("/products", "/variants", "/settings")):
            allowed |= {400}
        assert res.status_code in allowed, (method, path, res.status_code, res.text)
        if res.status_code == 501:
            assert res.json() == {"code": "not_implemented"}


async def test_it_adm_03_internal_token_is_required_on_every_admin_route(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_app: FastAPI
) -> None:
    """内部トークンなし・不一致は、ログインを含むすべての管理ルートが 401。"""
    staff_id = await ah.create_staff(engine, "staff-a")
    token = await ah.make_admin_session(engine, staff_id)
    for method, path in admin_routes(admin_app):
        for headers in (
            {},
            {"X-Internal-Token": "wrong-token"},
            {"X-Admin-Session-Token": token},
            {"X-Internal-Token": "wrong-token", "X-Admin-Session-Token": token},
        ):
            res = await call(client, method, path, headers)
            assert res.status_code == 401, (method, path, headers, res.status_code)
            assert res.json() == {"code": "unauthorized"}


async def test_it_adm_04_security_headers_on_every_status(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_app: FastAPI
) -> None:
    """200・400・401・403・404・409・422・501 のどれにも no-store と nosniff と DENY が付く。"""

    # 409・422 を起こす確認用のルート（C-2・C-3 の実ルートが入るまでの代わり。認証は掛けない）
    async def conflict() -> None:
        raise AppError(409, "stale_data", field="stock", current=1)

    async def unprocessable() -> None:
        raise AppError(422, "unsupported_value", field="stock")

    admin_app.add_api_route(f"{ADMIN_PREFIX}/_probe/409", conflict, methods=["GET"])
    admin_app.add_api_route(f"{ADMIN_PREFIX}/_probe/422", unprocessable, methods=["GET"])

    staff_id = await ah.create_staff(engine, "staff-a")
    token = await ah.make_admin_session(engine, staff_id)
    member_token = await ph.make_session(engine, await ph.member_id_of(engine))
    cases = [
        (200, "GET", f"{ADMIN_PREFIX}/me", ah.admin_headers(token)),
        (400, "POST", ah.ADMIN_LOGIN_PATH, ah.admin_headers()),
        (401, "GET", f"{ADMIN_PREFIX}/me", ah.admin_headers()),
        (403, "GET", f"{ADMIN_PREFIX}/me", ah.admin_headers(member_token)),
        (404, "GET", f"{ADMIN_PREFIX}/no-such-route", ah.admin_headers(token)),
        (409, "GET", f"{ADMIN_PREFIX}/_probe/409", ah.admin_headers(token)),
        (422, "GET", f"{ADMIN_PREFIX}/_probe/422", ah.admin_headers(token)),
        (200, "GET", f"{ADMIN_PREFIX}/products", ah.admin_headers(token)),  # 実ルート（C-2）
        (404, "GET", f"{ADMIN_PREFIX}/products/999999", ah.admin_headers(token)),
    ]
    for status, method, path, headers in cases:
        res = await call(client, method, path, headers)
        assert res.status_code == status, (path, res.status_code, res.text)
        assert res.headers["cache-control"] == "no-store", (status, path)
        assert res.headers["x-content-type-options"] == "nosniff", (status, path)
        assert res.headers["x-frame-options"] == "DENY", (status, path)


async def test_it_adm_05_rejection_log_has_no_secrets(
    client: httpx.AsyncClient, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """401・403 の拒否ログは 1 行（path・method・status・code・丸めた IP）。秘密を含まない。"""
    caplog.set_level(logging.WARNING, logger="app.security")
    await ah.create_staff(engine, "staff-secret-id")
    member_id = await ph.member_id_of(engine)
    member_token = await ph.make_session(engine, member_id)
    ip = "203.0.113.77"

    caplog.clear()
    res = await client.get(ah.ADMIN_ME_PATH, headers=ah.admin_headers("Q" * 43, ip=ip))
    assert res.status_code == 401
    res = await client.get(ah.ADMIN_ME_PATH, headers=ah.admin_headers(member_token, ip=ip))
    assert res.status_code == 403

    lines = [r.getMessage() for r in caplog.records if r.name == "app.security"]
    assert len(lines) == 2, lines
    records = [json.loads(line) for line in lines]
    assert [(r["status"], r["code"]) for r in records] == [
        (401, "unauthorized"),
        (403, "forbidden"),
    ]
    for r in records:
        assert set(r) == {"event", "path", "method", "status", "code", "ip"}
        assert r["event"] == "request_rejected" and r["method"] == "GET"
        assert r["path"] == ah.ADMIN_ME_PATH
        assert r["ip"] == "203.0.113.0", "丸めた IP"
    text = "\n".join(lines)
    for secret in (member_token, "Q" * 43, TEST_INTERNAL_TOKEN, "staff-secret-id", "demo-member1"):
        assert secret not in text
