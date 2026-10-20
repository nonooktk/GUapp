"""IT-030〜036: 認証 API（DS-API-030〜036）の結合テスト。MySQL 必須（テスト設計書 P2 追補b 4.1）。

- 登録（030）／メール確認（031）／ログイン（032）／ログアウト（033）／再設定の要求（034）・
  確定（035）／会員情報（036）
- 同時実行（IT-030-08・032-13・035-06）は MySQL・`alembic upgrade head`・プール 20 以上で行い、
  同時に処理中の件数の最大値が 2 以上であることを assert する（テスト設計書 1.4 #1〜#5）。
  認証系は `/_test/metrics`（注文の引当専用）を使えないため、サービス関数を包んで数える
- メールは記録用アダプタ（`tests/recording_mail.py`）で読む。期限・ロックの時刻は DB の時刻列を
  書き換えて境界を作る（待たない）
- パスワードはすべてテスト用のダミー値（実在の資格情報ではない）
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from app.adapters.mail import (
    KIND_ACCOUNT_EXISTS,
    KIND_ACCOUNT_LOCKED,
    KIND_EMAIL_VERIFICATION,
    KIND_PASSWORD_RESET,
)
from app.core import passwords
from app.core.session import hash_token
from app.repositories import members as members_repo
from app.repositories import sessions as sessions_repo
from app.services import auth as auth_service
from app.services.password_policy import BANNED_PASSWORDS
from tests.conftest import TEST_INTERNAL_TOKEN
from tests.recording_mail import RecordingMailAdapter

BASE_URL = "http://localhost:3000"
HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}
SEED_PW = seed_data.DEMO_MEMBER_PASSWORD
GOOD_PW = "Fresh-Pass-Phrase-77"  # pragma: allowlist secret
NEW_PW = "Another-Phrase-88"  # pragma: allowlist secret
WRONG_PW = "Wrong-Phrase-00"  # pragma: allowlist secret
MEMBER1 = "demo-member1@example.com"
MEMBER2 = "demo-member2@example.com"
MEMBER3 = "demo-member3@example.com"  # メール未確認
MEMBER4 = "demo-member4@example.com"
PREFIX = "$argon2id$v=19$m=19456,t=2,p=1$"


# ── フィクスチャ・ヘルパー ───────────────────────────────────────────────────


@pytest.fixture
def auth_app(
    make_app: Callable[..., FastAPI],
    test_database_url: str,
    migrated_schema: str,
    recording_mail: RecordingMailAdapter,
) -> FastAPI:
    app = make_app(APP_ENV="test", DATABASE_URL=test_database_url, PUBLIC_WEB_BASE_URL=BASE_URL)
    recording_mail.install(app)
    return app


@pytest.fixture
async def client(
    auth_app: FastAPI,
    seed_db: AsyncEngine,
    client_factory: Callable[[FastAPI], httpx.AsyncClient],
) -> httpx.AsyncClient:
    return client_factory(auth_app)


@pytest.fixture
def engine(seed_db: AsyncEngine) -> AsyncEngine:
    return seed_db


def hdr(ip: str = "203.0.113.10", token: str | None = None, **extra: str) -> dict[str, str]:
    headers = {**HEADERS, "X-Forwarded-For": ip, **extra}
    if token is not None:
        headers["X-Session-Token"] = token
    return headers


async def sql(engine: AsyncEngine, statement: str, **params: Any) -> list[Any]:
    """SELECT は行のリスト、それ以外は空リスト（書き込みは COMMIT する）。"""
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return list(result.all()) if result.returns_rows else []


async def scalar(engine: AsyncEngine, statement: str, **params: Any) -> Any:
    rows = await sql(engine, statement, **params)
    return rows[0][0]


def register_body(email: str, password: str = GOOD_PW, **over: Any) -> dict[str, Any]:
    return {"email": email, "password": password, "name": "テスト 太郎", **over}


async def register(
    client: httpx.AsyncClient,
    email: str,
    password: str = GOOD_PW,
    *,
    ip: str = "203.0.113.10",
    **over: Any,
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/register", json=register_body(email, password, **over), headers=hdr(ip)
    )


async def login(
    client: httpx.AsyncClient,
    email: str,
    password: str = SEED_PW,
    *,
    ip: str = "203.0.113.10",
    token: str | None = None,
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers=hdr(ip, token),
    )


async def login_ok(client: httpx.AsyncClient, email: str = MEMBER1, **kw: Any) -> str:
    res = await login(client, email, **kw)
    assert res.status_code == 200, res.text
    return res.json()["session_token"]


async def me(client: httpx.AsyncClient, token: str | None) -> httpx.Response:
    return await client.get("/api/v1/me", headers=hdr(token=token))


def token_of(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def mails(recording_mail: RecordingMailAdapter, kind: str) -> list[Any]:
    return recording_mail.of_kind(kind)


class Inflight:
    """同時に処理中の件数の最大値（テスト設計書 1.4 #2 の「同時性の証明」）。"""

    def __init__(self) -> None:
        self.now = 0
        self.max = 0


def track_inflight(
    monkeypatch: pytest.MonkeyPatch, module: Any, name: str, hold: float = 0.0
) -> Inflight:
    """`module.name`（async 関数）を包んで同時処理中の件数を数え、`hold` 秒だけ窓を広げる。"""
    original = getattr(module, name)
    counter = Inflight()

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        counter.now += 1
        counter.max = max(counter.max, counter.now)
        try:
            result = await original(*args, **kwargs)
            if hold:
                await asyncio.sleep(hold)
            return result
        finally:
            counter.now -= 1

    monkeypatch.setattr(module, name, wrapped)
    return counter


# ══════════════════════════════════════════════════════════════════════════
# IT-030 会員登録
# ══════════════════════════════════════════════════════════════════════════


