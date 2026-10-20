"""UT-SEED-08〜11: P2-b の seed 定義とダミー性（テスト設計書 P2 追補b 5.1・設計仕様書 5.8）。

会員の投入有無（production と `SEED_MEMBER_PASSWORD`。DS-DEC-87）は、SQLite のファイル DB に
実際に seed して確かめる（MySQL 固有の挙動は IT-SCHEMA-13）。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app import seed_data
from app.models import Base, Member
from app.seed import member_seed_password, seed

STORE_CODE_RE = re.compile(r"^[a-z0-9-]{1,32}$")
SEED_PASSWORD_FOR_TEST = "unit-test-seed-pw-1"  # pragma: allowlist secret（テスト用ダミー）


@pytest.fixture
async def sqlite_engine(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'seed.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


# ── UT-SEED-08 会員 ────────────────────────────────────────────────────────────


def test_ut_seed_08_members_definition() -> None:
    members = seed_data.MEMBERS
    assert len(members) == seed_data.EXPECTED_MEMBER_COUNT == 5
    assert [m.email for m in members] == [f"demo-member{i}@example.com" for i in range(1, 6)]
    assert [m.name for m in members] == [
        "デモ 一郎",
        "デモ 二郎",
        "デモ 三子",
        "デモ 四郎",
        "デモ 五子",
    ]
    assert [m.email for m in members if not m.email_verified] == ["demo-member3@example.com"]


async def test_ut_seed_08_members_inserted_in_development(
    app_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    app_env(APP_ENV="development")
    result = await seed(sqlite_engine)
    assert result.counts["members"] == 5
    async with sqlite_engine.connect() as conn:
        rows = (await conn.execute(select(Member.email, Member.password_hash))).all()
    hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
    for _email, password_hash in rows:
        assert password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
        assert hasher.verify(password_hash, seed_data.DEMO_MEMBER_PASSWORD)
        assert not hasher.check_needs_rehash(password_hash)


async def test_ut_seed_08_production_without_password_skips_members(
    app_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    """production で SEED_MEMBER_PASSWORD が無ければ会員を投入しない（0 件）。他は投入する。"""
    app_env(APP_ENV="production")
    result = await seed(sqlite_engine)
    assert result.counts["members"] == 0
    assert result.counts["stores"] == 3 and result.counts["reviews"] == 43
    assert any("SEED_MEMBER_PASSWORD" in n for n in result.notes)


async def test_ut_seed_08_production_with_password_inserts_members(
    app_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    app_env(APP_ENV="production", SEED_MEMBER_PASSWORD=SEED_PASSWORD_FOR_TEST)
    result = await seed(sqlite_engine)
    assert result.counts["members"] == 5 and result.notes == ()
    async with sqlite_engine.connect() as conn:
        hashes = (await conn.execute(text("SELECT password_hash FROM members"))).scalars().all()
    hasher = PasswordHasher()
    assert all(h.startswith("$argon2id$") for h in hashes)
    assert all(hasher.verify(h, SEED_PASSWORD_FOR_TEST) for h in hashes)
    # 既定のダミーパスワードでは入れない（公開環境に既知の資格情報を残さない）
    with pytest.raises(Exception):  # noqa: B017  argon2 の VerifyMismatchError
        hasher.verify(hashes[0], seed_data.DEMO_MEMBER_PASSWORD)


def test_ut_seed_08_member_seed_password_rules(app_env: Callable[..., None]) -> None:
    from app.core.config import get_settings

    app_env(APP_ENV="development")
    assert member_seed_password(get_settings()) == seed_data.DEMO_MEMBER_PASSWORD
    app_env(APP_ENV="test", SEED_MEMBER_PASSWORD=SEED_PASSWORD_FOR_TEST)
    assert member_seed_password(get_settings()) == SEED_PASSWORD_FOR_TEST
    app_env(APP_ENV="production")
    assert member_seed_password(get_settings()) is None
    app_env(APP_ENV="production", SEED_MEMBER_PASSWORD=SEED_PASSWORD_FOR_TEST)
    assert member_seed_password(get_settings()) == SEED_PASSWORD_FOR_TEST


# ── UT-SEED-09 店舗 ────────────────────────────────────────────────────────────


def test_ut_seed_09_stores() -> None:
    stores = seed_data.STORES
    assert len(stores) == seed_data.EXPECTED_STORE_COUNT == 3
    assert [s.code for s in stores] == ["demo-tokyo", "demo-osaka", "demo-fukuoka"]
    for s in stores:
        assert STORE_CODE_RE.fullmatch(s.code)
        assert re.fullmatch(r"[0-9]{7}", s.postal_code), "ASCII 数字 7 桁・ハイフンなし"
        assert s.pickup_enabled is True
        assert s.address.startswith(s.prefecture)
    assert len({s.code for s in stores}) == 3
    assert [s.sort_order for s in stores] == sorted(s.sort_order for s in stores)


# ── UT-SEED-10 レビュー ────────────────────────────────────────────────────────


def test_ut_seed_10_reviews_match_design_table() -> None:
    reviews = seed_data.REVIEWS
    assert len(reviews) == seed_data.EXPECTED_REVIEW_COUNT == 43
    assert sum(1 for r in reviews if r.approved) == 42
    assert [r for r in reviews if not r.approved] == [
        r for r in reviews if r.product_number == 1 and r.fit == "large" and not r.approved
    ]
    assert sum(1 for r in reviews if not r.approved) == 1

    # 設計仕様書 5.8 の表（商品番号 → small, just, large）
    expected = {
        1: (2, 6, 2),
        2: (0, 5, 1),
        3: (4, 3, 0),
        4: (1, 1, 1),
        5: (0, 2, 5),
        6: (3, 0, 0),
        7: (1, 4, 0),
        8: (0, 1, 0),
    }
    counts = Counter((r.product_number, r.fit) for r in reviews if r.approved)
    for number, (small, just, large) in expected.items():
        assert (counts[(number, "small")], counts[(number, "just")], counts[(number, "large")]) == (
            small,
            just,
            large,
        ), f"商品 {number}"
    assert sum(sum(v) for v in expected.values()) == 42
    assert (
        sum(v[0] for v in expected.values()),
        sum(v[1] for v in expected.values()),
        sum(v[2] for v in expected.values()),
    ) == (11, 22, 9)
    assert not [r for r in reviews if r.product_number >= 9], "商品 9 以降は 0 件"
    assert all(3 <= r.rating <= 5 for r in reviews)
    assert all(r.member_id is None for r in reviews)
    assert all(r.fit in {"small", "just", "large"} for r in reviews)


def test_ut_seed_10_product_names_are_unique() -> None:
    """`--only-p2b` は商品名でレビューの商品を引くので、名前が一意であること。"""
    names = [p.name for p in seed_data.PRODUCTS]
    assert len(names) == len(set(names))


async def test_ut_seed_10_reviews_attached_to_the_right_products(
    app_env: Callable[..., None], sqlite_engine: AsyncEngine
) -> None:
    app_env(APP_ENV="development")
    await seed(sqlite_engine)
    async with sqlite_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT p.name, r.fit, r.approved FROM reviews r "
                    "JOIN products p ON p.id = r.product_id"
                )
            )
        ).all()
    by_product = Counter(name for name, _fit, approved in rows if approved)
    assert by_product[seed_data.PRODUCTS[0].name] == 10
    assert by_product[seed_data.PRODUCTS[7].name] == 1
    assert seed_data.PRODUCTS[8].name not in by_product


# ── UT-SEED-11 ダミー性 ────────────────────────────────────────────────────────


def _all_strings() -> list[str]:
    out: list[str] = []
    for m in seed_data.MEMBERS:
        out += [m.email, m.name]
    for s in seed_data.STORES:
        out += [s.code, s.name, s.prefecture, s.postal_code, s.address]
    for r in seed_data.REVIEWS:
        out += [r.body]
    return out


def test_ut_seed_11_dummy_only() -> None:
    assert all(m.email.endswith("@example.com") for m in seed_data.MEMBERS)
    # 郵便番号は 0000001〜0000003 のダミー（実在の番号ではない）
    assert {s.postal_code for s in seed_data.STORES} == {"0000001", "0000002", "0000003"}
    # 店舗名は「デモ店」で始まる（実在の店舗名に似せない）
    assert all(s.name.startswith("デモ店") for s in seed_data.STORES)
    strings = _all_strings()
    # 電話番号らしき数字列（10〜11 桁）・URL・メール（example.com 以外）を含まない
    assert not [t for t in strings if re.search(r"[0-9０-９]{10,11}", t)]
    assert not [t for t in strings if re.search(r"https?://", t)]
    emails = [e for t in strings for e in re.findall(r"[\w.+-]+@[\w.-]+", t)]
    assert emails and all(e.endswith("@example.com") for e in emails)
    # 実在の企業名・ブランド名を含まない
    assert not [t for t in strings if re.search(r"ユニクロ|ジーユー|GU店|UNIQLO", t)]
