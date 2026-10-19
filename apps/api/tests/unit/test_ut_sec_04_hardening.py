"""UT-SEC-04 セキュリティ強化 PR-B の api 側（S5・S7・S8・S9・S10）。DB 不要。

- S5 応答のセキュリティヘッダ
- S7 数量・variant_id の範囲（範囲外は 400。11〜99 の業務上限 422 は IT 側で確認）
- S8 `client_ip` は `X-Forwarded-For` の末尾
- S9 401・429 の拒否ログ（1 行・IP 丸め・トークン無し）
- S10 本番のメールはファイルに書かずログに注文番号だけ
S3（GET /cart でカートを作らない）は DB が要るので `tests/integration/test_it_010_013_cart.py`。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from starlette.requests import Request

from app.adapters.mail import (
    DEFAULT_OUTBOX_DIR,
    LogOnlyMailAdapter,
    OutboxMailAdapter,
    get_mail_adapter,
)
from app.core.rate_limit import SlidingWindowRateLimiter, client_ip
from app.core.reject_log import mask_ip
from tests.conftest import TEST_INTERNAL_TOKEN
from tests.unit.test_ut_adapters_and_rate_limit import _order_out

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}

EXPECTED_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "strict-transport-security": "max-age=31536000",
    "cache-control": "no-store",
}


def _request(headers: dict[str, str], client: tuple[str, int] | None = ("10.1.2.3", 5000)):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


# ── S5 セキュリティヘッダ ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path", "headers", "status"),
    [
        ("GET", "/api/v1/health", {}, 200),  # 正常系（内部トークン不要）
        ("GET", "/api/v1/cart", {}, 401),  # 認証エラー
        ("GET", "/api/v1/nope", HEADERS, 404),  # ルート不一致
        ("GET", "/api/v1/orders", HEADERS, 405),  # メソッド不一致
        ("POST", "/api/v1/cart/items", HEADERS, 400),  # 入力検証エラー
    ],
)
async def test_ut_sec_04_s5_security_headers_on_every_response(
    make_app, client_factory, method: str, path: str, headers: dict[str, str], status: int
) -> None:
    client = client_factory(make_app())
    res = await client.request(method, path, headers=headers, json={} if method == "POST" else None)
    assert res.status_code == status, res.text
    for name, value in EXPECTED_SECURITY_HEADERS.items():
        assert res.headers.get(name) == value, name


async def test_ut_sec_04_s5_headers_on_500_and_existing_header_is_kept(
    make_app, client_factory
) -> None:
    from fastapi.responses import JSONResponse

    app = make_app()

    async def boom() -> None:
        raise RuntimeError("boom")

    async def cached() -> JSONResponse:
        return JSONResponse({"ok": True}, headers={"Cache-Control": "max-age=60"})

    app.add_api_route("/_boom", boom)
    app.add_api_route("/_cached", cached)
    client = client_factory(app)

    res = await client.get("/_boom")
    assert res.status_code == 500
    for name, value in EXPECTED_SECURITY_HEADERS.items():
        assert res.headers.get(name) == value, name

    # 既に付いている Cache-Control は上書きしない。ほかのヘッダは足す
    res = await client.get("/_cached")
    assert res.headers["cache-control"] == "max-age=60"
    assert res.headers["x-content-type-options"] == "nosniff"


async def test_ut_sec_04_s5_cors_preflight_response_has_headers(make_app, client_factory) -> None:
    client = client_factory(make_app())
    res = await client.options(
        "/api/v1/cart",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"


async def test_ut_sec_04_s5_swagger_ui_is_not_blocked_by_csp_in_development(
    make_app, client_factory
) -> None:
    """開発時の /docs は CDN のスクリプトを読むので CSP を付けない（本番は /docs 自体が無い）。"""
    client = client_factory(make_app(APP_ENV="development"))
    res = await client.get("/docs")
    assert res.status_code == 200
    assert "content-security-policy" not in res.headers
    assert res.headers["x-content-type-options"] == "nosniff"


# ── S7 数量・ID の範囲 ────────────────────────────────────────────────────────


def _out_of_range(name: str) -> dict:
    return {"code": "validation_error", "fields": [{"name": name, "reason": "out_of_range"}]}


@pytest.mark.parametrize("quantity", [0, -1, 100, 10**9])
async def test_ut_sec_04_s7_quantity_out_of_range_is_400(
    make_app, client_factory, quantity: int
) -> None:
    client = client_factory(make_app())
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": 1, "quantity": quantity}, headers=HEADERS
    )
    assert res.status_code == 400, res.text
    assert res.json() == _out_of_range("quantity")
    res = await client.patch("/api/v1/cart/items/1", json={"quantity": quantity}, headers=HEADERS)
    assert res.status_code == 400, res.text
    assert res.json() == _out_of_range("quantity")


@pytest.mark.parametrize("variant_id", [0, -1, 9223372036854775808])
async def test_ut_sec_04_s7_variant_id_out_of_range_is_400(
    make_app, client_factory, variant_id: int
) -> None:
    client = client_factory(make_app())
    res = await client.post(
        "/api/v1/cart/items", json={"variant_id": variant_id, "quantity": 1}, headers=HEADERS
    )
    assert res.status_code == 400, res.text
    assert res.json() == _out_of_range("variant_id")


def test_ut_sec_04_s7_schema_accepts_boundaries() -> None:
    """境界値: 数量 1・99、variant_id 1・2^63-1 はスキーマを通る（11〜99 の 422 は業務規則側）。"""
    from app.schemas.cart import CartItemIn, CartItemPatchIn

    for q in (1, 10, 11, 99):
        assert CartItemIn(variant_id=1, quantity=q).quantity == q
        assert CartItemPatchIn(quantity=q).quantity == q
    assert CartItemIn(variant_id=9223372036854775807, quantity=1).variant_id == 9223372036854775807


# ── S8 client_ip ──────────────────────────────────────────────────────────────


def test_ut_sec_04_s8_client_ip_uses_last_forwarded_for_element() -> None:
    assert client_ip(_request({"X-Forwarded-For": "a, b"})) == "b"
    # 先頭を偽って付けられても、BFF が付けた末尾を使う
    assert (
        client_ip(_request({"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 203.0.113.7"})) == "203.0.113.7"
    )
    assert client_ip(_request({"X-Forwarded-For": "203.0.113.7"})) == "203.0.113.7"
    assert client_ip(_request({"X-Forwarded-For": " a ,  b  "})) == "b"


def test_ut_sec_04_s8_client_ip_falls_back_to_connection() -> None:
    assert client_ip(_request({})) == "10.1.2.3"
    assert client_ip(_request({"X-Forwarded-For": ""})) == "10.1.2.3"
    assert client_ip(_request({"X-Forwarded-For": "a, "})) == "10.1.2.3"
    assert client_ip(_request({}, client=None)) == "unknown"


# ── S9 拒否ログ ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ip", "masked"),
    [
        ("203.0.113.77", "203.0.113.0"),
        ("10.1.2.3", "10.1.2.0"),
        ("2001:db8:1234:5678:9abc:def0:1234:5678", "2001:db8:1234::"),
        ("::1", "::"),
        ("unknown", "unknown"),
        ("not an ip", "unknown"),
    ],
)
def test_ut_sec_04_s9_mask_ip(ip: str, masked: str) -> None:
    assert mask_ip(ip) == masked


def _security_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.security"]


async def test_ut_sec_04_s9_401_logs_one_masked_line_without_token(
    make_app, client_factory, caplog: pytest.LogCaptureFixture
) -> None:
    client = client_factory(make_app())
    wrong = "wrong-token-value-should-not-appear"
    with caplog.at_level(logging.WARNING, logger="app.security"):
        res = await client.get(
            "/api/v1/cart",
            headers={"X-Internal-Token": wrong, "X-Forwarded-For": "198.51.100.9, 203.0.113.77"},
        )
    assert res.status_code == 401
    records = _security_records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    line = records[0].getMessage()
    assert "\n" not in line
    assert json.loads(line) == {
        "event": "request_rejected",
        "path": "/api/v1/cart",
        "method": "GET",
        "status": 401,
        "code": "unauthorized",
        "ip": "203.0.113.0",  # 末尾の要素を丸めた値
    }
    assert wrong not in caplog.text and TEST_INTERNAL_TOKEN not in caplog.text
    assert "203.0.113.77" not in caplog.text


async def test_ut_sec_04_s9_401_without_token_header_is_logged_too(
    make_app, client_factory, caplog: pytest.LogCaptureFixture
) -> None:
    client = client_factory(make_app())
    with caplog.at_level(logging.WARNING, logger="app.security"):
        await client.get("/api/v1/products")
    records = _security_records(caplog)
    assert len(records) == 1
    assert json.loads(records[0].getMessage())["code"] == "unauthorized"


async def test_ut_sec_04_s9_valid_token_logs_nothing(
    make_app, client_factory, caplog: pytest.LogCaptureFixture
) -> None:
    client = client_factory(make_app())
    with caplog.at_level(logging.WARNING, logger="app.security"):
        res = await client.get("/api/v1/health")
        res2 = await client.get("/api/v1/nope", headers=HEADERS)
    assert res.status_code == 200 and res2.status_code == 404
    assert _security_records(caplog) == []


async def test_ut_sec_04_s9_429_logs_one_masked_line_without_email(
    make_app, client_factory, caplog: pytest.LogCaptureFixture
) -> None:
    app = make_app()
    app.state.lookup_rate_limiter = SlidingWindowRateLimiter(limit=1)
    assert app.state.lookup_rate_limiter.hit("203.0.113.9") is None  # 上限まで使い切る
    client = client_factory(app)
    url = "/api/v1/orders/GU-260918-ABCDEFGH/lookup"  # pragma: allowlist secret
    with caplog.at_level(logging.WARNING, logger="app.security"):
        res = await client.post(
            url,
            json={"guest_email": "someone@example.com"},
            headers={**HEADERS, "X-Forwarded-For": "203.0.113.9"},
        )
    assert res.status_code == 429
    assert res.json() == {"code": "rate_limited"}
    records = _security_records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert json.loads(records[0].getMessage()) == {
        "event": "request_rejected",
        "path": url,
        "method": "POST",
        "status": 429,
        "code": "rate_limited",
        "ip": "203.0.113.0",
    }
    assert "someone@example.com" not in caplog.text
    assert TEST_INTERNAL_TOKEN not in caplog.text


# ── S10 本番のメール ──────────────────────────────────────────────────────────


async def test_ut_sec_04_s10_production_mail_writes_no_file_and_logs_only_order_number(
    app_env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app_env(APP_ENV="production")
    adapter = get_mail_adapter()
    assert isinstance(adapter, LogOnlyMailAdapter)

    def _no_write(*_a, **_k):
        raise AssertionError("本番でファイルを書いてはいけない")

    monkeypatch.setattr(Path, "write_text", _no_write)
    monkeypatch.setattr(Path, "mkdir", _no_write)
    order = _order_out()
    outbox_file = DEFAULT_OUTBOX_DIR / f"{order.order_number}.txt"
    outbox_file.unlink(missing_ok=True)

    with caplog.at_level(logging.INFO, logger="app.adapters.mail"):
        await adapter.send_order_confirmation(order)

    assert not outbox_file.exists()
    lines = [r.getMessage() for r in caplog.records if r.name == "app.adapters.mail"]
    assert len(lines) == 1
    assert order.order_number in lines[0]
    # 注文番号だけ。宛先・氏名・住所・電話・金額は出さない
    for secret in (
        order.guest_email,
        "t***@example.com",
        order.ship_name,
        order.ship_address,
        order.ship_phone,
        order.ship_postal_code,
    ):
        assert secret not in caplog.text


@pytest.mark.parametrize("env", ["development", "test"])
def test_ut_sec_04_s10_non_production_keeps_outbox(app_env, env: str) -> None:
    app_env(APP_ENV=env)
    assert isinstance(get_mail_adapter(), OutboxMailAdapter)
