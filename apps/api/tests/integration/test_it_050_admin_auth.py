"""IT-050・050a・050b: 管理認証 API（DS-API-050・050a・050b）の結合テスト。MySQL 必須。

テスト設計書 P2 追補c 4.1 / 設計仕様書 P2 追補c 4.1・4.6・5.6・7.3。

- 管理者は `admin_helpers.create_staff` で作る（seed の `demo-staff` を使うのは IT-050-01 だけ）
- 期限・ロックの境界は DB の時刻列（`login_attempts.at`）を書き換えて作る（待たない）
- 同時実行（IT-050-10）は MySQL・`alembic upgrade head`・プール 20 以上で行い、同時に処理中の
  件数の最大値が 2 以上であることを assert する（本編 1.4 #1〜#5）。10 回の有効試行を通す
- パスワードはすべてテスト用のダミー値
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import seed_data
from app.core import passwords
from app.core.session import hash_token
from app.repositories import staff as staff_repo
from app.services import admin_auth as admin_auth_service
from app.services.admin_auth import admin_login_identifier
from tests.integration import admin_helpers as ah
from tests.integration import p2b_helpers as ph
from tests.recording_mail import RecordingMailAdapter

PREFIX = "$argon2id$v=19$m=19456,t=2,p=1$"
SEED_STAFF_ID = seed_data.STAFF[0].login_id
SEED_STAFF_PW = seed_data.DEMO_STAFF_PASSWORD


# ── フィクスチャ・ヘルパー ───────────────────────────────────────────────────


@pytest.fixture
def admin_app(
    make_app: Callable[..., FastAPI],
    test_database_url: str,
    migrated_schema: str,
    recording_mail: RecordingMailAdapter,
) -> FastAPI:
    app = make_app(APP_ENV="test", DATABASE_URL=test_database_url)
    recording_mail.install(app)
    return app


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


async def sql(engine: AsyncEngine, statement: str, **params: Any) -> list[Any]:
    """SELECT は行のリスト、それ以外は空リスト（書き込みは COMMIT する）。"""
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return list(result.all()) if result.returns_rows else []


async def scalar(engine: AsyncEngine, statement: str, **params: Any) -> Any:
    return (await sql(engine, statement, **params))[0][0]


async def staff_sessions(engine: AsyncEngine, staff_id: int | None = None) -> int:
    if staff_id is None:
        return int(await scalar(engine, "SELECT COUNT(*) FROM sessions WHERE subject_type='staff'"))
    return int(
        await scalar(
            engine,
            "SELECT COUNT(*) FROM sessions WHERE subject_type='staff' AND subject_id=:i",
            i=staff_id,
        )
    )


async def me(client: httpx.AsyncClient, token: str | None) -> httpx.Response:
    return await client.get(ah.ADMIN_ME_PATH, headers=ah.admin_headers(token))


async def fail(
    client: httpx.AsyncClient, login_id: str, ip: str, times: int, password: str | None = None
) -> list[int]:
    codes = []
    for _ in range(times):
        res = await ah.login_admin(client, login_id, password or ah.WRONG_ADMIN_PASSWORD, ip=ip)
        codes.append(res.status_code)
    return codes


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
# IT-050 管理ログイン
# ══════════════════════════════════════════════════════════════════════════


async def test_it_050_01_seed_staff_login_creates_session_and_audit(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    res = await ah.login_admin(client, SEED_STAFF_ID, SEED_STAFF_PW, ip="203.0.113.50")
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"session_token", "staff"}
    assert len(body["session_token"]) == 43
    assert body["staff"] == {"login_id": SEED_STAFF_ID, "role": "staff"}
    assert "id" not in body["staff"] and "password_hash" not in res.text
    assert res.headers["cache-control"] == "no-store"

    staff_id = await scalar(engine, "SELECT id FROM staff WHERE login_id=:l", l=SEED_STAFF_ID)
    rows = await sql(
        engine,
        "SELECT token_hash, subject_type, subject_id, expires_at, last_seen_at FROM sessions",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.token_hash == hash_token(body["session_token"]) and len(row.token_hash) == 64
    assert row.subject_type == "staff" and row.subject_id == staff_id
    assert abs((row.expires_at - ah.utcnow()) - timedelta(hours=8)) < timedelta(seconds=5)
    assert abs(row.last_seen_at - ah.utcnow()) < timedelta(seconds=5), "作成時刻のまま"

    audits = await sql(
        engine,
        "SELECT actor_type, actor_id, action, target_type, target_id, detail FROM audit_logs",
    )
    assert len(audits) == 1
    a = audits[0]
    assert (a.actor_type, a.actor_id, a.action) == ("staff", staff_id, "admin.login")
    assert (a.target_type, a.target_id) == ("staff", str(staff_id))
    assert json.loads(a.detail) == {"ip": "203.0.113.0"}, "丸めた IP だけ"
    # 成功の記録（失敗行はなし）
    attempts = await sql(engine, "SELECT subject_type, succeeded, identifier FROM login_attempts")
    assert len(attempts) == 1 and attempts[0].subject_type == "staff" and attempts[0].succeeded
    assert attempts[0].identifier == admin_login_identifier(SEED_STAFF_ID)
    assert (await me(client, body["session_token"])).status_code == 200


async def test_it_050_02_wrong_password_and_unknown_id_are_the_same_401(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await ah.create_staff(engine, "staff-a")
    wrong = await ah.login_admin(client, "staff-a", ah.WRONG_ADMIN_PASSWORD)
    unknown = await ah.login_admin(client, "nobody-here", ah.ADMIN_PASSWORD)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"code": "invalid_credentials"}
    assert wrong.content == unknown.content
    rows = await sql(
        engine, "SELECT subject_type, succeeded, identifier FROM login_attempts ORDER BY id"
    )
    assert [(r.subject_type, bool(r.succeeded)) for r in rows] == [("staff", False)] * 2
    assert {r.identifier for r in rows} == {
        admin_login_identifier("staff-a"),
        admin_login_identifier("nobody-here"),
    }
    for plain in ("staff-a", "nobody-here"):
        assert (
            await scalar(engine, "SELECT COUNT(*) FROM login_attempts WHERE identifier=:i", i=plain)
            == 0
        )
    assert await staff_sessions(engine) == 0
    assert await scalar(engine, "SELECT COUNT(*) FROM audit_logs") == 0


async def test_it_050_03_id_lock_after_five_failures_even_for_unknown_id(
    client: httpx.AsyncClient, engine: AsyncEngine, recording_mail: RecordingMailAdapter
) -> None:
    await ah.create_staff(engine, "staff-a")
    await ah.create_staff(engine, "staff-b", ah.OTHER_ADMIN_PASSWORD)

    # 4 回失敗したあとの成功は 200
    assert await fail(client, "staff-a", "203.0.113.11", 4) == [401] * 4
    ok = await ah.login_admin(client, "staff-a", ip="203.0.113.11")
    assert ok.status_code == 200, ok.text

    # 5 回目までは 401、6 回目は正しいパスワードでも 403
    assert await fail(client, "staff-b", "203.0.113.12", 5) == [401] * 5
    locked = await ah.login_admin(client, "staff-b", ah.OTHER_ADMIN_PASSWORD, ip="203.0.113.12")
    assert locked.status_code == 403 and locked.json() == {"code": "account_locked"}

    # 未登録の ID でも同じ（存在を漏らさない）
    assert await fail(client, "ghost-user", "203.0.113.13", 5) == [401] * 5
    ghost = await ah.login_admin(client, "ghost-user", ip="203.0.113.13")
    assert ghost.status_code == 403 and ghost.json() == {"code": "account_locked"}
    assert recording_mail.sent == [], "ロック通知のメールは送らない"


async def test_it_050_04_lock_window_boundary(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await ah.create_staff(engine, "staff-a")
    assert await fail(client, "staff-a", "203.0.113.21", 5) == [401] * 5

    async def shift_attempts(seconds: int) -> None:
        await sql(
            engine,
            "UPDATE login_attempts SET `at` = DATE_SUB(UTC_TIMESTAMP(), INTERVAL :s SECOND)",
            s=seconds,
        )

    await shift_attempts(15 * 60 - 1)  # 14 分 59 秒前
    res = await ah.login_admin(client, "staff-a", ip="203.0.113.21")
    assert res.status_code == 403
    await shift_attempts(15 * 60 + 1)  # 15 分 1 秒前
    res = await ah.login_admin(client, "staff-a", ip="203.0.113.21")
    assert res.status_code == 200, res.text
    left = await scalar(
        engine,
        "SELECT COUNT(*) FROM login_attempts WHERE succeeded = 0",
    )
    assert left == 0, "成功で失敗行が消える"


async def test_it_050_05_ip_limit_after_ten_failures_and_member_rows_do_not_count(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await ah.create_staff(engine, "staff-a")
    ip = "203.0.113.31"
    # 10 個の異なる ID に失敗を記録（ID 単位のロックには掛からない）
    for i in range(10):
        res = await ah.login_admin(client, f"ghost-{i:02d}", ah.WRONG_ADMIN_PASSWORD, ip=ip)
        assert res.status_code == 401, (i, res.text)
    eleventh = await ah.login_admin(client, "ghost-10", ah.WRONG_ADMIN_PASSWORD, ip=ip)
    assert eleventh.status_code == 429 and eleventh.json() == {"code": "rate_limited"}
    assert eleventh.headers["retry-after"] == "900"
    # 正しい管理者の正しいパスワードも 429（パスワードの検証より前に判定する）
    correct = await ah.login_admin(client, "staff-a", ip=ip)
    assert correct.status_code == 429 and correct.headers["retry-after"] == "900"
    # 別の IP からは通る
    assert (await ah.login_admin(client, "staff-a", ip="203.0.113.32")).status_code == 200

    # 同じ IP の会員の失敗行（29 件）は数えない
    other_ip = "203.0.113.33"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO login_attempts (subject_type, identifier, succeeded, ip, `at`)"
                " VALUES ('member', :i, 0, :ip, :a)"
            ),
            [{"i": hash_token(f"member-{n}"), "ip": other_ip, "a": ah.utcnow()} for n in range(29)],
        )
    assert (
        await scalar(engine, "SELECT COUNT(*) FROM login_attempts WHERE ip=:ip", ip=other_ip) == 29
    )
    assert (await ah.login_admin(client, "staff-a", ip=other_ip)).status_code == 200


async def test_it_050_06_relogin_deletes_old_session_and_issues_a_new_one(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    staff_id = await ah.create_staff(engine, "staff-a")
    old = await ah.login_admin_ok(client, "staff-a")
    res = await ah.login_admin(client, "staff-a", token=old)
    assert res.status_code == 200
    new = res.json()["session_token"]
    assert new != old
    hashes = {r[0] for r in await sql(engine, "SELECT token_hash FROM sessions")}
    assert hashes == {hash_token(new)}, "旧トークンの行が消え、新しい行ができる"
    assert (await me(client, old)).status_code == 401
    assert (await me(client, new)).status_code == 200
    assert await staff_sessions(engine, staff_id) == 1


async def test_it_050_06b_old_token_of_a_member_session_is_not_deleted(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await ah.create_staff(engine, "staff-a")
    member_id = await ph.member_id_of(engine)
    member_token = await ph.make_session(engine, member_id)
    res = await ah.login_admin(client, "staff-a", token=member_token)
    assert res.status_code == 200
    members = await scalar(
        engine,
        "SELECT COUNT(*) FROM sessions WHERE subject_type='member' AND subject_id=:i",
        i=member_id,
    )
    assert members == 1, "提示された古い値が会員の行でも、会員の行は消さない"


async def test_it_050_07_up_to_three_concurrent_sessions_oldest_evicted(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    staff_id = await ah.create_staff(engine, "staff-a")
    tokens = []
    counts = []
    for _ in range(4):
        tokens.append(await ah.login_admin_ok(client, "staff-a"))
        counts.append(await staff_sessions(engine, staff_id))
    assert counts == [1, 2, 3, 3]
    assert (await me(client, tokens[0])).status_code == 401, "最も古い行だけが消える"
    for t in tokens[1:]:
        assert (await me(client, t)).status_code == 200


@pytest.mark.parametrize(
    ("body", "bad_field"),
    [
        ({"login_id": "ab", "password": "x"}, "login_id"),
        ({"login_id": "a" * 51, "password": "x"}, "login_id"),
        ({"login_id": "", "password": "x"}, "login_id"),
        ({"login_id": "a b", "password": "x"}, "login_id"),
        ({"login_id": "staff-a"}, "password"),
        ({"login_id": "staff-a", "password": ""}, "password"),
        ({"login_id": "staff-a", "password": "p" * 129}, "password"),
        ({"password": "x"}, "login_id"),
    ],
)
async def test_it_050_08_validation_errors_are_400_and_not_recorded(
    client: httpx.AsyncClient, engine: AsyncEngine, body: dict[str, Any], bad_field: str
) -> None:
    await ah.create_staff(engine, "staff-a")
    res = await client.post(ah.ADMIN_LOGIN_PATH, json=body, headers=ah.admin_headers())
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "validation_error"
    assert bad_field in {f["name"] for f in res.json()["fields"]}
    assert await scalar(engine, "SELECT COUNT(*) FROM login_attempts") == 0


async def test_it_050_08b_fullwidth_and_uppercase_login_id_is_normalized(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await ah.create_staff(engine, "staff-a")
    for raw in ("ＳＴＡＦＦ-ａ", "STAFF-A", "  Staff-A  "):
        res = await ah.login_admin(client, raw)
        assert res.status_code == 200, (raw, res.text)
        assert res.json()["staff"]["login_id"] == "staff-a"


async def test_it_050_09_old_parameter_hash_is_rehashed_on_login(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    legacy = PasswordHasher(time_cost=1, memory_cost=19456, parallelism=1).hash(ah.ADMIN_PASSWORD)
    assert "t=1" in legacy
    staff_id = await ah.create_staff(engine, "staff-old", password_hash=legacy)
    assert (await ah.login_admin(client, "staff-old")).status_code == 200
    new_hash = await scalar(engine, "SELECT password_hash FROM staff WHERE id=:i", i=staff_id)
    assert new_hash.startswith(PREFIX) and new_hash != legacy
    assert (await ah.login_admin(client, "staff-old")).status_code == 200


async def test_it_050_10_same_staff_4_parallel_logins_with_1_wrong(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """5.6・本編 1.4: 同じ管理者で 4 並列の正しいログイン ＋ 誤パスワード 1 本（10 回試行）。

    G-16 以降、同じ ID で同時に検証まで進めるのは上限（5 本）までなので、1 回は 5 本にする
    （以前は 13 本を一度に送っていた）。セッションの上限は 3 件なので、4 本でも超過を確かめられる。
    """
    caplog.set_level(logging.WARNING, logger="app.services.admin_auth")
    staff_id = await ah.create_staff(engine, "staff-conc")
    # 行ロックの取得から COMMIT までの窓を 30ms 広げる（待っている件数も数える）
    inflight = track_inflight(monkeypatch, staff_repo, "lock_for_login", hold=0.03)
    for round_no in range(10):
        await sql(engine, "DELETE FROM sessions")
        await sql(engine, "DELETE FROM login_attempts")
        inflight.max = 0
        jobs = [
            ah.login_admin(client, "staff-conc", ip=f"203.0.113.{100 + i}") for i in range(4)
        ] + [ah.login_admin(client, "staff-conc", ah.WRONG_ADMIN_PASSWORD, ip="203.0.114.1")]
        results = await asyncio.gather(*jobs)
        assert inflight.max >= 2, f"同時性が成立していない（無効試行）: {inflight.max}"
        good, bad = results[:4], results[4:]
        assert all(r.status_code == 200 for r in good), [(r.status_code, r.text) for r in good]
        assert all(r.status_code == 401 for r in bad), [(r.status_code, r.text) for r in bad]
        assert len({r.json()["session_token"] for r in good}) == 4
        active = await staff_sessions(engine, staff_id)
        assert active <= 3, f"round {round_no}: 有効なセッションが {active} 件"
    retries = [r for r in caplog.records if "ロック競合" in r.getMessage()]
    print(f"\nIT-050-10: 4+1 本 inflight_max={inflight.max} 再試行={len(retries)} 回")


def count_verifications(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """argon2 の照合（`verify_password_async`）が呼ばれた回数を数える。"""
    calls = [0]
    original = passwords.verify_password_async

    async def counting(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(passwords, "verify_password_async", counting)
    return calls


async def test_it_050_13_parallel_wrong_passwords_never_verify_more_than_the_id_threshold(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-16: 同じ ID へ誤ったパスワードを 12 本同時に送っても、照合まで進むのは 5 本以下。"""
    await ah.create_staff(engine, "staff-burst")
    claims = track_inflight(monkeypatch, admin_auth_service, "claim_login_attempt")
    calls = count_verifications(monkeypatch)
    results = await asyncio.gather(
        *(
            ah.login_admin(
                client, "staff-burst", f"{ah.WRONG_ADMIN_PASSWORD}-{i}", ip=f"203.0.113.{i}"
            )
            for i in range(12)
        )
    )
    assert claims.max >= 2, f"同時性が成立していない（無効試行）: {claims.max}"
    codes = [r.status_code for r in results]
    assert set(codes) <= {401, 403}, codes
    assert calls[0] <= admin_auth_service.ID_LOCK_THRESHOLD, f"照合まで進んだ試行: {calls[0]}"
    assert codes.count(401) == calls[0]
    assert codes.count(403) == 12 - calls[0]
    print(f"\nIT-050-13: 12 本同時 → 照合まで進んだ={calls[0]} 本、403={codes.count(403)} 本")
    assert all(r.json() == {"code": "account_locked"} for r in results if r.status_code == 403)
    failed = await scalar(
        engine, "SELECT COUNT(*) FROM login_attempts WHERE subject_type='staff' AND succeeded = 0"
    )
    assert failed == calls[0], "拒否した試行は先に記録した行を取り消す"