async def test_it_030_01_register_creates_member_token_mail_and_audit(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    res = await register(client, "new@example.com", birth_date="1990-05-01", gender="female")
    assert res.status_code == 202 and res.json() == {"status": "accepted"}
    assert "set-cookie" not in res.headers, "自動ログインしない（DS-DEC-76）"

    row = (
        await sql(
            engine,
            "SELECT password_hash, email_verified_at, name FROM members "
            "WHERE email='new@example.com'",
        )
    )[0]
    assert row.password_hash.startswith(PREFIX) and row.email_verified_at is None
    assert row.name == "テスト 太郎"
    tokens = await sql(
        engine,
        "SELECT purpose, token_hash, used_at FROM email_tokens "
        "WHERE member_id=(SELECT id FROM members WHERE email='new@example.com')",
    )
    assert len(tokens) == 1 and tokens[0].purpose == "verify_email" and tokens[0].used_at is None

    sent = mails(recording_mail, KIND_EMAIL_VERIFICATION)
    assert len(sent) == 1 and sent[0].to == "new@example.com"
    link = sent[0].args["link"]
    assert link.startswith(f"{BASE_URL}/verify-email?token=")
    assert tokens[0].token_hash == hash_token(token_of(link)), "DB には SHA-256 だけ"
    assert token_of(link) not in str(tokens[0])

    audit = await sql(
        engine,
        "SELECT actor_type, action, target_type, detail FROM audit_logs "
        "WHERE action='member.register'",
    )
    assert len(audit) == 1 and audit[0].actor_type == "member"
    assert "new@example.com" not in str(audit[0]), "監査ログにメールを書かない"


async def test_it_030_02_existing_email_gives_identical_202_and_account_exists_mail(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    first = await register(client, "dup@example.com")
    members_before = await scalar(engine, "SELECT COUNT(*) FROM members")
    tokens_before = await scalar(engine, "SELECT COUNT(*) FROM email_tokens")
    recording_mail.clear()

    second = await register(client, "dup@example.com", NEW_PW, name="別人")
    assert second.status_code == first.status_code == 202
    assert second.content == first.content, "本文が一字一句同じ（DS-DEC-71）"
    assert await scalar(engine, "SELECT COUNT(*) FROM members") == members_before
    assert await scalar(engine, "SELECT COUNT(*) FROM email_tokens") == tokens_before
    assert (
        await scalar(engine, "SELECT name FROM members WHERE email='dup@example.com'")
        == "テスト 太郎"
    )
    assert len(mails(recording_mail, KIND_ACCOUNT_EXISTS)) == 1
    assert mails(recording_mail, KIND_ACCOUNT_EXISTS)[0].to == "dup@example.com"
    assert not mails(recording_mail, KIND_EMAIL_VERIFICATION)
    # 同じメールの別表記（全角・大文字）も既登録
    third = await register(client, "ＤＵＰ@Example.COM")
    assert third.status_code == 202 and third.content == first.content
    assert await scalar(engine, "SELECT COUNT(*) FROM members") == members_before


@pytest.mark.parametrize(
    ("override", "field", "reason"),
    [
        ({"email": "abc"}, "email", "format"),
        ({"email": "a@"}, "email", "format"),
        ({"email": ""}, "email", "required"),
        ({"password": ""}, "password", "required"),
        ({"name": ""}, "name", "required"),
        ({"name": "　　"}, "name", "required"),
        ({"name": "あ" * 51}, "name", "too_long"),
        ({"birth_date": "2999-01-01"}, "birth_date", "out_of_range"),
        ({"birth_date": "1899-12-31"}, "birth_date", "out_of_range"),
        ({"birth_date": "2000-13-01"}, "birth_date", "format"),
        ({"gender": "unknown"}, "gender", "format"),
    ],
)
async def test_it_030_03_validation_errors_have_field_and_reason(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    override: dict[str, Any],
    field: str,
    reason: str,
) -> None:
    body = register_body("valid@example.com")
    body.update(override)
    res = await client.post("/api/v1/auth/register", json=body, headers=hdr())
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "validation_error"
    assert {"name": field, "reason": reason} in res.json()["fields"]
    assert await scalar(engine, "SELECT COUNT(*) FROM members WHERE email='valid@example.com'") == 0


async def test_it_030_03_missing_required_fields_are_400(client: httpx.AsyncClient) -> None:
    res = await client.post("/api/v1/auth/register", json={}, headers=hdr())
    assert res.status_code == 400
    assert {f["name"] for f in res.json()["fields"]} == {"email", "password", "name"}


@pytest.mark.parametrize(
    ("length", "emoji", "status"),
    [
        (7, False, 400),
        (8, False, 202),
        (128, False, 202),
        (129, False, 400),
        (8, True, 202),
        (7, True, 400),
    ],
)
async def test_it_030_04_password_length_boundaries_by_codepoints(
    client: httpx.AsyncClient, length: int, emoji: bool, status: int
) -> None:
    password = "😀" * (length - 1) + "x" if emoji else "Ab1" * (length // 3) + "Z" * (length % 3)
    assert len(password) == length
    res = await register(client, "len@example.com", password)
    assert res.status_code == status, res.text
    if status == 400:
        assert res.json()["fields"][0]["name"] == "password"


@pytest.mark.parametrize("password", sorted(BANNED_PASSWORDS))
async def test_it_030_05_banned_passwords_are_422_weak_password(
    client: httpx.AsyncClient, engine: AsyncEngine, password: str
) -> None:
    res = await register(
        client, "weak@example.com", password.upper() if password.isascii() else password
    )
    assert res.status_code == 422, res.text
    assert res.json() == {"code": "weak_password", "field": "password"}
    assert await scalar(engine, "SELECT COUNT(*) FROM members") == len(seed_data.MEMBERS)


async def test_it_030_05_email_equal_and_repeated_passwords_are_422(
    client: httpx.AsyncClient,
) -> None:
    for password in (
        "weak@example.com",
        "WEAK@EXAMPLE.COM",
        "ｗｅａｋ＠ｅｘａｍｐｌｅ．ｃｏｍ",
        "aaaaaaaa",
        "ああああああああ",
    ):
        res = await register(client, "weak@example.com", password)
        assert (res.status_code, res.json()) == (
            422,
            {"code": "weak_password", "field": "password"},
        ), password


async def test_it_030_05_weak_password_check_does_not_depend_on_existing_email(
    client: httpx.AsyncClient,
) -> None:
    for password in ("password123", "aaaaaaaa"):
        new = await register(client, "fresh@example.com", password)
        existing = await register(client, MEMBER1, password)
        assert new.status_code == existing.status_code == 422
        assert new.content == existing.content


async def test_it_030_06_fullwidth_spaces_case_and_password_normalization(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    res = await register(client, "　ＤＥＭＯ＠ＥＸＡＭＰＬＥ．ＣＯＭ　")
    assert res.status_code == 202
    assert (
        await scalar(engine, "SELECT email FROM members WHERE email='demo@example.com'")
        == "demo@example.com"
    )

    res = await register(client, "Upper.Case@Example.COM")
    assert res.status_code == 202
    assert (
        await scalar(
            engine, "SELECT COUNT(*) FROM members WHERE BINARY email='upper.case@example.com'"
        )
        == 1
    )

    res = await register(client, "zero​width@example.com")
    assert res.status_code == 400 and res.json()["fields"] == [
        {"name": "email", "reason": "format"}
    ]

    # 全角英数のパスワードで登録し、半角の同じ文字列でログインできる
    assert (await register(client, "wide@example.com", "ＦｒｅｓｈＰａｓｓ９９")).status_code == 202
    assert (await login(client, "wide@example.com", "FreshPass99")).status_code == 200
    assert (
        await login(client, "wide@example.com", "ＦｒｅｓｈＰａｓｓ９９", ip="203.0.113.11")
    ).status_code == 200


async def test_it_030_07_extra_fields_are_ignored(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    res = await register(
        client,
        "mass@example.com",
        id=9999,
        role="admin",
        is_admin=True,
        email_verified_at="2026-01-01T00:00:00",
        anonymized_at="2026-01-01T00:00:00",
        locked_until="2999-01-01T00:00:00",
    )
    assert res.status_code == 202
    row = (
        await sql(
            engine,
            "SELECT id, email_verified_at, anonymized_at, locked_until FROM members "
            "WHERE email='mass@example.com'",
        )
    )[0]
    assert row.id != 9999
    assert row.email_verified_at is None and row.anonymized_at is None and row.locked_until is None


async def test_it_030_08_same_email_10_parallel_registrations_make_one_member(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    recording_mail: RecordingMailAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INSERT members から COMMIT までの窓を 40ms 広げ、2 本以上が同時に INSERT に入ることを数える
    inflight = track_inflight(monkeypatch, members_repo, "insert_member", hold=0.04)
    results = await asyncio.gather(
        *(register(client, "race@example.com", ip=f"203.0.113.{i}") for i in range(10))
    )
    assert inflight.max >= 2, f"同時性が成立していない（無効試行）: {inflight.max}"
    assert all(r.status_code == 202 for r in results), [(r.status_code, r.text) for r in results]
    assert len({r.content for r in results}) == 1, "全応答の本文が同一"
    assert await scalar(engine, "SELECT COUNT(*) FROM members WHERE email='race@example.com'") == 1
    assert await scalar(engine, "SELECT COUNT(*) FROM email_tokens") == 1
    # UNIQUE 違反の 9 本が「既登録」の枝に入った（確認メール 1 通・既登録メール 9 通）
    assert len(mails(recording_mail, KIND_EMAIL_VERIFICATION)) == 1
    assert len(mails(recording_mail, KIND_ACCOUNT_EXISTS)) == 9


@pytest.mark.parametrize("domains", ["example.com", "example.com, example.net"])
async def test_it_030_09_demo_email_domains_restrict_registration(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], httpx.AsyncClient],
    test_database_url: str,
    seed_db: AsyncEngine,
    recording_mail: RecordingMailAdapter,
    domains: str,
) -> None:
    app = make_app(
        APP_ENV="test",
        DATABASE_URL=test_database_url,
        PUBLIC_WEB_BASE_URL=BASE_URL,
        DEMO_EMAIL_DOMAINS=domains,
    )
    recording_mail.install(app)
    client = client_factory(app)
    assert (await register(client, "ok@example.com")).status_code == 202
    assert (await register(client, "OK2@EXAMPLE.COM")).status_code == 202
    for email in ("sub@sub.example.com", "x@example.org"):
        res = await register(client, email)
        assert res.status_code == 422, email
        assert res.json() == {"code": "unsupported_value", "field": "email"}
    assert (await register(client, "net@example.net")).status_code == (
        202 if "net" in domains else 422
    )


async def test_it_030_09_without_setting_every_domain_is_accepted(
    client: httpx.AsyncClient,
) -> None:
    for email in ("a@example.com", "b@sub.example.com", "c@example.org"):
        assert (await register(client, email)).status_code == 202


async def test_it_030_10_register_is_rate_limited_per_ip_even_for_existing_emails(
    client: httpx.AsyncClient,
) -> None:
    for i in range(10):
        assert (await register(client, f"rl{i}@example.com", ip="198.51.100.1")).status_code == 202
    new = await register(client, "rl-new@example.com", ip="198.51.100.1")
    existing = await register(client, MEMBER1, ip="198.51.100.1")
    assert new.status_code == existing.status_code == 429
    assert new.json() == existing.json() == {"code": "rate_limited"}
    assert int(new.headers["Retry-After"]) >= 1
    assert (await register(client, "rl-other@example.com", ip="198.51.100.2")).status_code == 202


async def test_it_030_11_missing_public_web_base_url_is_500_for_new_and_existing(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], httpx.AsyncClient],
    test_database_url: str,
    seed_db: AsyncEngine,
    engine: AsyncEngine,
) -> None:
    """設定漏れを黙って許さない（8.1）。新規・既登録で応答が分かれないよう、どちらも 500。"""
    client = client_factory(make_app(APP_ENV="test", DATABASE_URL=test_database_url))
    new = await register(client, "nobase@example.com")
    existing = await register(client, MEMBER1)
    assert new.status_code == existing.status_code == 500
    assert new.content == existing.content
    assert (
        await scalar(engine, "SELECT COUNT(*) FROM members WHERE email='nobase@example.com'") == 0
    )


# ══════════════════════════════════════════════════════════════════════════
# IT-031 メール確認
# ══════════════════════════════════════════════════════════════════════════


async def _registered_token(
    client: httpx.AsyncClient,
    recording_mail: RecordingMailAdapter,
    email: str = "verify@example.com",
) -> str:
    assert (await register(client, email)).status_code == 202
    return token_of(mails(recording_mail, KIND_EMAIL_VERIFICATION)[-1].args["link"])


async def verify(client: httpx.AsyncClient, token: str, ip: str = "203.0.113.10") -> httpx.Response:
    return await client.post("/api/v1/auth/verify-email", json={"token": token}, headers=hdr(ip))


async def test_it_031_01_verify_sets_email_verified_at_and_marks_token_used(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    token = await _registered_token(client, recording_mail)
    res = await verify(client, token)
    assert res.status_code == 200 and res.json() == {"verified": True}
    assert (
        await scalar(
            engine, "SELECT email_verified_at FROM members WHERE email='verify@example.com'"
        )
        is not None
    )
    assert (
        await scalar(
            engine, "SELECT used_at FROM email_tokens WHERE token_hash=:h", h=hash_token(token)
        )
        is not None
    )
    audit = await sql(engine, "SELECT detail FROM audit_logs WHERE action='member.email_verified'")
    assert len(audit) == 1


async def test_it_031_02_reuse_unknown_malformed_and_other_purpose_tokens(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    token = await _registered_token(client, recording_mail)
    assert (await verify(client, token)).status_code == 200
    again = await verify(client, token)
    unknown = await verify(client, "A" * 43)
    assert again.status_code == unknown.status_code == 404
    assert again.json() == unknown.json() == {"code": "not_found"}
    for bad in ("A" * 42, "A" * 44, "A" * 42 + "!", "A" * 42 + "=", ""):
        res = await verify(client, bad)
        assert res.status_code == 400, bad
    # 再設定用のトークンでは確認できない
    assert (
        await client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "verify@example.com"},
            headers=hdr(),
        )
    ).status_code == 200
    reset_token = token_of(mails(recording_mail, KIND_PASSWORD_RESET)[-1].args["link"])
    assert (await verify(client, reset_token)).status_code == 404


async def test_it_031_02_token_only_verifies_its_owner(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    token_a = await _registered_token(client, recording_mail, "owner-a@example.com")
    await _registered_token(client, recording_mail, "owner-b@example.com")
    assert (await verify(client, token_a)).status_code == 200
    assert (
        await scalar(
            engine, "SELECT email_verified_at FROM members WHERE email='owner-a@example.com'"
        )
        is not None
    )
    assert (
        await scalar(
            engine, "SELECT email_verified_at FROM members WHERE email='owner-b@example.com'"
        )
        is None
    )


async def test_it_031_03_expiry_boundary(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    alive = await _registered_token(client, recording_mail, "alive@example.com")
    dead = await _registered_token(client, recording_mail, "dead@example.com")
    await sql(
        engine,
        "UPDATE email_tokens SET expires_at = UTC_TIMESTAMP() + INTERVAL 5 SECOND "
        "WHERE token_hash=:h",
        h=hash_token(alive),
    )
    await sql(
        engine,
        "UPDATE email_tokens SET expires_at = UTC_TIMESTAMP() - INTERVAL 5 SECOND "
        "WHERE token_hash=:h",
        h=hash_token(dead),
    )
    # 1 秒後に切れるトークンは、処理が遅れると切れうるので先に確認する
    assert (await verify(client, alive)).status_code == 200
    assert (await verify(client, dead)).status_code == 404
    assert (
        await scalar(engine, "SELECT email_verified_at FROM members WHERE email='dead@example.com'")
        is None
    )


async def test_it_031_04_verified_at_is_not_overwritten(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    token = await _registered_token(client, recording_mail)
    await sql(
        engine,
        "UPDATE members SET email_verified_at='2026-01-01 00:00:00' "
        "WHERE email='verify@example.com'",
    )
    assert (await verify(client, token)).status_code == 200
    value = await scalar(
        engine, "SELECT email_verified_at FROM members WHERE email='verify@example.com'"
    )
    assert str(value) == "2026-01-01 00:00:00", "確認済みの時刻は上書きしない"


async def test_it_031_05_verify_is_rate_limited_per_ip(client: httpx.AsyncClient) -> None:
    for _ in range(20):
        assert (await verify(client, "A" * 43, ip="198.51.100.5")).status_code == 404
    res = await verify(client, "A" * 43, ip="198.51.100.5")
    assert res.status_code == 429 and res.json() == {"code": "rate_limited"}


# ══════════════════════════════════════════════════════════════════════════
# IT-032 ログイン
# ══════════════════════════════════════════════════════════════════════════


async def test_it_032_01_login_issues_session_and_audit(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    verified_before = await scalar(
        engine, "SELECT email_verified_at FROM members WHERE email=:e", e=MEMBER1
    )
    res = await login(client, MEMBER1)
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert set(body) == {"session_token", "member"}
    assert len(body["session_token"]) == 43
    assert body["member"] == {"name": "デモ 一郎", "email_verified": True}
    rows = await sql(
        engine,
        "SELECT token_hash, subject_type, expires_at, last_seen_at, "
        "TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), expires_at) AS ttl FROM sessions",
    )
    assert len(rows) == 1
    assert rows[0].token_hash == hash_token(body["session_token"]) and len(rows[0].token_hash) == 64
    assert rows[0].subject_type == "member"
    assert abs(rows[0].ttl - 24 * 3600) <= 5
    assert await scalar(engine, "SELECT COUNT(*) FROM audit_logs WHERE action='member.login'") == 1
    assert (
        await scalar(engine, "SELECT email_verified_at FROM members WHERE email=:e", e=MEMBER1)
        == verified_before
    )
    # 未確認の会員もログインできる（DS-DEC-74）
    res3 = await login(client, MEMBER3)
    assert res3.status_code == 200 and res3.json()["member"]["email_verified"] is False


async def test_it_032_02_wrong_password_and_unknown_email_look_identical(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    wrong = await login(client, MEMBER1, WRONG_PW)
    unknown = await login(client, "nobody@example.com", WRONG_PW)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.content == unknown.content
    assert wrong.json() == {"code": "invalid_credentials"}
    assert {k: v for k, v in wrong.headers.items() if k != "date"} == {
        k: v for k, v in unknown.headers.items() if k != "date"
    }
    rows = await sql(engine, "SELECT identifier, succeeded, ip FROM login_attempts")
    assert len(rows) == 2 and not any(r.succeeded for r in rows)
    assert {r.identifier for r in rows} == {hash_token(MEMBER1), hash_token("nobody@example.com")}
    assert all("@" not in r.identifier for r in rows), "平文のメールを保存しない"
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 0


async def test_it_032_03_four_failures_then_success_five_failures_then_locked(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    for _ in range(4):
        assert (await login(client, MEMBER1, WRONG_PW)).status_code == 401
    assert (await login(client, MEMBER1)).status_code == 200
    assert not mails(recording_mail, KIND_ACCOUNT_LOCKED)

    for n in range(5):
        res = await login(client, MEMBER2, WRONG_PW)
        assert res.status_code == 401, f"{n + 1} 回目は 401（ロックは次の試行から）"
    assert len(mails(recording_mail, KIND_ACCOUNT_LOCKED)) == 1, "5 回目の失敗の時点で通知 1 通"
    assert mails(recording_mail, KIND_ACCOUNT_LOCKED)[0].to == MEMBER2
    res = await login(client, MEMBER2, WRONG_PW)
    assert res.status_code == 403 and res.json() == {"code": "account_locked"}
    assert len(mails(recording_mail, KIND_ACCOUNT_LOCKED)) == 1, "通知は 1 回だけ"
    assert "retry-after" not in res.headers and "locked_until" not in res.text


async def test_it_032_04_unknown_email_is_locked_the_same_without_notification(
    client: httpx.AsyncClient, recording_mail: RecordingMailAdapter
) -> None:
    for _ in range(5):
        assert (await login(client, "ghost@example.com", WRONG_PW)).status_code == 401
    res = await login(client, "ghost@example.com", WRONG_PW)
    assert res.status_code == 403 and res.json() == {"code": "account_locked"}
    assert not mails(recording_mail, KIND_ACCOUNT_LOCKED)


async def test_it_032_05_lock_window_boundary_14m59s_and_15m01s(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    for _ in range(5):
        await login(client, MEMBER1, WRONG_PW)
    await sql(engine, "UPDATE login_attempts SET at = UTC_TIMESTAMP() - INTERVAL 899 SECOND")
    res = await login(client, MEMBER1)
    assert res.status_code == 403, "14 分 59 秒前の失敗はまだ数える"
    await sql(engine, "UPDATE login_attempts SET at = UTC_TIMESTAMP() - INTERVAL 901 SECOND")
    res = await login(client, MEMBER1)
    assert res.status_code == 200, "15 分 1 秒前の失敗は数えない"


async def test_it_032_06_ip_limit_30_failures_gives_429_even_for_correct_password(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    ip = "198.51.100.20"
    for i in range(30):
        res = await login(client, f"spray{i}@example.com", WRONG_PW, ip=ip)
        assert res.status_code == 401, i
    res = await login(client, "spray30@example.com", WRONG_PW, ip=ip)
    assert res.status_code == 429 and res.json() == {"code": "rate_limited"}
    assert res.headers["retry-after"] == "900"
    ok = await login(client, MEMBER1, SEED_PW, ip=ip)
    assert ok.status_code == 429, "正しい会員の正しいパスワードも同じ IP では 429"
    assert (await login(client, MEMBER1, SEED_PW, ip="198.51.100.21")).status_code == 200
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 1


async def test_it_032_06_x_forwarded_for_uses_the_last_element(client: httpx.AsyncClient) -> None:
    """先頭の要素は呼び出し元が偽れるので、末尾（直前のホップ）で数える（G-14）。"""
    for i in range(30):
        h = hdr("198.51.100.30", **{"X-Forwarded-For": f"10.0.0.{i}, 198.51.100.30"})
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": f"x{i}@example.com", "password": WRONG_PW},
            headers=h,
        )
        assert res.status_code == 401
    res = await login(client, "x@example.com", WRONG_PW, ip="198.51.100.30")
    assert res.status_code == 429


async def test_it_032_07_relogin_replaces_old_session(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    old = await login_ok(client)
    assert (await me(client, old)).status_code == 200
    new = await login_ok(client, token=old)
    assert new != old
    assert (
        await scalar(engine, "SELECT COUNT(*) FROM sessions WHERE token_hash=:h", h=hash_token(old))
        == 0
    )
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 1
    assert (await me(client, old)).status_code == 401
    assert (await me(client, new)).status_code == 200


async def test_it_032_07_attacker_chosen_token_is_never_adopted(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    chosen = "S" * 43
    new = await login_ok(client, token=chosen)
    assert new != chosen
    assert (
        await scalar(
            engine, "SELECT COUNT(*) FROM sessions WHERE token_hash=:h", h=hash_token(chosen)
        )
        == 0
    )
    assert (await me(client, chosen)).status_code == 401
    # 形が違う値は無視される（エラーにならない）
    assert (await login(client, MEMBER2, token="short")).status_code == 200


async def test_it_032_08_old_hash_params_are_rehashed_on_login(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    from argon2 import PasswordHasher

    old_hash = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(SEED_PW)
    await sql(engine, "UPDATE members SET password_hash=:h WHERE email=:e", h=old_hash, e=MEMBER1)
    assert (await login(client, MEMBER1)).status_code == 200
    new_hash = await scalar(engine, "SELECT password_hash FROM members WHERE email=:e", e=MEMBER1)
    assert new_hash.startswith(PREFIX) and new_hash != old_hash
    assert (await login(client, MEMBER1, ip="203.0.113.11")).status_code == 200
    assert (
        await scalar(engine, "SELECT password_hash FROM members WHERE email=:e", e=MEMBER1)
        == new_hash
    ), "再ハッシュは 1 回だけ"
    assert (await login(client, MEMBER1, WRONG_PW, ip="203.0.113.12")).status_code == 401


@pytest.mark.parametrize(("logins", "expected"), [(9, 9), (10, 10), (11, 10)])
async def test_it_032_09_at_most_10_sessions_per_member(
    client: httpx.AsyncClient, engine: AsyncEngine, logins: int, expected: int
) -> None:
    tokens = [await login_ok(client, MEMBER1) for _ in range(logins)]
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == expected
    if logins == 11:
        assert (await me(client, tokens[0])).status_code == 401, "最も古いセッションが消える"
        assert (await me(client, tokens[1])).status_code == 200
        assert (await me(client, tokens[10])).status_code == 200


async def test_it_032_09_other_members_sessions_do_not_count(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    other = await login_ok(client, MEMBER2)
    for _ in range(11):
        await login_ok(client, MEMBER1)
    assert (await me(client, other)).status_code == 200
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 11


async def test_it_032_09_expired_sessions_are_removed_on_login(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await login_ok(client, MEMBER1)
    await sql(engine, "UPDATE sessions SET expires_at = UTC_TIMESTAMP() - INTERVAL 5 SECOND")
    await login_ok(client, MEMBER1)
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 1


async def test_it_032_10_success_clears_failures_and_restarts_the_count(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    for _ in range(3):
        await login(client, MEMBER1, WRONG_PW)
    assert (await login(client, MEMBER1)).status_code == 200
    ident = hash_token(MEMBER1)
    assert (
        await scalar(
            engine,
            "SELECT COUNT(*) FROM login_attempts WHERE identifier=:i AND succeeded=0",
            i=ident,
        )
        == 0
    )
    assert (
        await scalar(
            engine,
            "SELECT COUNT(*) FROM login_attempts WHERE identifier=:i AND succeeded=1",
            i=ident,
        )
        == 1
    )
    for _ in range(5):
        assert (await login(client, MEMBER1, WRONG_PW)).status_code == 401
    assert (await login(client, MEMBER1, WRONG_PW)).status_code == 403


async def test_it_032_11_locked_member_with_correct_password_gets_no_session(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    for _ in range(5):
        await login(client, MEMBER1, WRONG_PW)
    res = await login(client, MEMBER1)
    assert res.status_code == 403 and res.json() == {"code": "account_locked"}
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 0


async def test_it_032_12_validation_and_anonymized_member(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    res = await client.post("/api/v1/auth/login", json={"email": MEMBER1}, headers=hdr())
    assert res.status_code == 400 and res.json()["fields"] == [
        {"name": "password", "reason": "required"}
    ]
    res = await client.post("/api/v1/auth/login", json={"password": SEED_PW}, headers=hdr())
    assert res.status_code == 400
    res = await login(client, MEMBER1, "a" * 129)
    assert res.status_code == 400 and res.json()["fields"] == [
        {"name": "password", "reason": "too_long"}
    ]
    res = await login(client, "not-an-email", SEED_PW)
    assert res.status_code == 400

    await sql(engine, "UPDATE members SET anonymized_at=UTC_TIMESTAMP() WHERE email=:e", e=MEMBER4)
    anonymized = await login(client, MEMBER4)
    unknown = await login(client, "nobody@example.com", SEED_PW)
    assert anonymized.status_code == unknown.status_code == 401
    assert anonymized.content == unknown.content


async def test_it_032_13_same_member_10_parallel_logins_with_3_wrong(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.auth")
    # sessions の整理から INSERT までの窓を 30ms 広げる
    inflight = track_inflight(monkeypatch, sessions_repo, "evict_oldest_for_new_session", hold=0.03)
    jobs = [login(client, MEMBER1, ip=f"203.0.113.{i}") for i in range(10)] + [
        login(client, MEMBER1, WRONG_PW, ip=f"203.0.114.{i}") for i in range(3)
    ]
    results = await asyncio.gather(*jobs)
    assert inflight.max >= 2, f"同時性が成立していない（無効試行）: {inflight.max}"
    good, bad = results[:10], results[10:]
    assert all(r.status_code == 200 for r in good), [(r.status_code, r.text) for r in good]
    assert all(r.status_code == 401 for r in bad), [(r.status_code, r.text) for r in bad]
    assert len({r.json()["session_token"] for r in good}) == 10
    sessions = await scalar(engine, "SELECT COUNT(*) FROM sessions")
    assert sessions <= 10, sessions
    retries = [r for r in caplog.records if "ロック競合" in r.getMessage()]
    print(
        f"\nIT-032-13: inflight_max={inflight.max} 再試行（1213/1205）={len(retries)} 回"
        f" セッション={sessions}"
    )


async def test_it_032_16_login_and_confirm_run_in_read_committed(
    client: httpx.AsyncClient,
    recording_mail: RecordingMailAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5.6: ギャップロックを避けるため、ログインと再設定の確定は READ COMMITTED で実行する。"""
    seen: dict[str, str] = {}

    def spy(module: Any, name: str, label: str) -> None:
        original = getattr(module, name)

        async def wrapped(session: Any, *args: Any, **kwargs: Any) -> Any:
            row = await session.execute(text("SELECT @@transaction_isolation"))
            seen[label] = row.scalar_one()
            return await original(session, *args, **kwargs)

        monkeypatch.setattr(module, name, wrapped)

    spy(sessions_repo, "insert_session", "login")
    spy(members_repo, "set_password_hash", "confirm")
    await login_ok(client, MEMBER1)
    token = await _reset_token(client, recording_mail)
    assert (await reset_confirm(client, token)).status_code == 200
    assert seen == {"login": "READ-COMMITTED", "confirm": "READ-COMMITTED"}


async def test_it_032_14_old_login_attempts_are_cleaned_up_on_success(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    ident = hash_token("old@example.com")
    await sql(
        engine,
        "INSERT INTO login_attempts "
        "(subject_type, identifier, succeeded, ip, at, created_at, updated_at) VALUES "
        "('member', :i, 0, '203.0.113.99', UTC_TIMESTAMP() - INTERVAL 25 HOUR, "
        "UTC_TIMESTAMP(), UTC_TIMESTAMP()), "
        "('member', :i, 0, '203.0.113.99', UTC_TIMESTAMP() - INTERVAL 23 HOUR, "
        "UTC_TIMESTAMP(), UTC_TIMESTAMP())",
        i=ident,
    )
    await login_ok(client, MEMBER1)
    assert (
        await scalar(engine, "SELECT COUNT(*) FROM login_attempts WHERE identifier=:i", i=ident)
        == 1
    )


async def test_it_032_15_logs_do_not_contain_email_password_or_token(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    await login(client, MEMBER1, WRONG_PW, ip="198.51.100.77")
    token = await login_ok(client, MEMBER2)
    text_logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (MEMBER1, MEMBER2, WRONG_PW, SEED_PW, token):
        assert secret not in text_logged
    assert "198.51.100.77" not in text_logged, "拒否ログの IP は丸める"


# ══════════════════════════════════════════════════════════════════════════
# IT-033 ログアウト
# ══════════════════════════════════════════════════════════════════════════


async def logout(client: httpx.AsyncClient, token: str | None) -> httpx.Response:
    return await client.post("/api/v1/auth/logout", headers=hdr(token=token))


async def test_it_033_01_logout_deletes_session(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    token = await login_ok(client)
    res = await logout(client, token)
    assert res.status_code == 204 and res.content == b""
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 0
    assert (await me(client, token)).status_code == 401
    assert (await logout(client, token)).status_code == 204, "2 回目も 204（冪等）"


async def test_it_033_02_invalid_tokens_are_204_and_touch_nothing(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await login_ok(client)
    for token in (None, "Z" * 43, "short", "A" * 42 + "!"):
        assert (await logout(client, token)).status_code == 204, token
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 1


async def test_it_033_03_only_the_presented_session_is_removed(client: httpx.AsyncClient) -> None:
    first = await login_ok(client)
    second = await login_ok(client)
    assert (await logout(client, first)).status_code == 204
    assert (await me(client, first)).status_code == 401
    assert (await me(client, second)).status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# IT-034 パスワード再設定の要求
# ══════════════════════════════════════════════════════════════════════════


async def reset_request(
    client: httpx.AsyncClient, email: str, ip: str = "203.0.113.10", **extra: str
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/password-reset/request", json={"email": email}, headers=hdr(ip, **extra)
    )


async def reset_confirm(
    client: httpx.AsyncClient, token: str, password: str = NEW_PW, ip: str = "203.0.113.10"
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": password},
        headers=hdr(ip),
    )


async def test_it_034_01_known_member_gets_token_and_mail_and_old_tokens_are_voided(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    res = await reset_request(client, MEMBER1)
    assert res.status_code == 200 and res.json() == {"status": "accepted"}
    rows = await sql(
        engine,
        "SELECT purpose, used_at, "
        "TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), expires_at) AS ttl FROM email_tokens",
    )
    assert len(rows) == 1 and rows[0].purpose == "reset_password" and abs(rows[0].ttl - 3600) <= 5
    sent = mails(recording_mail, KIND_PASSWORD_RESET)
    assert len(sent) == 1 and sent[0].to == MEMBER1
    assert sent[0].args["link"].startswith(f"{BASE_URL}/password-reset/confirm?token=")
    # 2 回目の要求で、前の未使用トークンは使用済みになる
    await reset_request(client, MEMBER1)
    used = await sql(engine, "SELECT used_at IS NOT NULL AS used FROM email_tokens ORDER BY id")
    assert [r.used for r in used] == [1, 0]


async def test_it_034_02_unknown_email_gets_identical_200_and_nothing_else(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    known = await reset_request(client, MEMBER1)
    recording_mail.clear()
    tokens_before = await scalar(engine, "SELECT COUNT(*) FROM email_tokens")
    unknown = await reset_request(client, "nobody@example.com")
    assert unknown.status_code == known.status_code == 200
    assert unknown.content == known.content
    assert await scalar(engine, "SELECT COUNT(*) FROM email_tokens") == tokens_before
    assert not recording_mail.sent
    # 匿名化済みの会員も「いない」扱い
    await sql(engine, "UPDATE members SET anonymized_at=UTC_TIMESTAMP() WHERE email=:e", e=MEMBER4)
    assert (await reset_request(client, MEMBER4)).content == known.content
    assert not recording_mail.sent


async def test_it_034_03_invalid_email_and_domain_restriction(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], httpx.AsyncClient],
    test_database_url: str,
    seed_db: AsyncEngine,
    recording_mail: RecordingMailAdapter,
) -> None:
    app = make_app(
        APP_ENV="test",
        DATABASE_URL=test_database_url,
        PUBLIC_WEB_BASE_URL=BASE_URL,
        DEMO_EMAIL_DOMAINS="example.com",
    )
    recording_mail.install(app)
    client = client_factory(app)
    res = await reset_request(client, "abc")
    assert res.status_code == 400 and res.json()["fields"] == [
        {"name": "email", "reason": "format"}
    ]
    res = await reset_request(client, "x@example.org")
    assert res.status_code == 422 and res.json() == {"code": "unsupported_value", "field": "email"}
    assert (await reset_request(client, MEMBER1)).status_code == 200


async def test_it_034_04_rate_limits_5_per_ip_and_3_per_email(client: httpx.AsyncClient) -> None:
    for i in range(5):
        assert (
            await reset_request(client, f"u{i}@example.com", ip="198.51.100.40")
        ).status_code == 200
    res = await reset_request(client, "u5@example.com", ip="198.51.100.40")
    assert res.status_code == 429 and res.json() == {"code": "rate_limited"}
    assert int(res.headers["Retry-After"]) >= 1

    for i in range(3):
        assert (await reset_request(client, MEMBER1, ip=f"198.51.100.{50 + i}")).status_code == 200
    res = await reset_request(client, MEMBER1, ip="198.51.100.60")
    assert res.status_code == 429, "同じメールは IP を替えても 3 回/時"
    # 全角・大文字でも同じメールとして数える。未登録のメールも同じ数え方
    res = await reset_request(
        client, "ＤＥＭＯ-ＭＥＭＢＥＲ１＠ＥＸＡＭＰＬＥ．ＣＯＭ", ip="198.51.100.61"
    )
    assert res.status_code == 429
    for i in range(3):
        assert (
            await reset_request(client, "ghost@example.com", ip=f"198.51.100.{70 + i}")
        ).status_code == 200
    assert (await reset_request(client, "ghost@example.com", ip="198.51.100.80")).status_code == 429


async def test_it_034_05_link_host_is_public_web_base_url_not_the_host_header(
    client: httpx.AsyncClient, recording_mail: RecordingMailAdapter
) -> None:
    res = await reset_request(
        client, MEMBER1, **{"Host": "evil.example", "X-Forwarded-Host": "evil.example"}
    )
    assert res.status_code == 200
    link = mails(recording_mail, KIND_PASSWORD_RESET)[0].args["link"]
    assert link.startswith(BASE_URL + "/") and "evil.example" not in link


# ══════════════════════════════════════════════════════════════════════════
# IT-035 パスワード再設定の確定
# ══════════════════════════════════════════════════════════════════════════


async def _reset_token(
    client: httpx.AsyncClient, recording_mail: RecordingMailAdapter, email: str = MEMBER1
) -> str:
    assert (await reset_request(client, email, ip="198.51.100.200")).status_code == 200
    return token_of(mails(recording_mail, KIND_PASSWORD_RESET)[-1].args["link"])


async def test_it_035_01_confirm_updates_password_and_revokes_everything(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    session_a = await login_ok(client, MEMBER1)
    session_b = await login_ok(client, MEMBER1)
    other = await login_ok(client, MEMBER2)
    for _ in range(2):
        await login(client, MEMBER1, WRONG_PW)
    old_hash = await scalar(engine, "SELECT password_hash FROM members WHERE email=:e", e=MEMBER1)
    token = await _reset_token(client, recording_mail)

    res = await reset_confirm(client, token)
    assert res.status_code == 200 and res.json() == {"status": "ok"}
    assert "set-cookie" not in res.headers and "session_token" not in res.text, "自動ログインしない"
    new_hash = await scalar(engine, "SELECT password_hash FROM members WHERE email=:e", e=MEMBER1)
    assert new_hash != old_hash and new_hash.startswith(PREFIX)
    assert (
        await scalar(
            engine, "SELECT used_at FROM email_tokens WHERE token_hash=:h", h=hash_token(token)
        )
        is not None
    )
    assert (await me(client, session_a)).status_code == 401 and (
        await me(client, session_b)
    ).status_code == 401
    assert (await me(client, other)).status_code == 200, "他の会員のセッションは残る"
    assert (
        await scalar(
            engine,
            "SELECT COUNT(*) FROM login_attempts WHERE identifier=:i AND succeeded=0",
            i=hash_token(MEMBER1),
        )
        == 0
    )
    audit = await sql(engine, "SELECT detail FROM audit_logs WHERE action='member.password_reset'")
    assert len(audit) == 1

    assert (await login(client, MEMBER1, SEED_PW)).status_code == 401
    assert (await login(client, MEMBER1, NEW_PW)).status_code == 200


async def test_it_035_02_invalid_tokens(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    token = await _reset_token(client, recording_mail)
    assert (await reset_confirm(client, token)).status_code == 200
    used = await reset_confirm(client, token, GOOD_PW)
    unknown = await reset_confirm(client, "A" * 43)
    assert used.status_code == unknown.status_code == 404
    assert used.json() == unknown.json() == {"code": "not_found"}
    for bad in ("A" * 42, "A" * 44, "A" * 42 + "!"):
        assert (await reset_confirm(client, bad)).status_code == 400
    # 確認用のトークンでは再設定できない
    assert (await register(client, "purpose@example.com")).status_code == 202
    verify_token = token_of(mails(recording_mail, KIND_EMAIL_VERIFICATION)[-1].args["link"])
    assert (await reset_confirm(client, verify_token)).status_code == 404
    assert (await login(client, "purpose@example.com", GOOD_PW)).status_code == 200, (
        "パスワードは変わっていない"
    )


async def test_it_035_03_weak_password_does_not_consume_the_token(
    client: httpx.AsyncClient, recording_mail: RecordingMailAdapter
) -> None:
    token = await _reset_token(client, recording_mail)
    for weak in ("password123", MEMBER1, "aaaaaaaa"):
        res = await reset_confirm(client, token, weak)
        assert res.status_code == 422, weak
        assert res.json() == {"code": "weak_password", "field": "password"}
    assert (await reset_confirm(client, token, "short")).status_code == 400
    assert (await reset_confirm(client, token, NEW_PW)).status_code == 200


async def test_it_035_04_expiry_boundary(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    alive = await _reset_token(client, recording_mail, MEMBER1)
    dead = await _reset_token(client, recording_mail, MEMBER2)
    await sql(
        engine,
        "UPDATE email_tokens SET expires_at = UTC_TIMESTAMP() + INTERVAL 5 SECOND "
        "WHERE token_hash=:h",
        h=hash_token(alive),
    )
    await sql(
        engine,
        "UPDATE email_tokens SET expires_at = UTC_TIMESTAMP() - INTERVAL 5 SECOND "
        "WHERE token_hash=:h",
        h=hash_token(dead),
    )
    assert (await reset_confirm(client, alive)).status_code == 200
    assert (await reset_confirm(client, dead)).status_code == 404
    assert (await login(client, MEMBER2, SEED_PW)).status_code == 200, "期限切れでは変わらない"


async def test_it_035_05_newer_request_voids_the_older_link(
    client: httpx.AsyncClient, recording_mail: RecordingMailAdapter
) -> None:
    first = await _reset_token(client, recording_mail)
    second = await _reset_token(client, recording_mail)
    assert first != second
    assert (await reset_confirm(client, first)).status_code == 404
    assert (await reset_confirm(client, second)).status_code == 200


async def test_it_035_06_same_token_10_parallel_confirmations(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    recording_mail: RecordingMailAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await login_ok(client, MEMBER1)
    token = await _reset_token(client, recording_mail)
    inflight = track_inflight(monkeypatch, auth_service, "password_reset_confirm")
    updates = track_inflight(monkeypatch, members_repo, "set_password_hash", hold=0.03)
    results = await asyncio.gather(
        *(reset_confirm(client, token, NEW_PW, ip=f"203.0.113.{i}") for i in range(10))
    )
    assert inflight.max >= 2, f"同時性が成立していない（無効試行）: {inflight.max}"
    codes = sorted(r.status_code for r in results)
    assert codes == [200] + [404] * 9, codes
    assert all(r.json() == {"code": "not_found"} for r in results if r.status_code == 404)
    assert await scalar(engine, "SELECT COUNT(*) FROM sessions") == 0
    assert (
        await scalar(engine, "SELECT COUNT(*) FROM audit_logs WHERE action='member.password_reset'")
        == 1
    )
    assert updates.max == 1, "ハッシュの更新は 1 回（FOR UPDATE で直列化）"


async def test_it_035_07_confirm_is_rate_limited_per_ip(client: httpx.AsyncClient) -> None:
    for _ in range(10):
        assert (await reset_confirm(client, "A" * 43, ip="198.51.100.90")).status_code == 404
    assert (await reset_confirm(client, "A" * 43, ip="198.51.100.90")).status_code == 429


# ══════════════════════════════════════════════════════════════════════════
# IT-036 会員情報
# ══════════════════════════════════════════════════════════════════════════


async def test_it_036_01_me_returns_only_the_four_keys(client: httpx.AsyncClient) -> None:
    res = await me(client, await login_ok(client, MEMBER1))
    assert res.status_code == 200
    assert res.json() == {
        "name": "デモ 一郎",
        "email": MEMBER1,
        "email_verified": True,
        "personalize_opt_in": False,
    }
    res3 = await me(client, await login_ok(client, MEMBER3))
    assert res3.json()["email_verified"] is False
    assert not ({"id", "password_hash", "birth_date", "gender"} & set(res.json()))


async def test_it_036_02_missing_malformed_unknown_and_expired_sessions_are_401(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    assert (await me(client, None)).status_code == 401
    for token in ("short", "A" * 44, "A" * 42 + "!", "Z" * 43):
        res = await me(client, token)
        assert (res.status_code, res.json()) == (401, {"code": "unauthorized"}), token
    token = await login_ok(client)
    await sql(engine, "UPDATE sessions SET expires_at = UTC_TIMESTAMP() - INTERVAL 5 SECOND")
    assert (await me(client, token)).status_code == 401


async def test_it_036_03_anonymized_and_staff_sessions_are_401(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    token = await login_ok(client, MEMBER4)
    assert (await me(client, token)).status_code == 200
    await sql(engine, "UPDATE members SET anonymized_at=UTC_TIMESTAMP() WHERE email=:e", e=MEMBER4)
    assert (await me(client, token)).status_code == 401

    member_id = await scalar(engine, "SELECT id FROM members WHERE email=:e", e=MEMBER1)
    staff_token = "T" * 43
    await sql(
        engine,
        "INSERT INTO sessions "
        "(token_hash, subject_type, subject_id, expires_at, last_seen_at, created_at, updated_at) "
        "VALUES (:h, 'staff', :m, UTC_TIMESTAMP() + INTERVAL 1 HOUR, "
        "UTC_TIMESTAMP(), UTC_TIMESTAMP(), UTC_TIMESTAMP())",
        h=hash_token(staff_token),
        m=member_id,
    )
    assert (await me(client, staff_token)).status_code == 401, (
        "staff のセッションは会員として通らない"
    )


async def test_it_036_04_me_requires_internal_token(client: httpx.AsyncClient) -> None:
    token = await login_ok(client)
    res = await client.get("/api/v1/me", headers={"X-Session-Token": token})
    assert res.status_code == 401


async def test_hashing_is_done_with_the_shared_module(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """登録した会員のハッシュを `app.core.passwords` で検証できる（seed と同じパラメータ）。"""
    await register(client, "shared@example.com")
    stored = await scalar(
        engine, "SELECT password_hash FROM members WHERE email='shared@example.com'"
    )
    assert passwords.verify_password(stored, GOOD_PW)
    seed_hash = await scalar(engine, "SELECT password_hash FROM members WHERE email=:e", e=MEMBER1)
    assert seed_hash.split("$")[2:4] == stored.split("$")[2:4], "seed と同じパラメータ"
