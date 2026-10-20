"""レーン A の基盤（P2-b）の単体テスト。DB は SQLite のファイル DB または不要。

- セッション検証（DS-PRC-035・UT-SESS-01・UT-SESS-03 の検証部分）
- 名前つき回数制限（DS-DEC-84）
- メールアダプタ 5 種の追加と後処理の部品（DS-DEC-89・設計仕様書 4.10）
- 設定（`PUBLIC_WEB_BASE_URL`・`DEMO_EMAIL_DOMAINS`）
- ルーター骨格（10 本が登録され、未実装は 501）
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.adapters import mail as mail_mod
from app.adapters.mail import (
    LogOnlyMailAdapter,
    OutboxMailAdapter,
    build_public_url,
    get_mail_adapter,
    render_order_confirmation,
    safe_send,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import (
    RATE_LIMIT_SPECS,
    SlidingWindowRateLimiter,
    build_rate_limiters,
    ip_rate_limit,
)
from app.core.session import find_member_by_session_token, hash_token, is_valid_token_shape
from app.models import AuthSession, Base, Member, SubjectType
from app.schemas.order import OrderItemOut, OrderOut, OrderStoreOut
from tests.conftest import TEST_INTERNAL_TOKEN
from tests.recording_mail import RecordingMailAdapter

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}
NOW = datetime(2026, 10, 20, 12, 0, 0)
TOKEN_A = "A" * 43
TOKEN_B = "B" * 43


# ══════════════════════════════════════════════════════════════════════════
# セッション検証（DS-PRC-035）
# ══════════════════════════════════════════════════════════════════════════


def test_hash_token_is_sha256_hex_and_differs_from_input() -> None:
    h = hash_token(TOKEN_A)
    assert re.fullmatch(r"[0-9a-f]{64}", h)
    assert h != TOKEN_A and TOKEN_A not in h
    assert hash_token(TOKEN_A) == h and hash_token(TOKEN_B) != h


@pytest.mark.parametrize(
    ("token", "ok"),
    [
        ("A" * 43, True),
        ("a-_" + "Z" * 40, True),
        ("A" * 42, False),
        ("A" * 44, False),
        ("A" * 42 + "=", False),
        ("A" * 42 + " ", False),
        ("A" * 42 + "\n", False),
        ("", False),
        (None, False),
        ("あ" * 43, False),
    ],
)
def test_ut_sess_03_token_shape(token: str | None, ok: bool) -> None:
    assert is_valid_token_shape(token) is ok


@pytest.fixture
async def session_db(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _add_member(engine: AsyncEngine, member_id: int, **over: Any) -> None:
    values: dict[str, Any] = {
        "id": member_id,
        "email": f"m{member_id}@example.com",
        "password_hash": "$argon2id$dummy",
        "name": f"会員{member_id}",
        "personalize_opt_in": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(over)
    async with engine.begin() as conn:
        await conn.execute(insert(Member).values(**values))


async def _add_session(
    engine: AsyncEngine,
    token: str,
    member_id: int,
    *,
    expires_at: datetime,
    subject_type: SubjectType = SubjectType.member,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            insert(AuthSession).values(
                token_hash=hash_token(token),
                subject_type=subject_type,
                subject_id=member_id,
                expires_at=expires_at,
                last_seen_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )


async def _find(engine: AsyncEngine, token: str | None):
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine) as session:
        return await find_member_by_session_token(session, token, now=NOW)


async def test_ut_sess_01_expiry_boundary(session_db: AsyncEngine) -> None:
    """`expires_at > now` のものだけ有効。ちょうど現在・1 秒前は無効、1 秒後は有効。"""
    await _add_member(session_db, 1, email_verified_at=NOW)
    await _add_session(session_db, "1" * 43, 1, expires_at=NOW + timedelta(seconds=1))
    await _add_session(session_db, "2" * 43, 1, expires_at=NOW)
    await _add_session(session_db, "3" * 43, 1, expires_at=NOW - timedelta(seconds=1))

    ok = await _find(session_db, "1" * 43)
    assert ok is not None and ok.id == 1
    assert ok.email == "m1@example.com" and ok.name == "会員1"
    assert ok.email_verified is True and ok.personalize_opt_in is False
    assert await _find(session_db, "2" * 43) is None
    assert await _find(session_db, "3" * 43) is None
    assert await _find(session_db, "4" * 43) is None, "未知のトークン"


async def test_ut_sess_01_staff_session_is_never_a_member(session_db: AsyncEngine) -> None:
    await _add_member(session_db, 1)
    await _add_session(
        session_db,
        TOKEN_A,
        1,
        expires_at=NOW + timedelta(hours=1),
        subject_type=SubjectType.staff,
    )
    assert await _find(session_db, TOKEN_A) is None


async def test_ut_sess_01_anonymized_member_is_invalid(session_db: AsyncEngine) -> None:
    await _add_member(session_db, 1, anonymized_at=NOW - timedelta(days=1))
    await _add_session(session_db, TOKEN_A, 1, expires_at=NOW + timedelta(hours=1))
    assert await _find(session_db, TOKEN_A) is None


async def test_ut_sess_01_malformed_token_never_raises(session_db: AsyncEngine) -> None:
    for bad in (None, "", "A" * 42, "A" * 44, "A" * 42 + "="):
        assert await _find(session_db, bad) is None


async def test_unverified_member_has_email_verified_false(session_db: AsyncEngine) -> None:
    await _add_member(session_db, 3)
    await _add_session(session_db, TOKEN_A, 3, expires_at=NOW + timedelta(hours=1))
    member = await _find(session_db, TOKEN_A)
    assert (
        member is not None and member.email_verified is False and member.email_verified_at is None
    )


@pytest.fixture
async def authed_app(make_app: Callable[..., FastAPI], tmp_path: Path) -> FastAPI:
    """会員 1 の有効なセッション（TOKEN_A）が入った SQLite のファイル DB に向けた app。"""
    url = f"sqlite+aiosqlite:///{tmp_path / 'dep.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 実時間で有効なセッション（find は now 省略 = 現在時刻）
    future = datetime.now().replace(microsecond=0) + timedelta(hours=1)
    await _add_member(engine, 1)
    await _add_session(engine, TOKEN_A, 1, expires_at=future)
    await engine.dispose()
    return make_app(DATABASE_URL=url)


async def test_dependency_get_current_member_401_unless_valid(
    authed_app: FastAPI, client_factory: Callable[[FastAPI], httpx.AsyncClient]
) -> None:
    """無効・不明・形が違うセッションは 401、有効なら通る（骨格は 501）。"""
    client = client_factory(authed_app)
    res = await client.get("/api/v1/me", headers=HEADERS)
    assert res.status_code == 401 and res.json() == {"code": "unauthorized"}
    res = await client.get("/api/v1/me", headers={**HEADERS, "X-Session-Token": TOKEN_B})
    assert res.status_code == 401
    res = await client.get("/api/v1/me", headers={**HEADERS, "X-Session-Token": "short"})
    assert res.status_code == 401
    res = await client.get("/api/v1/me", headers={**HEADERS, "X-Session-Token": TOKEN_A})
    assert res.status_code == 200, "有効なセッションは通り、/me が 200 を返す"


async def test_dependency_get_optional_member_never_raises(
    authed_app: FastAPI, client_factory: Callable[[FastAPI], httpx.AsyncClient]
) -> None:
    """再入荷の申込（`get_optional_member`）は、無効なセッションでも 401 にならない。"""
    client = client_factory(authed_app)
    payload = {"variant_id": 1, "email": "a@example.com"}
    for token in (None, TOKEN_B, "short", TOKEN_A):
        headers = dict(HEADERS) if token is None else {**HEADERS, "X-Session-Token": token}
        res = await client.post("/api/v1/restock-notifications", json=payload, headers=headers)
        # セッションの有無・有効無効にかかわらず 401 にならず、サービスまで届く
        # （この DB に variant_id=1 は無いので 404。レーン C が骨格の 501 から置き換えた）
        assert res.status_code == 404, token


async def test_me_orders_query_ranges_are_400_after_authentication(
    authed_app: FastAPI, client_factory: Callable[[FastAPI], httpx.AsyncClient]
) -> None:
    """範囲外の page・per_page は 400（判定順序: 認証 401 → 形 400。本編 4.5）。"""
    client = client_factory(authed_app)
    anon = await client.get("/api/v1/me/orders", params={"page": 0}, headers=HEADERS)
    assert anon.status_code == 401, "認証が先"
    headers = {**HEADERS, "X-Session-Token": TOKEN_A}
    for params in ({"page": 0}, {"per_page": 0}, {"per_page": 51}):
        res = await client.get("/api/v1/me/orders", params=params, headers=headers)
        assert res.status_code == 400, params
        assert res.json()["code"] == "validation_error"
    res = await client.get("/api/v1/me/orders", params={"per_page": 50}, headers=headers)
    # 50 は範囲内。注文が 0 件の会員の一覧は 200（レーン C が骨格の 501 から置き換えた）
    assert res.status_code == 200, "50 は範囲内"


# ══════════════════════════════════════════════════════════════════════════
# 名前つき回数制限（DS-DEC-84）
# ══════════════════════════════════════════════════════════════════════════


def test_rate_limit_specs_match_design() -> None:
    expected = {
        "register": (10, 3600),
        "verify_email": (20, 3600),
        "password_reset_request": (5, 3600),
        "password_reset_request_email": (3, 3600),
        "password_reset_confirm": (10, 3600),
        "restock": (20, 3600),
    }
    assert {k: (v.limit, v.window_seconds) for k, v in RATE_LIMIT_SPECS.items()} == expected
    limiters = build_rate_limiters()
    assert set(limiters) == set(expected)
    assert all(isinstance(v, SlidingWindowRateLimiter) for v in limiters.values())
    # 制限器は独立（register を使い切っても他は減らない）
    for _ in range(10):
        assert limiters["register"].hit("1.2.3.4") is None
    assert limiters["register"].hit("1.2.3.4") is not None
    assert limiters["restock"].hit("1.2.3.4") is None


def test_ip_rate_limit_unknown_name_fails_at_creation() -> None:
    with pytest.raises(ValueError):
        ip_rate_limit("no-such-limiter")


async def test_register_is_limited_to_10_per_hour_per_ip(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], httpx.AsyncClient]
) -> None:
    client = client_factory(make_app())
    payload: dict[str, str] = {}  # 本文が不正（400）でも回数は数える
    for _ in range(10):
        res = await client.post(
            "/api/v1/auth/register", json=payload, headers={**HEADERS, "X-Forwarded-For": "9.9.9.9"}
        )
        assert res.status_code == 400
    res = await client.post(
        "/api/v1/auth/register", json=payload, headers={**HEADERS, "X-Forwarded-For": "9.9.9.9"}
    )
    assert res.status_code == 429 and res.json() == {"code": "rate_limited"}
    assert int(res.headers["Retry-After"]) >= 1
    # 別の IP は数えない
    res = await client.post(
        "/api/v1/auth/register", json=payload, headers={**HEADERS, "X-Forwarded-For": "8.8.8.8"}
    )
    assert res.status_code == 400


# ══════════════════════════════════════════════════════════════════════════
# メールアダプタ（DS-DEC-89・設計仕様書 4.10）
# ══════════════════════════════════════════════════════════════════════════


def order_out(**over: Any) -> OrderOut:
    values: dict[str, Any] = {
        "order_number": "GU-261020-ABCDEFGH",
        "status": "accepted",
        "items": [
            OrderItemOut(
                product_name="テスト商品",
                color="黒",
                size="M",
                unit_price=1990,
                quantity=2,
                line_total=3980,
            )
        ],
        "subtotal": 3980,
        "shipping_fee": 550,
        "total": 4530,
        "tax_included": 411,
        "tax_rate": "0.10",
        "ship_name": "テスト 太郎",
        "ship_postal_code": "1000001",
        "ship_address": "東京都千代田区千代田1-1",
        "ship_phone": "09012345678",
        "guest_email": "test@example.com",
        "receive_method": "delivery",
        "payment_method": "card",
        "ordered_at": "2026-10-20T00:00:00Z",
    }
    values.update(over)
    return OrderOut(**values)


def test_order_confirmation_delivery_text_has_no_pickup_code() -> None:
    text = render_order_confirmation(order_out())
    assert "受け取り方法: 配送" in text and "■ お届け先" in text and "〒1000001" in text
    assert "受け取りコード" not in text and "受け取り店舗" not in text


def test_order_confirmation_store_text_has_store_and_pickup_code() -> None:
    order = order_out(
        receive_method="store",
        shipping_fee=0,
        total=3980,
        ship_postal_code="0000001",
        ship_address="東京都千代田区デモ町1-2-3 デモビル1階",
        store=OrderStoreOut(
            name="デモ店 東京", prefecture="東京都", address="東京都千代田区デモ町1-2-3 デモビル1階"
        ),
        pickup_code="ABCD2345",
    )
    text = render_order_confirmation(order)
    assert "受け取り方法: 店舗受け取り" in text
    assert "デモ店 東京" in text and "東京都千代田区デモ町1-2-3 デモビル1階" in text
    assert "ABCD2345" in text and "■ 受け取りコード" in text
    assert "■ お届け先" not in text
    assert "送料: ¥0" in text


async def test_outbox_new_kinds_write_files_without_pii_in_name(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    adapter = OutboxMailAdapter(tmp_path / "outbox")
    to = "taro.yamada@example.com"
    with caplog.at_level(logging.INFO, logger="app.adapters.mail"):
        await adapter.send_email_verification(
            to, "太郎", "http://localhost:3000/verify-email?token=T"
        )
        await adapter.send_password_reset(
            to, "太郎", "http://localhost:3000/password-reset/confirm?token=R"
        )
        await adapter.send_account_locked(to, "太郎")
        await adapter.send_account_exists(to)
        await adapter.send_restock_notice(
            to, "リブレギンス", "ブラック", "M", "http://localhost:3000/products/29"
        )
    files = sorted(p.name for p in (tmp_path / "outbox").iterdir())
    kinds = [
        "account_exists",
        "account_locked",
        "email_verification",
        "password_reset",
        "restock_notice",
    ]
    assert len(files) == 5
    for kind, name in zip(kinds, files, strict=True):
        assert re.fullmatch(rf"{kind}-\d{{14}}-[0-9a-f]{{6}}\.txt", name), name
    # ファイル名にメール・トークンを入れない
    assert not [n for n in files if "@" in n or "yamada" in n or "token" in n]
    contents = {
        p.name.split("-")[0]: p.read_text(encoding="utf-8") for p in (tmp_path / "outbox").iterdir()
    }
    assert "token=T" in contents["email_verification"] and to in contents["email_verification"]
    assert "token=R" in contents["password_reset"]
    assert (
        "リブレギンス" in contents["restock_notice"]
        and "/products/29" in contents["restock_notice"]
    )
    # ログはマスク済みメールだけ（生のメール・リンクは出ない）
    assert "t***@example.com" in caplog.text
    assert to not in caplog.text and "token=" not in caplog.text


async def test_outbox_same_second_files_do_not_collide(tmp_path: Path) -> None:
    adapter = OutboxMailAdapter(tmp_path)
    for _ in range(20):
        await adapter.send_account_exists("a@example.com")
    assert len(list(tmp_path.iterdir())) == 20


async def test_log_only_adapter_writes_nothing_and_logs_kind_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    adapter = LogOnlyMailAdapter()
    with caplog.at_level(logging.INFO, logger="app.adapters.mail"):
        await adapter.send_email_verification(
            "a@example.com", "太郎", "http://x/verify?token=SECRET"
        )
        await adapter.send_password_reset("a@example.com", "太郎", "http://x/reset?token=SECRET")
        await adapter.send_account_locked("a@example.com", "太郎")
        await adapter.send_account_exists("a@example.com")
        await adapter.send_restock_notice("a@example.com", "商品", "黒", "M", "http://x/products/1")
    assert "kind=email_verification" in caplog.text and "kind=restock_notice" in caplog.text
    for secret in ("a@example.com", "SECRET", "http://", "太郎"):
        assert secret not in caplog.text
    assert not list(tmp_path.iterdir())


def test_get_mail_adapter_switches_on_production(app_env: Callable[..., None]) -> None:
    app_env(APP_ENV="production")
    assert isinstance(get_mail_adapter(), LogOnlyMailAdapter)
    app_env(APP_ENV="development")
    assert isinstance(get_mail_adapter(), OutboxMailAdapter)


async def test_safe_send_swallows_errors_and_logs_masked(caplog: pytest.LogCaptureFixture) -> None:
    mail = RecordingMailAdapter()
    mail.fail = True
    with caplog.at_level(logging.WARNING, logger="app.adapters.mail"):
        await safe_send(
            mail_mod.KIND_EMAIL_VERIFICATION,
            "taro@example.com",
            mail.send_email_verification,
            "taro@example.com",
            "太郎",
            "http://localhost:3000/verify-email?token=SECRET",
        )
    assert mail.sent == []
    assert "kind=email_verification" in caplog.text and "t***@example.com" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text and "taro@example.com" not in caplog.text

    mail.fail = False
    await safe_send(
        mail_mod.KIND_ACCOUNT_EXISTS, "a@example.com", mail.send_account_exists, "a@example.com"
    )
    assert [m.kind for m in mail.sent] == ["account_exists"]


def test_build_public_url(app_env: Callable[..., None]) -> None:
    app_env(PUBLIC_WEB_BASE_URL="http://localhost:3000")
    assert (
        build_public_url("/verify-email?token=abc")
        == "http://localhost:3000/verify-email?token=abc"
    )
    app_env(PUBLIC_WEB_BASE_URL="https://web.example.com/")
    assert build_public_url("/products/29") == "https://web.example.com/products/29"
    with pytest.raises(ValueError):
        build_public_url("products/29")


def test_build_public_url_unset_is_500(app_env: Callable[..., None]) -> None:
    app_env()  # PUBLIC_WEB_BASE_URL 未設定
    with pytest.raises(AppError) as ei:
        build_public_url("/verify-email?token=abc")
    assert ei.value.status == 500 and ei.value.code == "internal_error"


async def test_recording_mail_adapter_install_and_filter(
    make_app: Callable[..., FastAPI], recording_mail: RecordingMailAdapter
) -> None:
    app = make_app()
    recording_mail.install(app)
    mail = app.dependency_overrides[get_mail_adapter]()
    await mail.send_restock_notice("a@example.com", "商品", "黒", "M", "http://x/products/1")
    await mail.send_account_exists("b@example.com")
    sent = recording_mail.of_kind("restock_notice")
    assert len(sent) == 1 and sent[0].to == "a@example.com" and sent[0].args["size"] == "M"
    recording_mail.clear()
    assert recording_mail.sent == []


# ══════════════════════════════════════════════════════════════════════════
# 設定
# ══════════════════════════════════════════════════════════════════════════


def test_demo_email_domains_parsing(app_env: Callable[..., None]) -> None:
    app_env()
    assert get_settings().demo_email_domains == frozenset()
    app_env(DEMO_EMAIL_DOMAINS="example.com")
    assert get_settings().demo_email_domains == {"example.com"}
    app_env(DEMO_EMAIL_DOMAINS=" Example.com , example.NET ,, ")
    assert get_settings().demo_email_domains == {"example.com", "example.net"}


def test_new_settings_default_to_empty(app_env: Callable[..., None]) -> None:
    app_env()
    s = get_settings()
    assert (s.PUBLIC_WEB_BASE_URL, s.DEMO_EMAIL_DOMAINS, s.SEED_MEMBER_PASSWORD) == ("", "", "")


# ══════════════════════════════════════════════════════════════════════════
# ルーター骨格
# ══════════════════════════════════════════════════════════════════════════

SKELETON_ROUTES: list[tuple[str, str]] = [
    ("post", "/api/v1/auth/register"),
    ("post", "/api/v1/auth/verify-email"),
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/logout"),
    ("post", "/api/v1/auth/password-reset/request"),
    ("post", "/api/v1/auth/password-reset/confirm"),
    ("get", "/api/v1/me"),
    ("get", "/api/v1/me/orders"),
    ("get", "/api/v1/me/orders/{order_number}"),
    ("get", "/api/v1/stores"),
    ("post", "/api/v1/restock-notifications"),
]


def test_skeleton_routes_are_registered(make_app: Callable[..., FastAPI]) -> None:
    paths = make_app().openapi()["paths"]
    for method, path in SKELETON_ROUTES:
        assert method in paths.get(path, {}), f"{method.upper()} {path}"
    assert paths["/api/v1/auth/register"]["post"]["responses"].keys() >= {"202"}
    assert "204" in paths["/api/v1/auth/logout"]["post"]["responses"]


async def test_skeleton_endpoints_require_internal_token_and_return_501(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], httpx.AsyncClient]
) -> None:
    client = client_factory(make_app())
    assert (await client.get("/api/v1/stores")).status_code == 401, "内部トークン必須"
    res = await client.post(
        "/api/v1/restock-notifications", json={"variant_id": 1, "email": "a@example.com"}
    )
    assert res.status_code == 401, "内部トークン必須"
    res = await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x"})
    assert res.status_code == 401, "内部トークン必須"