async def test_it_050_13_parallel_attempts_from_one_ip_never_verify_more_than_the_ip_limit(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-16: 同じ IP から別々の ID へ 20 本同時に送っても、照合まで進むのは 10 本以下。"""
    claims = track_inflight(monkeypatch, admin_auth_service, "claim_login_attempt")
    calls = count_verifications(monkeypatch)
    results = await asyncio.gather(
        *(
            ah.login_admin(client, f"staff-spray-{i}", ah.WRONG_ADMIN_PASSWORD, ip="198.51.100.41")
            for i in range(20)
        )
    )
    assert claims.max >= 2, f"同時性が成立していない（無効試行）: {claims.max}"
    codes = [r.status_code for r in results]
    assert set(codes) <= {401, 429}, codes
    assert calls[0] <= admin_auth_service.IP_LIMIT_THRESHOLD, f"照合まで進んだ試行: {calls[0]}"
    assert codes.count(401) == calls[0]
    assert all(r.headers["retry-after"] == "900" for r in results if r.status_code == 429)


async def test_it_050_13_exactly_the_threshold_in_parallel_all_verify_then_the_next_is_locked(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-16: 上限ちょうど（ID 5 本・IP 10 本）の同時送信は全部照合まで進み、次が拒否される。"""
    await ah.create_staff(engine, "staff-edge")
    claims = track_inflight(monkeypatch, admin_auth_service, "claim_login_attempt")
    calls = count_verifications(monkeypatch)
    results = await asyncio.gather(
        *(
            ah.login_admin(client, "staff-edge", ah.WRONG_ADMIN_PASSWORD, ip=f"203.0.113.{i}")
            for i in range(5)
        )
    )
    assert claims.max >= 2, f"同時性が成立していない（無効試行）: {claims.max}"
    assert [r.status_code for r in results] == [401] * 5 and calls[0] == 5
    res = await ah.login_admin(client, "staff-edge", ah.ADMIN_PASSWORD, ip="203.0.113.99")
    assert res.status_code == 403 and res.json() == {"code": "account_locked"}
    assert calls[0] == 5, "ロック後は照合しない"

    ip = "198.51.100.51"
    results = await asyncio.gather(
        *(
            ah.login_admin(client, f"staff-edge-{i}", ah.WRONG_ADMIN_PASSWORD, ip=ip)
            for i in range(10)
        )
    )
    assert [r.status_code for r in results] == [401] * 10
    res = await ah.login_admin(client, "staff-edge-10", ah.WRONG_ADMIN_PASSWORD, ip=ip)
    assert res.status_code == 429 and res.headers["retry-after"] == "900"


async def test_it_050_13_rejected_attempts_do_not_extend_the_lock_and_success_clears_the_row(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """G-16: ロック中の試行は自分の行を取り消す。成功した試行の行は失敗として残らない。"""
    await ah.create_staff(engine, "staff-lock")
    await ah.create_staff(engine, "staff-fine", ah.OTHER_ADMIN_PASSWORD)
    assert await fail(client, "staff-lock", "203.0.113.70", 5) == [401] * 5
    assert await fail(client, "staff-lock", "203.0.113.70", 3) == [403] * 3
    assert await scalar(engine, "SELECT COUNT(*) FROM login_attempts") == 5, "拒否分は残らない"
    res = await ah.login_admin(client, "staff-fine", ah.OTHER_ADMIN_PASSWORD, ip="203.0.113.71")
    assert res.status_code == 200
    rows = await sql(
        engine,
        "SELECT succeeded FROM login_attempts WHERE identifier = :i",
        i=admin_login_identifier("staff-fine"),
    )
    assert [bool(r.succeeded) for r in rows] == [True]


async def test_it_050_14_rejection_logs_carry_the_subject_of_the_targeted_login_id(
    client: httpx.AsyncClient, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """G-19: 401・403・429 の拒否ログに、login_id の SHA-256 の先頭 12 桁（subject）が付く。"""
    caplog.set_level(logging.WARNING, logger="app.security")
    await ah.create_staff(engine, "staff-target")
    assert await fail(client, "staff-target", "203.0.113.80", 5) == [401] * 5
    assert await fail(client, "staff-target", "203.0.113.80", 1) == [403]
    for i in range(10):
        await ah.login_admin(client, f"spray-{i}", ah.WRONG_ADMIN_PASSWORD, ip="198.51.100.81")
    res = await ah.login_admin(client, "late-id", ah.WRONG_ADMIN_PASSWORD, ip="198.51.100.81")
    assert res.status_code == 429
    lines = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app.security"]
    subject = hash_token("staff-target")[:12]
    assert [(x["status"], x["code"]) for x in lines if x.get("subject") == subject] == [
        *[(401, "invalid_credentials")] * 5,
        (403, "account_locked"),
    ]
    assert [x["subject"] for x in lines if x["status"] == 429] == [hash_token("late-id")[:12]]
    for raw in ("staff-target", "late-id", hash_token("staff-target")):
        assert raw not in caplog.text


async def test_it_050_11_staff_and_member_locks_do_not_affect_each_other(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    ip = "203.0.113.61"
    await ah.create_staff(engine, "staff-a")
    await ah.create_staff(engine, "staff-b", ah.OTHER_ADMIN_PASSWORD)
    member = "demo-member1@example.com"

    async def member_login(password: str) -> httpx.Response:
        return await client.post(
            "/api/v1/auth/login",
            json={"email": member, "password": password},
            headers=ah.admin_headers(ip=ip),
        )

    # 管理者を ID ロック → 同じ IP の会員は成功する
    assert await fail(client, "staff-a", ip, 5) == [401] * 5
    assert (await ah.login_admin(client, "staff-a", ip=ip)).status_code == 403
    assert (await member_login(seed_data.DEMO_MEMBER_PASSWORD)).status_code == 200

    # 会員をロック → 同じ IP の管理者は成功する
    for _ in range(5):
        assert (await member_login("Wrong-Phrase-00")).status_code == 401
    assert (await member_login(seed_data.DEMO_MEMBER_PASSWORD)).status_code == 403
    res = await ah.login_admin(client, "staff-b", ah.OTHER_ADMIN_PASSWORD, ip=ip)
    assert res.status_code == 200, res.text


async def test_it_050_12_old_login_attempts_are_cleaned_up_at_most_1000(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await ah.create_staff(engine, "staff-a")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO login_attempts (subject_type, identifier, succeeded, ip, `at`)"
                " VALUES (:t, :i, 0, '198.51.100.1', :a)"
            ),
            [
                {
                    "t": "staff",
                    "i": admin_login_identifier(f"old-{n}"),
                    "a": ah.utcnow() - timedelta(hours=25),
                }
                for n in range(1001)
            ]
            + [
                {
                    "t": "staff",
                    "i": admin_login_identifier("recent"),
                    "a": ah.utcnow() - timedelta(hours=23),
                }
            ],
        )
    assert (await ah.login_admin(client, "staff-a")).status_code == 200
    old = await scalar(
        engine,
        "SELECT COUNT(*) FROM login_attempts WHERE ip='198.51.100.1' AND `at` < :c",
        c=ah.utcnow() - timedelta(hours=24),
    )
    assert old == 1, "古い行は最大 1000 件が削除され、1 件が残る"
    recent = await scalar(
        engine,
        "SELECT COUNT(*) FROM login_attempts WHERE identifier=:i",
        i=admin_login_identifier("recent"),
    )
    assert recent == 1, "24 時間以内の行は削除しない"


# ══════════════════════════════════════════════════════════════════════════
# IT-050a 管理ログアウト
# ══════════════════════════════════════════════════════════════════════════


async def test_it_050a_01_logout_deletes_session_and_audits(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    staff_id = await ah.create_staff(engine, "staff-a")
    token = await ah.login_admin_ok(client, "staff-a")
    res = await client.post(ah.ADMIN_LOGOUT_PATH, headers=ah.admin_headers(token))
    assert res.status_code == 204 and res.content == b""
    assert await staff_sessions(engine) == 0
    audits = await sql(
        engine,
        "SELECT actor_id, target_type, target_id, detail FROM audit_logs"
        " WHERE action='admin.logout'",
    )
    assert len(audits) == 1
    assert audits[0].actor_id == staff_id and audits[0].target_type == "staff"
    assert audits[0].target_id == str(staff_id) and audits[0].detail is None
    assert (await me(client, token)).status_code == 401


async def test_it_050a_02_logout_is_idempotent_and_never_touches_members_or_others(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    staff_a = await ah.create_staff(engine, "staff-a")
    staff_b = await ah.create_staff(engine, "staff-b", ah.OTHER_ADMIN_PASSWORD)
    await ah.login_admin_ok(client, "staff-a")
    other = await ah.login_admin_ok(client, "staff-b", ah.OTHER_ADMIN_PASSWORD)
    member_token = await ph.make_session(engine, await ph.member_id_of(engine))
    audits_before = await scalar(engine, "SELECT COUNT(*) FROM audit_logs")

    for token in (None, "Z" * 43, "short", "Z" * 42 + "=", member_token):
        res = await client.post(ah.ADMIN_LOGOUT_PATH, headers=ah.admin_headers(token))
        assert res.status_code == 204, (token, res.text)

    assert await staff_sessions(engine, staff_a) == 1 and await staff_sessions(engine, staff_b) == 1
    assert (await me(client, other)).status_code == 200, "他の管理者のセッションは消えない"
    members = await scalar(engine, "SELECT COUNT(*) FROM sessions WHERE subject_type='member'")
    assert members == 1, "会員のセッションの行も消えない"
    assert await scalar(engine, "SELECT COUNT(*) FROM audit_logs") == audits_before


async def test_it_050a_03_logout_keeps_the_other_session_of_the_same_staff(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await ah.create_staff(engine, "staff-a")
    first = await ah.login_admin_ok(client, "staff-a")
    second = await ah.login_admin_ok(client, "staff-a")
    res = await client.post(ah.ADMIN_LOGOUT_PATH, headers=ah.admin_headers(first))
    assert res.status_code == 204
    assert (await me(client, first)).status_code == 401
    assert (await me(client, second)).status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# IT-050b 管理者情報の取得・セッションの検証
# ══════════════════════════════════════════════════════════════════════════


async def test_it_050b_01_me_returns_only_login_id_and_role(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await ah.create_staff(engine, "staff-a")
    token = await ah.login_admin_ok(client, "staff-a")
    res = await me(client, token)
    assert res.status_code == 200
    assert res.json() == {"login_id": "staff-a", "role": "staff"}


async def test_it_050b_02_missing_malformed_unknown_and_expired_are_401(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    staff_id = await ah.create_staff(engine, "staff-a")
    expired = await ah.make_admin_session(engine, staff_id, ttl=timedelta(seconds=-1))
    for token in (None, "short", "A" * 43, "!" * 43, expired):
        res = await me(client, token)
        assert res.status_code == 401, (token, res.text)
        assert res.json() == {"code": "unauthorized"}


async def test_it_050b_03_member_session_is_403_and_member_header_is_401(
    client: httpx.AsyncClient, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="app.security")
    member_token = await ph.make_session(engine, await ph.member_id_of(engine))
    res = await me(client, member_token)
    assert res.status_code == 403 and res.json() == {"code": "forbidden"}
    rejected = [r for r in caplog.records if r.name == "app.security" and "403" in r.getMessage()]
    assert len(rejected) == 1, "拒否ログが 1 行"
    # 会員のトークンを会員用のヘッダだけに付けても、管理 API は 401
    res = await client.get(
        ah.ADMIN_ME_PATH, headers={**ah.admin_headers(), "X-Session-Token": member_token}
    )
    assert res.status_code == 401 and res.json() == {"code": "unauthorized"}


async def test_it_050b_04_deleted_staff_row_makes_the_session_401(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    staff_id = await ah.create_staff(engine, "staff-a")
    token = await ah.login_admin_ok(client, "staff-a")
    assert (await me(client, token)).status_code == 200
    await sql(engine, "DELETE FROM staff WHERE id=:i", i=staff_id)
    res = await me(client, token)
    assert res.status_code == 401 and res.json() == {"code": "unauthorized"}
