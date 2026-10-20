"""IT-SCHEMA-20〜22: P2-c のスキーマ（MySQL 必須。テスト設計書 P2 追補c 4.5）。

20: Alembic の head が 1 本。… → f16be26dc48a → p2c_admin_constraints（14aa9b4157c2）の順
21: 管理者とセッションの行を入れたまま f16be26dc48a へ downgrade し、head へ upgrade し直す
22: `staff.role` の CHECK 制約と `audit_logs` の索引（列の順序）
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
from app.seed import truncate_all_tables
from tests.integration.conftest import alembic_config

REV_OLD = "ad00074244c2"  # pragma: allowlist secret（P2-b の 1 つ前の版）
REV_AUTH = "13e0c198634f"  # pragma: allowlist secret（p2b_auth_tables）
REV_FK = "f16be26dc48a"  # pragma: allowlist secret（p2b_orders_pickup_fk）
REV_P2C = "14aa9b4157c2"  # pragma: allowlist secret（p2c_admin_constraints）
INDEX_NAME = "ix_audit_logs_target_type_target_id_at"
CHECK_NAME = "ck_staff_role_allowed"
ER_CHECK_VIOLATED = 3819


# ── IT-SCHEMA-20 ───────────────────────────────────────────────────────────────


def test_it_schema_20_single_head_and_revision_order(migrated_schema: str) -> None:
    """head が 1 本で、P2-b の最後のリビジョンの次に p2c_admin_constraints が付く（DS-DEC-123）。"""
    script = ScriptDirectory.from_config(alembic_config(migrated_schema))
    assert script.get_heads() == [REV_P2C], "head が 1 本で p2c_admin_constraints であること"
    assert script.get_revision(REV_P2C).down_revision == REV_FK
    assert script.get_revision(REV_FK).down_revision == REV_AUTH
    assert script.get_revision(REV_AUTH).down_revision == REV_OLD
    assert "p2c_admin_constraints" in script.get_revision(REV_P2C).path
    assert "p2b_orders_pickup_fk" in script.get_revision(REV_FK).path


# ── IT-SCHEMA-21 ───────────────────────────────────────────────────────────────


def test_it_schema_21_downgrade_keeps_rows_and_upgrade_restores(migrated_schema: str) -> None:
    """管理者とセッションの行を入れたまま f16be26dc48a へ downgrade → head へ upgrade し直す。"""
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

    def run(*statements: str) -> list[tuple[Any, ...]]:
        return asyncio.run(_run(statements))

    def has_check() -> bool:
        return bool(
            run(
                "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE()"
                f" AND TABLE_NAME = 'staff' AND CONSTRAINT_NAME = '{CHECK_NAME}'"
                " AND CONSTRAINT_TYPE = 'CHECK'"
            )
        )

    def has_index() -> bool:
        return bool(
            run(
                "SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE()"
                f" AND TABLE_NAME = 'audit_logs' AND INDEX_NAME = '{INDEX_NAME}'"
            )
        )

    def old_at_index_kept() -> bool:
        return bool(
            run(
                "SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE()"
                " AND TABLE_NAME = 'audit_logs' AND INDEX_NAME = 'ix_audit_logs_at'"
            )
        )

    insert_staff = (
        "INSERT INTO staff (login_id, password_hash, role)"
        " VALUES ('it-schema-21', '$argon2id$dummy', 'staff')"
    )
    insert_session = (
        "INSERT INTO sessions (token_hash, subject_type, subject_id, expires_at, last_seen_at)"
        " SELECT SHA2('it-schema-21', 256), 'staff', id, UTC_TIMESTAMP() + INTERVAL 1 HOUR,"
        " UTC_TIMESTAMP() FROM staff WHERE login_id = 'it-schema-21'"
    )
    insert_audit = (
        "INSERT INTO audit_logs (actor_type, actor_id, action, target_type, target_id)"
        " VALUES ('staff', 1, 'admin.login', 'staff', '1')"
    )
    try:
        assert has_check() and has_index()

        run(insert_staff, insert_session, insert_audit)
        command.downgrade(cfg, REV_FK)
        assert not has_check(), "downgrade で CHECK 制約が消える"
        assert not has_index(), "downgrade で索引が消える"
        assert old_at_index_kept(), "既存の at の索引は残る"
        # 外した状態では想定外のロールも入る（= 制約が消えている証拠）
        run("INSERT INTO staff (login_id, password_hash, role) VALUES ('it-schema-21b', 'x', 'x')")
        run("DELETE FROM staff WHERE login_id = 'it-schema-21b'")

        command.upgrade(cfg, "head")
        assert has_check() and has_index(), "upgrade で戻る"
        assert old_at_index_kept()
        assert run("SELECT login_id, role FROM staff") == [("it-schema-21", "staff")]
        assert run("SELECT COUNT(*) FROM sessions WHERE subject_type = 'staff'") == [(1,)]
        assert run("SELECT COUNT(*) FROM audit_logs") == [(1,)], "既存の行が失われない"
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


# ── IT-SCHEMA-22 ───────────────────────────────────────────────────────────────


async def _expect_check_violation(engine: AsyncEngine, sql: str) -> None:
    with pytest.raises(DBAPIError) as ei:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
    assert ei.value.orig.args[0] == ER_CHECK_VIOLATED, f"{sql} → {ei.value.orig.args}"  # type: ignore[union-attr]


async def test_it_schema_22_role_check_and_audit_index(it_engine: AsyncEngine) -> None:
    async with it_engine.begin() as conn:
        await conn.execute(text("DELETE FROM staff WHERE login_id LIKE 'it-schema-22%'"))
    try:
        async with it_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO staff (login_id, password_hash, role)"
                    " VALUES ('it-schema-22', 'x', 'staff')"
                )
            )
        for role in ("admin", ""):
            await _expect_check_violation(
                it_engine,
                "INSERT INTO staff (login_id, password_hash, role)"
                f" VALUES ('it-schema-22-{role or 'empty'}', 'x', '{role}')",
            )
        await _expect_check_violation(
            it_engine, "UPDATE staff SET role = 'admin' WHERE login_id = 'it-schema-22'"
        )
        async with it_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT COLUMN_NAME, SEQ_IN_INDEX FROM information_schema.STATISTICS"
                        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_logs'"
                        f" AND INDEX_NAME = '{INDEX_NAME}' ORDER BY SEQ_IN_INDEX"
                    )
                )
            ).all()
        assert [tuple(r) for r in rows] == [("target_type", 1), ("target_id", 2), ("at", 3)]
    finally:
        async with it_engine.begin() as conn:
            await conn.execute(text("DELETE FROM staff WHERE login_id LIKE 'it-schema-22%'"))
