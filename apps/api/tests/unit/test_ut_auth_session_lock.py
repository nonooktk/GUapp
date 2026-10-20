"""UT-SESS-02・UT-LOCK-01〜03・UT-AUTH-11（セッション上限・ログインの数え方・ダミー検証）。

設計仕様書 P2 追補b DS-DEC-70・71・72、テスト設計書 P2 追補b 5.1。DB は SQLite のファイル DB
（ロックの挙動そのものは MySQL の結合テスト IT-032 で確かめる）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import passwords
from app.models import AuthSession, Base, LoginAttempt, Member, SubjectType
from app.repositories import login_attempts as attempts_repo
from app.repositories import sessions as sessions_repo
from app.services.auth import (
    EMAIL_LOCK_THRESHOLD,
    IP_LIMIT_THRESHOLD,
    LOGIN_WINDOW,
    is_email_locked,
    is_ip_limited,
    normalize_ip,
)
from app.services.email_normalize import login_identifier
from tests.conftest import TEST_INTERNAL_TOKEN
from tests.recording_mail import RecordingMailAdapter

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}
NOW = datetime(2026, 10, 20, 12, 0, 0)
PLAIN = "correct-horse-battery-1"  # pragma: allowlist secret
WRONG_PW = "wrong-pw-1"  # pragma: allowlist secret


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncEngine:
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def db(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _add_member(engine: AsyncEngine, email: str, *, password_hash: str = "x") -> int:
    async with engine.begin() as conn:
        result = await conn.execute(
            insert(Member).values(
                email=email, password_hash=password_hash, name="テスト", personalize_opt_in=False
            )
        )
        return int(result.inserted_primary_key[0])


async def _add_sessions(
    db: async_sessionmaker[AsyncSession], member_id: int, count: int, *, prefix: str
) -> list[int]:
    """expires_at が古い順に id が増える有効なセッションを作る。"""
    async with db() as s:
        for i in range(count):
            s.add(
                AuthSession(
                    token_hash=f"{prefix}{i:02d}".ljust(64, "0"),
                    subject_type=SubjectType.member,
                    subject_id=member_id,
                    expires_at=NOW + timedelta(hours=1, minutes=i),
                    last_seen_at=NOW,
                )
            )
        await s.commit()
        return list(
            (
                await s.execute(
                    select(AuthSession.id)
                    .where(AuthSession.subject_id == member_id)
                    .order_by(AuthSession.id)
                )
            )
            .scalars()
            .all()
        )


# ── UT-SESS-02 セッション上限の削除対象 ───────────────────────────────────


@pytest.mark.parametrize(("existing", "evicted"), [(0, 0), (9, 0), (10, 1), (12, 3)])
def test_ut_sess_02_ids_to_evict(existing: int, evicted: int) -> None:
    ids = list(range(100, 100 + existing))
    assert sessions_repo.ids_to_evict(ids, 10) == ids[:evicted]


@pytest.mark.parametrize(("existing", "evicted"), [(9, 0), (10, 1), (12, 3)])
async def test_ut_sess_02_evicts_oldest_and_keeps_other_members(
    db: async_sessionmaker[AsyncSession], engine: AsyncEngine, existing: int, evicted: int
) -> None:
    me = await _add_member(engine, "me@example.com")
    other = await _add_member(engine, "other@example.com")
    mine = await _add_sessions(db, me, existing, prefix="a")
    others = await _add_sessions(db, other, 10, prefix="b")

    async with db() as s:
        assert await sessions_repo.evict_oldest_for_new_session(s, me, NOW) == evicted
        await sessions_repo.insert_session(
            s, member_id=me, token_hash="n" * 64, now=NOW, expires_at=NOW + timedelta(hours=24)
        )
        await s.commit()

    async with db() as s:
        remaining = set(
            (await s.execute(select(AuthSession.id).where(AuthSession.subject_id == me)))
            .scalars()
            .all()
        )
        assert not (set(mine[:evicted]) & remaining), "消すのは古い順"
        assert set(mine[evicted:]) <= remaining
        assert await sessions_repo.count_active_for_member(s, me, NOW) == min(existing + 1, 10)
        other_ids = set(
            (await s.execute(select(AuthSession.id).where(AuthSession.subject_id == other)))
            .scalars()
            .all()
        )
        assert other_ids == set(others), "他の会員のセッションは対象外"


async def test_ut_sess_02_expired_rows_are_deleted_not_counted(
    db: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    me = await _add_member(engine, "me@example.com")
    async with db() as s:
        s.add(
            AuthSession(
                token_hash="e" * 64,
                subject_type=SubjectType.member,
                subject_id=me,
                expires_at=NOW,  # ちょうど現在は無効
                last_seen_at=NOW - timedelta(hours=24),
            )
        )
        await s.commit()
    async with db() as s:
        await sessions_repo.delete_expired_for_member(s, me, NOW)
        await s.commit()
        assert (await s.execute(select(AuthSession.id))).first() is None


# ── UT-LOCK-01〜03 ログインの数え方 ───────────────────────────────────────


async def _record(
    db: async_sessionmaker[AsyncSession],
    identifier: str,
    *,
    at: datetime,
    ip: str = "203.0.113.1",
    succeeded: bool = False,
    subject_type: SubjectType = SubjectType.member,
) -> None:
    async with db() as s:
        await attempts_repo.record(s, subject_type, identifier, succeeded=succeeded, ip=ip, at=at)
        await s.commit()


def test_ut_lock_thresholds() -> None:
    assert (EMAIL_LOCK_THRESHOLD, IP_LIMIT_THRESHOLD) == (5, 30)
    assert [is_email_locked(n) for n in (4, 5, 6)] == [False, True, True]
    assert [is_ip_limited(n) for n in (29, 30, 31)] == [False, True, True]
    assert LOGIN_WINDOW == timedelta(minutes=15)


@pytest.mark.parametrize(
    ("failures", "age", "locked"),
    [
        (4, timedelta(minutes=14, seconds=59), False),
        (5, timedelta(minutes=14, seconds=59), True),
        (5, timedelta(minutes=15, seconds=1), False),
        (5, timedelta(minutes=15), False),  # ちょうど 15 分は窓の外（at > since）
        (6, timedelta(seconds=1), True),
    ],
)
async def test_ut_lock_01_email_lock_window(
    db: async_sessionmaker[AsyncSession], failures: int, age: timedelta, locked: bool
) -> None:
    identifier = login_identifier("lock@example.com")
    for _ in range(failures):
        await _record(db, identifier, at=NOW - age)
    async with db() as s:
        count = await attempts_repo.count_failures_by_identifier(
            s, SubjectType.member, identifier, NOW - LOGIN_WINDOW
        )
    assert is_email_locked(count) is locked


@pytest.mark.parametrize(("failures", "limited"), [(29, False), (30, True)])
async def test_ut_lock_02_ip_limit_ignores_other_ips(
    db: async_sessionmaker[AsyncSession], failures: int, limited: bool
) -> None:
    for i in range(failures):
        await _record(db, login_identifier(f"u{i}@example.com"), at=NOW - timedelta(minutes=1))
    for i in range(50):
        await _record(db, login_identifier(f"v{i}@example.com"), at=NOW, ip="198.51.100.9")
    async with db() as s:
        count = await attempts_repo.count_failures_by_ip(
            s, SubjectType.member, "203.0.113.1", NOW - LOGIN_WINDOW
        )
    assert count == failures
    assert is_ip_limited(count) is limited


async def test_ut_lock_03_counts_only_failures_of_same_type_and_identifier(
    db: async_sessionmaker[AsyncSession],
) -> None:
    target = login_identifier("t@example.com")
    when = NOW - timedelta(minutes=1)
    for _ in range(3):
        await _record(db, target, at=when)  # 数える（失敗・member・同じ識別子）
    await _record(db, target, at=when, succeeded=True)  # 成功は数えない
    await _record(db, target, at=when, subject_type=SubjectType.staff)  # staff は数えない
    await _record(db, login_identifier("x@example.com"), at=when)  # 別の識別子
    async with db() as s:
        by_identifier = await attempts_repo.count_failures_by_identifier(
            s, SubjectType.member, target, NOW - LOGIN_WINDOW
        )
        by_ip = await attempts_repo.count_failures_by_ip(
            s, SubjectType.member, "203.0.113.1", NOW - LOGIN_WINDOW
        )
    assert by_identifier == 3
    assert by_ip == 4, "同じ IP の member の失敗（識別子違いも含む）。成功と staff は除く"


async def test_failures_are_deleted_by_identifier_only(
    db: async_sessionmaker[AsyncSession],
) -> None:
    target = login_identifier("t@example.com")
    await _record(db, target, at=NOW)
    await _record(db, target, at=NOW, succeeded=True)
    await _record(db, login_identifier("x@example.com"), at=NOW)
    async with db() as s:
        await attempts_repo.delete_failures_by_identifier(s, SubjectType.member, target)
        await s.commit()
        rows = (await s.execute(select(LoginAttempt.identifier, LoginAttempt.succeeded))).all()
    assert sorted((r.identifier == target, r.succeeded) for r in rows) == [
        (False, False),
        (True, True),
    ]


async def test_old_attempts_cleanup_deletes_only_older_rows_up_to_limit(
    db: async_sessionmaker[AsyncSession],
) -> None:
    cutoff = NOW - timedelta(hours=24)
    for i in range(5):
        await _record(db, login_identifier(f"old{i}@example.com"), at=cutoff - timedelta(hours=1))
    await _record(db, login_identifier("new@example.com"), at=cutoff + timedelta(minutes=1))
    async with db() as s:
        assert await attempts_repo.delete_older_than(s, cutoff, limit=3) == 3
        await s.commit()
    async with db() as s:
        assert await attempts_repo.delete_older_than(s, cutoff, limit=1000) == 2
        await s.commit()
        remaining = (await s.execute(select(LoginAttempt.id))).scalars().all()
    assert len(remaining) == 1


def test_normalize_ip_never_exceeds_the_column_and_unknown_is_grouped() -> None:
    assert normalize_ip("203.0.113.1") == "203.0.113.1"
    assert normalize_ip(" 2001:DB8:0:0:0:0:0:1 ") == "2001:db8::1"
    assert normalize_ip("x" * 200) == "unknown"
    assert len(normalize_ip("2001:db8:ffff:ffff:ffff:ffff:ffff:ffff")) <= 45


# ── UT-AUTH-11 会員がいないときのダミー検証 ───────────────────────────────


async def test_ut_auth_11_dummy_hash_is_verified_when_member_is_missing(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[[FastAPI], httpx.AsyncClient],
    engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_mail: RecordingMailAdapter,
) -> None:
    member_hash = passwords.hash_password(PLAIN)
    await _add_member(engine, "exists@example.com", password_hash=member_hash)
    app = make_app(DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    recording_mail.install(app)
    client = client_factory(app)

    calls: list[str | None] = []
    original = passwords.verify_password_async

    async def spy(encoded: str | None, plain: str) -> bool:
        calls.append(encoded)
        return await original(encoded, plain)

    monkeypatch.setattr(passwords, "verify_password_async", spy)

    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "exists@example.com", "password": WRONG_PW},
        headers=HEADERS,
    )
    assert res.status_code == 401
    res_missing = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": WRONG_PW},
        headers=HEADERS,
    )
    assert res_missing.status_code == 401
    assert res_missing.json() == res.json() == {"code": "invalid_credentials"}

    assert calls == [member_hash, passwords.dummy_hash()], "どちらも検証が 1 回（なしはダミー）"

    # ダミーの元の文字列で入力されても、会員がいなければ成功にしない
    calls.clear()
    res_dummy = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": passwords._DUMMY_PLAIN},
        headers=HEADERS,
    )
    assert res_dummy.status_code == 401
    assert calls == [passwords.dummy_hash()]
