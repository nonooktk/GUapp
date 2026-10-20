"""UT-ADM-01〜07・17・18: 管理認証と共通部品の単体テスト（SQLite のファイル DB）。

テスト設計書 P2 追補c 5.1 / 設計仕様書 P2 追補c 4.6（DS-PRC-050・050b・054・055）。
MySQL 固有の挙動（`FOR UPDATE`・READ COMMITTED・CHECK 制約）は IT で担保する。

- UT-ADM-01 管理セッションの有効性（境界）／02 セッションの分類／03 `require_staff` の状態コード
- UT-ADM-04 login_id の正規化／05 管理ログインの識別子と閾値／06 ダミー検証／07 更新前の値の照合
- UT-ADM-17 監査ログの禁止キー／18 監査ログの改変が無いこと（ソースの静的検査）
- 併せて、ページ送りの型（`schemas/admin_common.py`）と管理者の分離（会員側の依存関数）
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

import app as app_package
from app.core import admin_session as admin_session_mod
from app.core import passwords
from app.core.admin_session import (
    ALLOWED_ROLES,
    AdminSessionKind,
    CurrentStaff,
    lookup_admin_session,
    require_staff,
)
from app.core.errors import AppError
from app.core.session import find_member_by_session_token, hash_token
from app.models import ActorType, AuditLog, AuthSession, Base, LoginAttempt, Staff, SubjectType
from app.repositories import login_attempts as attempts_repo
from app.schemas.admin_common import (
    DEFAULT_PER_PAGE,
    INT32_MAX,
    PageParams,
    build_page,
    page_params,
)
from app.services import admin_auth
from app.services.admin_audit import FORBIDDEN_DETAIL_KEYS, find_forbidden_key, write_admin_audit
from app.services.admin_auth import (
    ID_LOCK_THRESHOLD,
    IP_LIMIT_THRESHOLD,
    InvalidLoginId,
    admin_login_identifier,
    is_id_locked,
    is_ip_limited,
    normalize_login_id,
)
from app.services.optimistic import ensure_expected

NOW = datetime(2026, 10, 27, 12, 0, 0)
TOKEN_A = "A" * 43
TOKEN_B = "B" * 43


@pytest.fixture
async def staff_db(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _add_staff(
    engine: AsyncEngine, staff_id: int = 1, *, login_id: str = "staff-a", role: str = "staff"
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            insert(Staff).values(
                id=staff_id,
                login_id=login_id,
                password_hash="$argon2id$dummy",
                role=role,
                created_at=NOW,
                updated_at=NOW,
            )
        )


async def _add_session(
    engine: AsyncEngine,
    token: str,
    subject_id: int,
    *,
    expires_at: datetime,
    subject_type: SubjectType = SubjectType.staff,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            insert(AuthSession).values(
                token_hash=hash_token(token),
                subject_type=subject_type,
                subject_id=subject_id,
                expires_at=expires_at,
                last_seen_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )


async def _lookup(engine: AsyncEngine, token: str | None, now: datetime = NOW):
    async with AsyncSession(engine) as session:
        return await lookup_admin_session(session, token, now=now)


def _request(path: str = "/api/v1/admin/me", ip: str = "203.0.113.9") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [(b"x-forwarded-for", ip.encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-01 管理セッションの有効性（DS-PRC-050b）
# ══════════════════════════════════════════════════════════════════════════


async def test_ut_adm_01_expiry_boundary_and_missing_staff_row(staff_db: AsyncEngine) -> None:
    """1 秒後の staff だけが有効。ちょうど現在は無効（`expires_at > now`）。行が無ければ無効。"""
    await _add_staff(staff_db, 1)
    await _add_session(staff_db, "1" * 43, 1, expires_at=NOW + timedelta(seconds=1))
    await _add_session(staff_db, "2" * 43, 1, expires_at=NOW)
    await _add_session(staff_db, "3" * 43, 1, expires_at=NOW - timedelta(seconds=1))
    await _add_session(
        staff_db, "4" * 43, 1, expires_at=NOW + timedelta(hours=1), subject_type=SubjectType.member
    )
    await _add_session(
        staff_db, "5" * 43, 99, expires_at=NOW + timedelta(hours=1)
    )  # 管理者の行が無い

    ok = await _lookup(staff_db, "1" * 43)
    assert ok.kind is AdminSessionKind.staff
    assert ok.staff == CurrentStaff(id=1, login_id="staff-a", role="staff")
    assert (await _lookup(staff_db, "2" * 43)).kind is AdminSessionKind.invalid
    assert (await _lookup(staff_db, "3" * 43)).kind is AdminSessionKind.invalid
    assert (await _lookup(staff_db, "4" * 43)).kind is AdminSessionKind.member
    assert (await _lookup(staff_db, "5" * 43)).kind is AdminSessionKind.invalid
    assert (await _lookup(staff_db, "6" * 43)).kind is AdminSessionKind.invalid, "未知のトークン"


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-02 セッションの分類（DS-PRC-050b）
# ══════════════════════════════════════════════════════════════════════════


class _ExplodingSession:
    """DB を引いたら失敗する。形が違う値で DB を引かないことの確認用。"""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("DB を引いてはいけない")


@pytest.mark.parametrize("bad", [None, "", "A" * 42, "A" * 44, "A" * 42 + "=", "A" * 42 + " "])
async def test_ut_adm_02_malformed_token_is_invalid_without_touching_the_db(
    bad: str | None,
) -> None:
    result = await lookup_admin_session(_ExplodingSession(), bad)  # type: ignore[arg-type]
    assert result.kind is AdminSessionKind.invalid and result.staff is None


async def test_ut_adm_02_three_kinds(staff_db: AsyncEngine) -> None:
    await _add_staff(staff_db, 1)
    await _add_session(staff_db, TOKEN_A, 1, expires_at=NOW + timedelta(hours=1))
    await _add_session(
        staff_db, TOKEN_B, 7, expires_at=NOW + timedelta(hours=1), subject_type=SubjectType.member
    )
    await _add_session(staff_db, "C" * 43, 1, expires_at=NOW - timedelta(hours=1))
    assert {r.kind for r in [await _lookup(staff_db, TOKEN_A)]} == {AdminSessionKind.staff}
    member = await _lookup(staff_db, TOKEN_B)
    assert member.kind is AdminSessionKind.member and member.staff is None
    assert (await _lookup(staff_db, "C" * 43)).kind is AdminSessionKind.invalid
    assert (await _lookup(staff_db, "D" * 43)).kind is AdminSessionKind.invalid


async def test_ut_adm_02_member_dependency_still_rejects_staff_sessions(
    staff_db: AsyncEngine,
) -> None:
    """逆方向の分離: 管理者のセッションは会員の依存関数では常に無効（追補b・DS-DEC-72）。"""
    await _add_staff(staff_db, 1)
    await _add_session(staff_db, TOKEN_A, 1, expires_at=NOW + timedelta(hours=1))
    async with AsyncSession(staff_db) as session:
        assert await find_member_by_session_token(session, TOKEN_A, now=NOW) is None


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-03 require_staff の状態コード（DS-DEC-109・111）
# ══════════════════════════════════════════════════════════════════════════


def _future() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)


async def _require(
    engine: AsyncEngine, token: str | None
) -> tuple[CurrentStaff | AppError, AsyncMock]:
    async with AsyncSession(engine) as session:
        rollback = AsyncMock(wraps=session.rollback)
        session.rollback = rollback  # type: ignore[method-assign]
        try:
            result: CurrentStaff | AppError = await require_staff(
                _request(), x_admin_session_token=token, session=session
            )
        except AppError as exc:
            result = exc
        return result, rollback


async def test_ut_adm_03_status_codes_and_rollback(
    staff_db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _add_staff(staff_db, 1)
    await _add_session(staff_db, TOKEN_A, 1, expires_at=_future())
    await _add_session(staff_db, TOKEN_B, 7, expires_at=_future(), subject_type=SubjectType.member)
    await _add_session(staff_db, "C" * 43, 1, expires_at=_future() - timedelta(hours=1, seconds=1))

    ok, rollback = await _require(staff_db, TOKEN_A)
    assert ok == CurrentStaff(id=1, login_id="staff-a", role="staff")
    rollback.assert_awaited()  # 読み取りのトランザクションを rollback() で終える

    for token in (None, "short", "D" * 43, "C" * 43):
        err, rollback = await _require(staff_db, token)
        assert isinstance(err, AppError) and (err.status, err.code) == (401, "unauthorized")
        rollback.assert_awaited()

    err, rollback = await _require(staff_db, TOKEN_B)
    assert isinstance(err, AppError) and (err.status, err.code) == (403, "forbidden")
    rollback.assert_awaited()

    # 許可するロールの集合から外れた管理者は 403（DS-DEC-111）
    assert ALLOWED_ROLES == frozenset({"staff"})
    monkeypatch.setattr(admin_session_mod, "ALLOWED_ROLES", frozenset())
    err, rollback = await _require(staff_db, TOKEN_A)
    assert isinstance(err, AppError) and (err.status, err.code) == (403, "forbidden")
    rollback.assert_awaited()


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-04 login_id の正規化（DS-API-050）
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("staff-a", "staff-a"),
        ("ＳＴＡＦＦ-ａ", "staff-a"),  # 全角英数・全角ハイフン相当
        ("Staff-A", "staff-a"),
        ("  staff-a  ", "staff-a"),
        ("\u3000staff-a\u3000", "staff-a"),  # 全角空白
        ("abc", "abc"),  # 3 文字は可
        ("a" * 50, "a" * 50),  # 50 文字は可
        ("a.b_c-d", "a.b_c-d"),
        ("9abc", "9abc"),
    ],
)
def test_ut_adm_04_accepted_values_are_normalized(raw: str, expected: str) -> None:
    assert normalize_login_id(raw) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "required"),
        ("   ", "required"),
        ("ab", "too_short"),  # 2 文字
        ("a" * 51, "too_long"),
        ("-abc", "format"),  # 先頭が記号
        (".abc", "format"),
        ("ab c", "format"),  # 内部の空白
        ("a\u200bbc", "format"),  # ゼロ幅スペース
        ("abc\u200b", "format"),
        ("ab\x00c", "format"),  # 制御文字
        ("ab\nc", "format"),
        ("ab@c", "format"),  # 記号入り
        ("あいう", "format"),
        ("ab/c", "format"),
    ],
)
def test_ut_adm_04_rejected_values(raw: str, reason: str) -> None:
    with pytest.raises(InvalidLoginId) as ei:
        normalize_login_id(raw)
    assert ei.value.reason == reason


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-05 管理ログインの識別子と閾値（DS-DEC-110）
# ══════════════════════════════════════════════════════════════════════════


def test_ut_adm_05_identifier_is_sha256_of_the_normalized_login_id() -> None:
    a = admin_login_identifier(normalize_login_id("staff-a"))
    b = admin_login_identifier(normalize_login_id("ＳＴＡＦＦ-ａ"))
    c = admin_login_identifier(normalize_login_id("STAFF-A"))
    assert a == b == c and re.fullmatch(r"[0-9a-f]{64}", a)
    assert a == hash_token("staff-a"), "SHA-256 の 16 進。平文の login_id は保存しない"
    assert a != admin_login_identifier("staff-b")


def test_ut_adm_05_thresholds() -> None:
    assert (ID_LOCK_THRESHOLD, IP_LIMIT_THRESHOLD) == (5, 10)
    assert [is_id_locked(n) for n in (4, 5, 6)] == [False, True, True]
    assert [is_ip_limited(n) for n in (9, 10, 11)] == [False, True, True]


async def test_ut_adm_05_only_failed_staff_rows_are_counted(staff_db: AsyncEngine) -> None:
    ident = admin_login_identifier("staff-a")
    since = NOW - timedelta(minutes=15)

    async def add(subject_type: SubjectType, identifier: str, *, ok: bool, ip: str, at: datetime):
        async with staff_db.begin() as conn:
            await conn.execute(
                insert(LoginAttempt).values(
                    subject_type=subject_type,
                    identifier=identifier,
                    succeeded=ok,
                    ip=ip,
                    at=at,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

    recent = NOW - timedelta(minutes=1)
    for _ in range(4):
        await add(SubjectType.staff, ident, ok=False, ip="203.0.113.1", at=recent)
    for _ in range(3):  # 会員の行・成功の行・古い行は数えない
        await add(SubjectType.member, ident, ok=False, ip="203.0.113.1", at=recent)
    await add(SubjectType.staff, ident, ok=True, ip="203.0.113.1", at=recent)
    await add(SubjectType.staff, ident, ok=False, ip="203.0.113.1", at=NOW - timedelta(minutes=16))

    async with AsyncSession(staff_db) as session:
        by_id = await attempts_repo.count_failures_by_identifier(
            session, SubjectType.staff, ident, since
        )
        by_ip = await attempts_repo.count_failures_by_ip(
            session, SubjectType.staff, "203.0.113.1", since
        )
    assert by_id == by_ip == 4
    assert not is_id_locked(by_id)
    await add(SubjectType.staff, ident, ok=False, ip="203.0.113.1", at=recent)
    async with AsyncSession(staff_db) as session:
        assert is_id_locked(
            await attempts_repo.count_failures_by_identifier(
                session, SubjectType.staff, ident, since
            )
        )


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-06 管理者がいないときのダミー検証（DS-DEC-110）
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("exists", [True, False])
async def test_ut_adm_06_verification_runs_once_with_or_without_the_staff(
    staff_db: AsyncEngine, monkeypatch: pytest.MonkeyPatch, exists: bool
) -> None:
    if exists:
        await _add_staff(staff_db, 1)
    calls: list[str | None] = []

    async def fake_verify(encoded: str | None, plain: str) -> bool:
        calls.append(encoded)
        return False

    monkeypatch.setattr(passwords, "verify_password_async", fake_verify)
    async with AsyncSession(staff_db) as session:
        with pytest.raises(AppError) as ei:
            await admin_auth.login(
                session,
                login_id="staff-a",
                password="whatever-password",  # pragma: allowlist secret
                request=_request(),
                old_session_token=None,
            )
    assert (ei.value.status, ei.value.code) == (401, "invalid_credentials")
    assert len(calls) == 1
    assert calls[0] == ("$argon2id$dummy" if exists else passwords.dummy_hash())
    async with AsyncSession(staff_db) as session:
        rows = (
            await session.execute(select(LoginAttempt.subject_type, LoginAttempt.succeeded))
        ).all()
    assert [(r.subject_type, r.succeeded) for r in rows] == [(SubjectType.staff, False)]


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-07 更新前の値の照合（DS-PRC-055）
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("expected", "current"),
    [(5, 5), (0, 0), (True, True), ("0.10", "0.10"), ("", ""), (None, None), (550, 550)],
)
def test_ut_adm_07_exact_match_passes(expected: Any, current: Any) -> None:
    ensure_expected("field", expected, current)


@pytest.mark.parametrize(
    ("expected", "current"),
    [
        (5, 6),
        (True, 1),
        (1, True),
        (0, False),
        (False, 0),
        ("0.10", 0.1),
        (0.1, "0.10"),
        ("550", 550),
        (550, "550"),
        (None, 0),
        (0, None),
        (5, 5.0),
    ],
)
def test_ut_adm_07_mismatch_including_type_is_409_stale_data(expected: Any, current: Any) -> None:
    with pytest.raises(AppError) as ei:
        ensure_expected("stock", expected, current)
    err = ei.value
    assert (err.status, err.code) == (409, "stale_data")
    assert err.to_body() == {"code": "stale_data", "field": "stock", "current": current}


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-17 監査ログの禁止キー（DS-PRC-054）
# ══════════════════════════════════════════════════════════════════════════

_FORBIDDEN = [
    "email",
    "name",
    "phone",
    "address",
    "postal_code",
    "pickup_code",
    "password",
    "token",
    "guest_email",
    "ship_name",
    "ship_postal_code",
    "ship_anything",
    "EMAIL",
]


def test_ut_adm_17_forbidden_key_set_is_the_nine_in_the_design() -> None:
    assert FORBIDDEN_DETAIL_KEYS == {
        "email",
        "name",
        "phone",
        "address",
        "postal_code",
        "pickup_code",
        "password",
        "token",
        "guest_email",
    }


@pytest.mark.parametrize("key", _FORBIDDEN)
async def test_ut_adm_17_forbidden_keys_raise_even_when_nested(
    staff_db: AsyncEngine, key: str
) -> None:
    staff = CurrentStaff(id=1, login_id="staff-a", role="staff")
    for detail in (
        {key: "x"},
        {"before": {"a": 1}, "after": {key: "x"}},
        {"items": [{"sku": "S"}, {"deep": [{key: 1}]}]},
    ):
        assert find_forbidden_key(detail) is not None
        async with AsyncSession(staff_db) as session:
            with pytest.raises(RuntimeError):
                await write_admin_audit(
                    session,
                    staff,
                    action="admin.stock.set",
                    target_type="variant",
                    target_id="1",
                    detail=detail,
                )
            await session.rollback()
    async with AsyncSession(staff_db) as session:
        assert (await session.execute(select(AuditLog))).first() is None, "何も書かれない"


async def test_ut_adm_17_allowed_keys_are_written_as_staff_actor(staff_db: AsyncEngine) -> None:
    staff = CurrentStaff(id=7, login_id="staff-a", role="staff")
    detail = {"sku": "GU-029-BK-M", "before": 0, "after": 5, "restock_waiting": 2}
    async with AsyncSession(staff_db) as session:
        await write_admin_audit(
            session,
            staff,
            action="admin.stock.set",
            target_type="variant",
            target_id="29",
            detail=detail,
        )
        await write_admin_audit(
            session, staff, action="admin.logout", target_type="staff", target_id="7"
        )
        await session.commit()
    async with AsyncSession(staff_db) as session:
        rows = (await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    assert len(rows) == 2
    first, second = rows
    assert first.actor_type is ActorType.staff and first.actor_id == 7
    assert (first.action, first.target_type, first.target_id) == (
        "admin.stock.set",
        "variant",
        "29",
    )
    assert first.detail == detail
    assert second.detail is None


# ══════════════════════════════════════════════════════════════════════════
# UT-ADM-18 監査ログの改変が無いこと（DS-DEC-120。ソースの静的検査）
# ══════════════════════════════════════════════════════════════════════════

_MUTATION_PATTERNS = [
    re.compile(r"\b(?:update|delete)\(\s*AuditLog\b"),
    re.compile(r"\b(?:update|delete)\(\s*AuditLog\.__table__"),
    re.compile(r"\bUPDATE\s+`?audit_logs\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+`?audit_logs\b", re.IGNORECASE),
]


def find_audit_mutations(source: str) -> list[int]:
    """`audit_logs`／`AuditLog` への UPDATE・DELETE らしき記述の行番号（1 始まり）。"""
    lines = []
    for number, line in enumerate(source.splitlines(), start=1):
        if any(p.search(line) for p in _MUTATION_PATTERNS):
            lines.append(number)
    return lines


def test_ut_adm_18_scanner_detects_violations() -> None:
    bad = [
        "await session.execute(update(AuditLog).values(action='x'))",
        "await session.execute(delete(AuditLog).where(AuditLog.id == 1))",
        'await conn.execute(text("UPDATE audit_logs SET action = 1"))',
        'await conn.execute(text("delete from `audit_logs` where 1=1"))',
    ]
    for line in bad:
        assert find_audit_mutations(line) == [1], line
    good = (
        "session.add(AuditLog(actor_type=ActorType.staff))\n"
        "select(AuditLog).where(AuditLog.id == 1)"
    )
    assert find_audit_mutations(good) == []


def test_ut_adm_18_app_source_never_updates_or_deletes_audit_logs() -> None:
    root = Path(app_package.__file__).parent
    files = sorted(root.rglob("*.py"))
    assert len(files) > 50, "走査の対象が空振りしていない"
    sources = {f: f.read_text(encoding="utf-8") for f in files}
    assert any("AuditLog" in s for s in sources.values())
    violations = [
        f"{f.relative_to(root.parent)}:{n}"
        for f, source in sources.items()
        for n in find_audit_mutations(source)
    ]
    assert violations == [], f"audit_logs を UPDATE・DELETE してはいけません: {violations}"


# ══════════════════════════════════════════════════════════════════════════
# ページ送りの型（schemas/admin_common.py。C-2・C-3 が使う契約）
# ══════════════════════════════════════════════════════════════════════════


def test_page_params_offsets_and_defaults() -> None:
    params = PageParams(page=3, per_page=20)
    assert (params.limit, params.offset) == (20, 40)
    assert PageParams(page=1, per_page=100).offset == 0
    assert DEFAULT_PER_PAGE == 20 and INT32_MAX == 2_147_483_647
    assert page_params(page=2, per_page=50) == PageParams(page=2, per_page=50)


def test_build_page_has_more_and_empty_page() -> None:
    page = build_page(["a", "b"], PageParams(page=1, per_page=2), total=5)
    assert page.model_dump() == {
        "items": ["a", "b"],
        "page": 1,
        "per_page": 2,
        "total": 5,
        "has_more": True,
    }
    assert build_page(["e"], PageParams(page=3, per_page=2), total=5).has_more is False
    empty = build_page([], PageParams(page=1, per_page=20), total=0)
    assert empty.items == [] and empty.has_more is False and empty.total == 0
