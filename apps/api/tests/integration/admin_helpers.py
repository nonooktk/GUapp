"""P2-c の管理 API の IT 共通ヘルパー（担当レーン: C-1。C-2・C-3 の IT も使う）。

設計: テスト設計書 P2 追補c 1 章 #3 / 設計仕様書 P2 追補c 11.3。

- `create_staff`: テスト内で `staff` の行を作る（argon2id のハッシュ。seed の `demo-staff` は
  使わない。seed の確認は IT-050-01・UT-SEED だけ）
- `admin_headers`: 内部トークン ＋ `X-Admin-Session-Token`（＋ `X-Forwarded-For`）
- `make_admin_session`: `sessions` に管理者のセッションを直接入れて、生の値（43 文字）を返す
  （ログイン API を通さずにトークンを得る近道。会員のセッションは `p2b_helpers.make_session`）
- `login_admin`・`login_admin_ok`: `POST /api/v1/admin/auth/login` を呼ぶ

パスワードはすべてテスト用のダミー値（実在の資格情報ではない）。氏名・メールは扱わない。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core import passwords
from app.core.session import hash_token
from tests.conftest import TEST_INTERNAL_TOKEN

ADMIN_PASSWORD = "Admin-Test-Phrase-01"  # pragma: allowlist secret
OTHER_ADMIN_PASSWORD = "Admin-Other-Phrase-02"  # pragma: allowlist secret
WRONG_ADMIN_PASSWORD = "Admin-Wrong-Phrase-99"  # pragma: allowlist secret

ADMIN_LOGIN_PATH = "/api/v1/admin/auth/login"
ADMIN_LOGOUT_PATH = "/api/v1/admin/auth/logout"
ADMIN_ME_PATH = "/api/v1/admin/me"
DEFAULT_IP = "203.0.113.50"


def utcnow() -> datetime:
    """DB は UTC の naive datetime。"""
    return datetime.now(UTC).replace(tzinfo=None)


async def create_staff(
    engine: AsyncEngine,
    login_id: str = "test-staff",
    password: str = ADMIN_PASSWORD,
    *,
    role: str = "staff",
    password_hash: str | None = None,
) -> int:
    """`staff` の行を入れて ID を返す。`password_hash` を渡すと、それをそのまま保存する。

    （旧パラメータのハッシュで再ハッシュを確かめるときなどに使う。）
    """
    hashed = password_hash if password_hash is not None else passwords.hash_password(password)
    async with engine.begin() as conn:
        result = await conn.execute(
            text("INSERT INTO staff (login_id, password_hash, role) VALUES (:l, :p, :r)"),
            {"l": login_id, "p": hashed, "r": role},
        )
        return int(result.lastrowid)


async def make_admin_session(
    engine: AsyncEngine,
    staff_id: int,
    *,
    ttl: timedelta = timedelta(hours=1),
    subject_type: str = "staff",
) -> str:
    """有効（既定）または期限切れ（負の ttl）の管理者のセッションを入れ、生の値を返す。

    `subject_type="member"` にすると、会員 ID を `staff_id` に渡して会員のセッションを作れる
    （会員のセッションを管理 API に提示するテスト用。`p2b_helpers.make_session` と同じ結果）。
    """
    token = secrets.token_urlsafe(32)
    assert len(token) == 43
    now = utcnow()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO sessions (token_hash, subject_type, subject_id, expires_at,"
                " last_seen_at) VALUES (:h, :t, :s, :x, :n)"
            ),
            {"h": hash_token(token), "t": subject_type, "s": staff_id, "x": now + ttl, "n": now},
        )
    return token


def admin_headers(
    token: str | None = None, *, ip: str | None = None, **extra: str
) -> dict[str, str]:
    """内部トークン ＋ `X-Admin-Session-Token`（`token` があれば）＋ `X-Forwarded-For`（`ip`）。"""
    headers = {"X-Internal-Token": TEST_INTERNAL_TOKEN, **extra}
    if token is not None:
        headers["X-Admin-Session-Token"] = token
    if ip is not None:
        headers["X-Forwarded-For"] = ip
    return headers


async def login_admin(
    client: httpx.AsyncClient,
    login_id: str = "test-staff",
    password: str = ADMIN_PASSWORD,
    *,
    ip: str = DEFAULT_IP,
    token: str | None = None,
) -> httpx.Response:
    """`token` は古いセッション（`X-Admin-Session-Token`。再発行時の削除に使う）。"""
    return await client.post(
        ADMIN_LOGIN_PATH,
        json={"login_id": login_id, "password": password},
        headers=admin_headers(token, ip=ip),
    )


async def login_admin_ok(client: httpx.AsyncClient, *args: Any, **kwargs: Any) -> str:
    """ログインして、生のセッショントークンを返す（200 を期待）。"""
    res = await login_admin(client, *args, **kwargs)
    assert res.status_code == 200, res.text
    return res.json()["session_token"]
