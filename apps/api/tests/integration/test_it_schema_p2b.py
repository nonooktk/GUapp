"""IT-SCHEMA-09〜13: P2-b のスキーマと seed（MySQL 必須。テスト設計書 P2 追補b 4.4）。

09: upgrade head 後の表は 21（P1 の 12 + P2-a の 1 + P2-b の 8）
10: Alembic の head が 1 本。ad00074244c2 → p2b_auth_tables → p2b_orders_pickup_fk の順
11: 既存の行を残したまま ad00074244c2 へ downgrade し、head へ upgrade し直す
12: 制約を直接 INSERT で確かめる（重複・範囲外・存在しない参照は拒否される）
13: seed 後の件数と `seed --only-p2b` の挙動
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app import seed_data
from app.models import ALL_TABLES, P1_TABLES, P2A_TABLES, P2B_TABLES
from app.seed import count_rows, seed, truncate_all_tables
from tests.integration.conftest import alembic_config

REV_OLD = "ad00074244c2"  # pragma: allowlist secret（P2-b の 1 つ前の版）
REV_AUTH = "13e0c198634f"  # pragma: allowlist secret（p2b_auth_tables）
REV_FK = "f16be26dc48a"  # pragma: allowlist secret（p2b_orders_pickup_fk）

# MySQL のエラー番号
ER_DUP_ENTRY = 1062
ER_NO_REFERENCED_ROW = 1452
ER_CHECK_VIOLATED = 3819


async def _tables(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        return {row[0] for row in await conn.execute(text("SHOW TABLES"))}


# ── IT-SCHEMA-09 ───────────────────────────────────────────────────────────────


async def test_it_schema_09_upgrade_head_creates_21_tables(it_engine: AsyncEngine) -> None:
    tables = await _tables(it_engine)
    assert tables - {"alembic_version"} == ALL_TABLES
    assert len(ALL_TABLES) == 21
    assert len(P1_TABLES) == 12 and len(P2A_TABLES) == 1 and len(P2B_TABLES) == 8
    assert P2B_TABLES == {
        "members",
        "sessions",
        "staff",
        "stores",
        "reviews",
        "restock_notifications",
        "login_attempts",
        "email_tokens",
    }


# ── IT-SCHEMA-10 ───────────────────────────────────────────────────────────────


def test_it_schema_10_single_head_and_revision_order(migrated_schema: str) -> None:
    """head が 1 本（F-029 などの別ブランチが head を増やさないための検査。DS-DEC-83）。"""
    script = ScriptDirectory.from_config(alembic_config(migrated_schema))
    # P2-c 以降は head が進む。P2-b の最後が履歴にあることだけ確かめる（head は IT-SCHEMA-20）
    revisions = [r.revision for r in script.walk_revisions()]
    assert REV_FK in revisions, "p2b_orders_pickup_fk が履歴にあること"

    chain: list[str] = []
    rev = script.get_revision(REV_FK)
    while rev is not None and rev.revision != REV_OLD:
        chain.append(rev.doc or "")
        parent = rev.down_revision
        assert isinstance(parent, str), "枝分かれ・合流していない一本道"
        rev = script.get_revision(parent)
    assert rev is not None and rev.revision == REV_OLD
    assert len(chain) == 2
    assert script.get_revision(REV_FK).down_revision == REV_AUTH
    assert script.get_revision(REV_AUTH).down_revision == REV_OLD
    assert "p2b_orders_pickup_fk" in script.get_revision(REV_FK).path
    assert "p2b_auth_tables" in script.get_revision(REV_AUTH).path


# ── IT-SCHEMA-11 ───────────────────────────────────────────────────────────────


def test_it_schema_11_downgrade_keeps_rows_and_upgrade_restores(migrated_schema: str) -> None:
    """P1 相当の注文・カートの行を入れたまま ad00074244c2 へ downgrade → head へ upgrade し直す。"""
    cfg = alembic_config(migrated_schema)

    async def _run(statements: Sequence[str]) -> list[tuple[Any, ...]]:
        engine = create_async_engine(migrated_schema)
        try:
            out: list[tuple[Any, ...]] = []
            async with engine.begin() as conn:
                for sql in statements:
                    result = await conn.execute(text(sql))
                    if result.returns_rows:
                        out = [tuple(r) for r in result.all()]
            return out
        finally:
            await engine.dispose()

    def _constraints() -> list[tuple[Any, ...]]:
        return asyncio.run(
            _run(
                [
                    "SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE "
                    "FROM information_schema.TABLE_CONSTRAINTS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('orders', 'carts') "
                    "AND CONSTRAINT_TYPE IN ('FOREIGN KEY', 'UNIQUE') ORDER BY 1, 2"
                ]
            )
        )

    def _indexes() -> set[str]:
        rows = asyncio.run(
            _run(
                [
                    "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders'"
                ]
            )
        )
        return {r[0] for r in rows}

    def _tables_now() -> set[str]:
        rows = asyncio.run(_run(["SHOW TABLES"]))
        return {r[0] for r in rows} - {"alembic_version"}

    insert_cart = "INSERT INTO carts (anonymous_token, status) VALUES ('it-schema-11', 'active')"
    insert_order = (
        "INSERT INTO orders (order_number, idempotency_key, guest_email, status, receive_method, "
        "subtotal, shipping_fee, discount, total, tax_rate_at_order, ship_name, ship_postal_code, "
        "ship_address, ship_phone, cart_id) "
        "SELECT 'GU-260101-AAAAAAAA', 'it-schema-11-key', 'it11@example.com', 'accepted', "
        "'delivery', 1000, 550, 0, 1550, '0.10', 'テスト', '1000001', '東京都', '09012345678', "
        "id FROM carts WHERE anonymous_token = 'it-schema-11'"
    )
    new_names = {
        "fk_orders_member_id_members",
        "fk_orders_store_id_stores",
        "fk_carts_member_id_members",
        "uq_orders_pickup_code",
    }
    new_indexes = {
        "ix_orders_member_id_created_at",
        "ix_orders_created_at",
        "ix_orders_guest_email",
    }
    try:
        with_new = _constraints()
        assert new_names <= {r[1] for r in with_new}
        assert new_indexes <= _indexes()

        command.downgrade(cfg, REV_OLD)
        assert _tables_now() == P1_TABLES | P2A_TABLES, "P2-b の 8 表が消える"
        assert not (new_names & {r[1] for r in _constraints()}), "外部キー・UNIQUE が消える"
        assert not (new_indexes & _indexes()), "追加した索引が消える"
        assert "fk_orders_store_id_stores" not in _indexes(), "自動作成の索引も残らない"

        # downgrade 後の状態（P1 相当）に行を入れ、upgrade 後も失われないことを確かめる
        asyncio.run(_run([insert_cart, insert_order]))

        command.upgrade(cfg, "head")
        assert _tables_now() == ALL_TABLES
        assert new_names <= {r[1] for r in _constraints()}
        assert new_indexes <= _indexes()
        rows = asyncio.run(
            _run(["SELECT order_number, member_id, store_id, pickup_code FROM orders"])
        )
        assert rows == [("GU-260101-AAAAAAAA", None, None, None)], "既存の行が失われない"
        assert asyncio.run(_run(["SELECT COUNT(*) FROM carts"])) == [(1,)]
    finally:
        command.upgrade(cfg, "head")

        async def _cleanup() -> None:
            engine = create_async_engine(migrated_schema)
            try:
                async with engine.begin() as conn:
                    await truncate_all_tables(conn)
            finally:
                await engine.dispose()

        asyncio.run(_cleanup())


# ── IT-SCHEMA-12 ───────────────────────────────────────────────────────────────


async def _expect_error(engine: AsyncEngine, sql: str, code: int) -> None:
    # 重複・外部キーは IntegrityError、CHECK 違反は OperationalError（3819）で上がる
    with pytest.raises(DBAPIError) as ei:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
    assert ei.value.orig.args[0] == code, f"{sql} → {ei.value.orig.args}"  # type: ignore[union-attr]


async def _exec(engine: AsyncEngine, sql: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql))


def _order_sql(number: str, key: str, **cols: str) -> str:
    """cart_id は最初のカート。`cols` は member_id・store_id・pickup_code の指定（SQL 片）。"""
    names = ["order_number", "idempotency_key", *cols]
    values = [f"'{number}'", f"'{key}'", *cols.values()]
    return (
        "INSERT INTO orders (guest_email, status, receive_method, subtotal, shipping_fee, "
        "discount, total, tax_rate_at_order, ship_name, ship_postal_code, ship_address, "
        "ship_phone, cart_id, " + ", ".join(names) + ") "
        "SELECT 'it12@example.com', 'accepted', 'store', 1000, 0, 0, 1000, '0.10', 'テスト', "
        "'0000001', '東京都', '09012345678', id, " + ", ".join(values) + " FROM carts LIMIT 1"
    )


async def test_it_schema_12_constraints_reject_bad_rows(seed_db: AsyncEngine) -> None:
    e = seed_db
    # members.email の重複（照合順序は大文字小文字を区別しないので、大文字違いも重複）
    await _expect_error(
        e,
        "INSERT INTO members (email, password_hash, name) "
        "VALUES ('DEMO-MEMBER1@EXAMPLE.COM', 'x', 'dup')",
        ER_DUP_ENTRY,
    )

    # sessions.token_hash の重複
    session_sql = (
        "INSERT INTO sessions (token_hash, subject_type, subject_id, expires_at, last_seen_at) "
        "VALUES ('{h}', 'member', 1, NOW(), NOW())"
    )
    await _exec(e, session_sql.format(h="a" * 64))
    await _expect_error(e, session_sql.format(h="a" * 64), ER_DUP_ENTRY)

    # restock_notifications (variant_id, email) の重複
    restock_sql = (
        "INSERT INTO restock_notifications (variant_id, email) "
        "SELECT id, 'dup@example.com' FROM variants ORDER BY id LIMIT 1"
    )
    await _exec(e, restock_sql)
    await _expect_error(e, restock_sql, ER_DUP_ENTRY)

    # reviews.rating の範囲（0・6 は拒否、1・5 は可）
    review_sql = (
        "INSERT INTO reviews (product_id, rating, body, approved) "
        "SELECT id, {r}, 'x', 1 FROM products ORDER BY id LIMIT 1"
    )
    await _expect_error(e, review_sql.format(r=0), ER_CHECK_VIOLATED)
    await _expect_error(e, review_sql.format(r=6), ER_CHECK_VIOLATED)
    await _exec(e, review_sql.format(r=1))
    await _exec(e, review_sql.format(r=5))

    # orders: 存在しない会員・存在しない店舗
    await _exec(e, "INSERT INTO carts (anonymous_token, status) VALUES ('it-schema-12', 'active')")
    await _expect_error(
        e, _order_sql("GU-260101-BBBBBBBB", "k12-member", member_id="999999"), ER_NO_REFERENCED_ROW
    )
    await _expect_error(
        e, _order_sql("GU-260101-CCCCCCCC", "k12-store", store_id="999999"), ER_NO_REFERENCED_ROW
    )

    # orders.pickup_code の重複は拒否、NULL は複数行入る
    await _exec(e, _order_sql("GU-260101-DDDDDDDD", "k12-pc1", pickup_code="'ABCDEFGH'"))
    await _expect_error(
        e, _order_sql("GU-260101-EEEEEEEE", "k12-pc2", pickup_code="'ABCDEFGH'"), ER_DUP_ENTRY
    )
    await _exec(e, _order_sql("GU-260101-FFFFFFFF", "k12-null1"))
    await _exec(e, _order_sql("GU-260101-GGGGGGGG", "k12-null2"))
    async with e.connect() as conn:
        nulls = (
            await conn.execute(text("SELECT COUNT(*) FROM orders WHERE pickup_code IS NULL"))
        ).scalar_one()
    assert nulls == 2


# ── IT-SCHEMA-13 ───────────────────────────────────────────────────────────────


async def test_it_schema_13_seed_counts(seed_db: AsyncEngine) -> None:
    async with seed_db.connect() as conn:
        counts = await count_rows(conn)
        approved = (
            await conn.execute(text("SELECT COUNT(*) FROM reviews WHERE approved = 1"))
        ).scalar_one()
        unapproved_p1 = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM reviews r JOIN products p ON p.id = r.product_id "
                    "WHERE r.approved = 0 AND p.name = :n AND r.fit = 'large'"
                ),
                {"n": seed_data.PRODUCTS[0].name},
            )
        ).scalar_one()
        unverified = (
            (await conn.execute(text("SELECT email FROM members WHERE email_verified_at IS NULL")))
            .scalars()
            .all()
        )
        hashes = (await conn.execute(text("SELECT password_hash FROM members"))).scalars().all()
    assert (counts["members"], counts["stores"], counts["reviews"]) == (5, 3, 43)
    assert approved == 42
    assert unapproved_p1 == 1
    assert unverified == ["demo-member3@example.com"]
    assert all(h.startswith("$argon2id$") for h in hashes)


async def _truncate_p2b(engine: AsyncEngine, *names: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for name in names:
            assert name in P2B_TABLES
            await conn.execute(text(f"TRUNCATE TABLE `{name}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


async def test_it_schema_13_only_p2b_inserts_into_empty_tables_only(seed_db: AsyncEngine) -> None:
    # すべて入っている状態では何もしない
    result = await seed(seed_db, only_p2b=True)
    assert result.skipped is True
    assert (result.counts["members"], result.counts["stores"], result.counts["reviews"]) == (
        5,
        3,
        43,
    )

    # 3 表が空なら投入する。2 回目は何もしない
    await _truncate_p2b(seed_db, "reviews", "members", "stores")
    first = await seed(seed_db, only_p2b=True)
    assert first.skipped is False
    assert (first.counts["members"], first.counts["stores"], first.counts["reviews"]) == (5, 3, 43)
    second = await seed(seed_db, only_p2b=True)
    assert second.skipped is True and second.counts == first.counts

    # 一部の表だけ空なら、その表だけ投入する（既存の表は触らない）
    await _truncate_p2b(seed_db, "stores")
    third = await seed(seed_db, only_p2b=True)
    assert third.skipped is False
    assert (third.counts["members"], third.counts["stores"], third.counts["reviews"]) == (5, 3, 43)

    # reset とは併用できない
    with pytest.raises(ValueError):
        await seed(seed_db, reset=True, only_p2b=True)
