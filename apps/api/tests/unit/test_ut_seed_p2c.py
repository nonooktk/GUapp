"""UT-SEED-20〜23: P2-c の seed（管理者。テスト設計書 P2 追補c 5.1 / 設計仕様書 P2 追補c 5.7）。

SQLite のファイル DB に実際に seed して確かめる（MySQL 固有の挙動は IT）。
環境変数 `SEED_STAFF_PASSWORD`・`SEED_STAFF_LOGIN_ID` は、`.env` の値が紛れ込まないよう、
毎回空文字で上書きしてから必要なものだけ与える。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app import seed as seed_mod
from app import seed_data
from app.models import Base
from app.seed import seed, staff_seed_credentials

LOGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")
PW_12 = "twelve-chars"  # pragma: allowlist secret（テスト用ダミー。12 文字）
PW_11 = "eleven-char"  # pragma: allowlist secret（テスト用ダミー。11 文字）
PW_NEW = "another-twelve-pw"  # pragma: allowlist secret（テスト用ダミー）
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


@pytest.fixture
async def sqlite_engine(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'seed.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def staff_env(app_env: Callable[..., None]) -> Callable[..., None]:
    """管理者の seed に関わる環境変数を空にそろえてから、必要なものだけ与える。"""

    def _apply(*, password: str = "", login_id: str = "", **env: str) -> None:
        app_env(SEED_STAFF_PASSWORD=password, SEED_STAFF_LOGIN_ID=login_id, **env)

    return _apply


async def _staff_rows(engine: AsyncEngine) -> list[tuple[str, str, str]]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT login_id, password_hash, role FROM staff"))
        return [tuple(r) for r in rows]


# ── UT-SEED-20 seed の管理者の定義 ───────────────────────────────────────────


def test_ut_seed_20_staff_definition() -> None:
    assert len(seed_data.STAFF) == seed_data.EXPECTED_STAFF_COUNT == 1
    only = seed_data.STAFF[0]
    assert only.login_id == "demo-staff" and LOGIN_ID_RE.fullmatch(only.login_id)
    assert only.role == "staff"
    # パスワードは定数として存在する（値はここでは検査せず、長さだけ見る。他のファイルに書かない）
    assert isinstance(seed_data.DEMO_STAFF_PASSWORD, str) and seed_data.DEMO_STAFF_PASSWORD
    assert seed_data.STAFF_PASSWORD_MIN_LENGTH_PRODUCTION == 12


async def test_ut_seed_20_staff_is_inserted_in_development(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    staff_env(APP_ENV="development")
    result = await seed(sqlite_engine)
    assert result.counts["staff"] == 1
    [(login_id, password_hash, role)] = await _staff_rows(sqlite_engine)
    assert (login_id, role) == ("demo-staff", "staff")
    assert password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert HASHER.verify(password_hash, seed_data.DEMO_STAFF_PASSWORD)
    assert not HASHER.check_needs_rehash(password_hash)


# ── UT-SEED-21 production の seed（パスワードが無い・短い）────────────────────


@pytest.mark.parametrize("password", ["", PW_11])
async def test_ut_seed_21_production_without_a_usable_password_skips_staff_only(
    staff_env: Callable[..., None],
    sqlite_engine: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
    password: str,
) -> None:
    staff_env(APP_ENV="production", password=password)
    result = await seed(sqlite_engine)
    assert result.counts["staff"] == 0
    assert result.counts["stores"] == 3 and result.counts["products"] > 0, "他の seed は続く"
    err = capsys.readouterr().err
    assert "SEED_STAFF_PASSWORD" in err and "12" in err, "理由を標準エラーに出す"
    assert password not in err or password == ""


async def test_ut_seed_21_default_dummy_password_is_never_used_in_production(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    staff_env(APP_ENV="production")
    assert staff_seed_credentials(seed_mod.get_settings()) == (
        None,
        "APP_ENV=production で SEED_STAFF_PASSWORD が無い、または 12 文字未満のため、"
        "管理者の seed を行いません",
    )
    await seed(sqlite_engine)
    assert await _staff_rows(sqlite_engine) == []


# ── UT-SEED-22 production の seed（正常）─────────────────────────────────────


async def test_ut_seed_22_production_with_12_chars_inserts_one(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    staff_env(APP_ENV="production", password=PW_12)
    result = await seed(sqlite_engine)
    assert result.counts["staff"] == 1
    [(login_id, password_hash, role)] = await _staff_rows(sqlite_engine)
    assert (login_id, role) == ("demo-staff", "staff")
    assert password_hash.startswith("$argon2id$")
    assert HASHER.verify(password_hash, PW_12)
    with pytest.raises(VerifyMismatchError):
        HASHER.verify(password_hash, seed_data.DEMO_STAFF_PASSWORD)  # 既定のダミーでは入れない
    assert "SEED_STAFF_PASSWORD" not in capsys.readouterr().err


async def test_ut_seed_22_login_id_from_env_is_normalized_and_validated(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine, tmp_path: Path
) -> None:
    staff_env(APP_ENV="production", password=PW_12, login_id="Ops-Admin.01")
    await seed(sqlite_engine)
    assert [r[0] for r in await _staff_rows(sqlite_engine)] == ["ops-admin.01"]

    # 形式不正な login_id は投入しない（他の seed は続く）
    other = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'other.db'}")
    try:
        async with other.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        staff_env(APP_ENV="production", password=PW_12, login_id="x y")
        result = await seed(other)
        assert result.counts["staff"] == 0 and result.counts["stores"] == 3
    finally:
        await other.dispose()


async def test_ut_seed_22_password_is_nfkc_normalized_before_hashing(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    fullwidth = "ＦｕｌｌＷｉｄｔｈＰｗ１２３"  # pragma: allowlist secret（テスト用ダミー）
    staff_env(APP_ENV="production", password=fullwidth)
    await seed(sqlite_engine)
    [(_, password_hash, _)] = await _staff_rows(sqlite_engine)
    assert HASHER.verify(password_hash, unicodedata.normalize("NFKC", fullwidth))
    with pytest.raises(VerifyMismatchError):
        HASHER.verify(password_hash, fullwidth)


def test_ut_seed_22_credential_rules_in_non_production(staff_env: Callable[..., None]) -> None:
    staff_env(APP_ENV="development")
    creds, reason = staff_seed_credentials(seed_mod.get_settings())
    assert reason is None and creds is not None
    assert (creds.login_id, creds.password) == ("demo-staff", seed_data.DEMO_STAFF_PASSWORD)
    staff_env(APP_ENV="test", password="short")  # 開発・テストでは短くてもよい
    creds, _ = staff_seed_credentials(seed_mod.get_settings())
    assert creds is not None and creds.password == "short"


# ── UT-SEED-23 --only-p2c ────────────────────────────────────────────────────


async def test_ut_seed_23_only_p2c_inserts_once(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    staff_env(APP_ENV="development")
    first = await seed(sqlite_engine, only_p2c=True)
    assert first.skipped is False and first.counts["staff"] == 1
    assert first.counts["products"] == 0, "管理者だけ（他の表には触れない）"
    second = await seed(sqlite_engine, only_p2c=True)
    assert second.skipped is True and second.counts["staff"] == 1, "2 回目は何もしない"


async def test_ut_seed_23_only_p2c_in_production_without_password_does_nothing(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    staff_env(APP_ENV="production")
    result = await seed(sqlite_engine, only_p2c=True)
    assert result.skipped is True and result.counts["staff"] == 0
    assert "SEED_STAFF_PASSWORD" in capsys.readouterr().err


async def test_ut_seed_23_update_staff_password_changes_only_the_hash(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    staff_env(APP_ENV="production", password=PW_12)
    await seed(sqlite_engine, only_p2c=True)
    async with sqlite_engine.connect() as conn:
        before = (await conn.execute(text("SELECT * FROM staff"))).one()._asdict()

    staff_env(APP_ENV="production", password=PW_NEW)
    # --update-staff-password を付けないと、行があるので何もしない
    assert (await seed(sqlite_engine, only_p2c=True)).skipped is True
    assert HASHER.verify((await _staff_rows(sqlite_engine))[0][1], PW_12)

    updated = await seed(sqlite_engine, only_p2c=True, update_staff_password=True)
    assert updated.skipped is False
    async with sqlite_engine.connect() as conn:
        after = (await conn.execute(text("SELECT * FROM staff"))).one()._asdict()
    assert HASHER.verify(after["password_hash"], PW_NEW)
    changed = {k for k in before if before[k] != after[k]}
    assert changed <= {"password_hash", "updated_at"}, f"他の列は変えない: {changed}"
    assert "password_hash" in changed
    assert (before["login_id"], before["role"], before["locked_until"]) == (
        after["login_id"],
        after["role"],
        after["locked_until"],
    )


async def test_ut_seed_23_update_staff_password_edge_cases(
    staff_env: Callable[..., None], sqlite_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    # 同じ login_id の行が無ければ何もしない
    staff_env(APP_ENV="development")
    result = await seed(sqlite_engine, only_p2c=True, update_staff_password=True)
    assert result.skipped is True and result.counts["staff"] == 0
    assert "login_id" in capsys.readouterr().err
    # production で短いパスワードなら更新しない
    await seed(sqlite_engine, only_p2c=True)
    staff_env(APP_ENV="production", password=PW_11)
    result = await seed(sqlite_engine, only_p2c=True, update_staff_password=True)
    assert result.skipped is True
    assert HASHER.verify((await _staff_rows(sqlite_engine))[0][1], seed_data.DEMO_STAFF_PASSWORD)


async def test_ut_seed_23_option_combinations(sqlite_engine: AsyncEngine) -> None:
    with pytest.raises(ValueError):
        await seed(sqlite_engine, only_p2b=True, only_p2c=True)
    with pytest.raises(ValueError):
        await seed(sqlite_engine, reset=True, only_p2c=True)
    with pytest.raises(ValueError):
        await seed(sqlite_engine, update_staff_password=True)
    for argv in (
        ["--update-staff-password"],
        ["--only-p2c", "--only-p2b"],
        ["--reset", "--only-p2c"],
    ):
        with pytest.raises(SystemExit) as ei:
            seed_mod.main(argv)
        assert ei.value.code == 2
