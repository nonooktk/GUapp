"""IT-029-29・30: マイグレーションと 90 日削除の手動 SQL（P2 追補d 5.4・8.5）。MySQL 必須。

IT-029-29 は共用のテスト DB で `downgrade -1` → `upgrade head` を行う
（終わったら必ず head に戻す）。
統合後の期待値: head が 1 本で F-029 のリビジョン、`down_revision` が P2-c の head
（`14aa9b4157c2`）。
"""

from __future__ import annotations

import asyncio

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.integration.conftest import alembic_config

CHAT_TABLES = {"chat_sessions", "chat_messages"}
REVISION_FILE_SUFFIX = "_p2d_chat.py"


def _run(url: str, sql: str, **params: object) -> list[tuple]:
    async def go() -> list[tuple]:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params)
                return [tuple(r) for r in result.all()] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _tables(url: str) -> set[str]:
    return {r[0] for r in _run(url, "SHOW TABLES")}


def _indexes(url: str, table: str) -> dict[str, tuple[bool, list[str]]]:
    rows = _run(
        url,
        "SELECT INDEX_NAME, NON_UNIQUE, COLUMN_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t ORDER BY INDEX_NAME, SEQ_IN_INDEX",
        t=table,
    )
    out: dict[str, tuple[bool, list[str]]] = {}
    for name, non_unique, column in rows:
        unique, columns = out.setdefault(name, (non_unique == 0, []))
        columns.append(column)
    return out


def test_it_029_29_migration_up_down_up(migrated_schema: str) -> None:
    url = migrated_schema
    cfg = alembic_config(url)
    script = ScriptDirectory.from_config(cfg)

    # alembic heads が 1 本。F-029 のリビジョンの down_revision は P2-c の head
    heads = script.get_heads()
    assert len(heads) == 1, heads
    revision = script.get_revision(heads[0])
    assert revision is not None
    assert revision.path is not None and revision.path.endswith(REVISION_FILE_SUFFIX)
    assert revision.down_revision == "14aa9b4157c2"  # pragma: allowlist secret

    try:
        before = _tables(url)
        assert CHAT_TABLES <= before

        # 索引・UNIQUE・FK ができている
        sessions = _indexes(url, "chat_sessions")
        assert sessions["uq_chat_sessions_token_hash"] == (True, ["token_hash"])
        assert sessions["ix_chat_sessions_updated_at"] == (False, ["updated_at"])
        messages = _indexes(url, "chat_messages")
        assert messages["ix_chat_messages_session_id_id"] == (False, ["chat_session_id", "id"])
        assert messages["ix_chat_messages_created_at"] == (False, ["created_at"])
        fk = _run(
            url,
            "SELECT REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
            "FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'chat_messages' "
            "AND COLUMN_NAME = 'chat_session_id' AND REFERENCED_TABLE_NAME IS NOT NULL",
        )
        assert fk == [("chat_sessions", "id")]
        columns = {
            r[0]: r[1]
            for r in _run(
                url,
                "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'chat_sessions'",
            )
        }
        assert columns["token_hash"] == "char(64)"

        # downgrade で 2 表だけが消え、他の表は変わらない
        command.downgrade(cfg, "-1")
        after_down = _tables(url)
        assert after_down == before - CHAT_TABLES

        command.upgrade(cfg, "head")
        assert _tables(url) == before
    finally:
        command.upgrade(cfg, "head")  # 失敗しても必ず head に戻す


def test_it_029_30_manual_delete_sql_removes_only_old_conversations(
    migrated_schema: str,
) -> None:
    url = migrated_schema
    _run(url, "DELETE FROM chat_messages")
    _run(url, "DELETE FROM chat_sessions")

    def session(name: str, days: int) -> int:
        _run(
            url,
            "INSERT INTO chat_sessions (token_hash, turns, created_at, updated_at) "
            "VALUES (:h, 1, UTC_TIMESTAMP() - INTERVAL :d DAY, UTC_TIMESTAMP() - INTERVAL :d DAY)",
            h=name.ljust(64, "0"),
            d=days,
        )
        return int(
            _run(url, "SELECT id FROM chat_sessions WHERE token_hash=:h", h=name.ljust(64, "0"))[0][
                0
            ]
        )

    def message(session_id: int, body: str, days: int) -> None:
        _run(
            url,
            "INSERT INTO chat_messages "
            "(chat_session_id, role, body_masked, created_at, updated_at) "
            "VALUES (:s, 'user', :b, UTC_TIMESTAMP() - INTERVAL :d DAY, "
            "UTC_TIMESTAMP() - INTERVAL :d DAY)",
            s=session_id,
            b=body,
            d=days,
        )

    old_only = session("old", 91)
    message(old_only, "古い質問", 91)
    old_with_new_message = session("mixed", 91)
    message(old_with_new_message, "古い質問2", 91)
    message(old_with_new_message, "新しい質問", 89)
    only_new_message_in_old_session = session("kept", 91)
    message(only_new_message_in_old_session, "89 日前の質問", 89)
    recent = session("recent", 89)
    message(recent, "89 日前の質問", 89)

    _run(url, "DELETE FROM chat_messages WHERE created_at < UTC_TIMESTAMP() - INTERVAL 90 DAY")
    _run(
        url,
        "DELETE s FROM chat_sessions s LEFT JOIN chat_messages m ON m.chat_session_id = s.id "
        "WHERE s.updated_at < UTC_TIMESTAMP() - INTERVAL 90 DAY AND m.id IS NULL",
    )

    bodies = {r[0] for r in _run(url, "SELECT body_masked FROM chat_messages")}
    assert bodies == {"新しい質問", "89 日前の質問"}
    remaining = {r[0] for r in _run(url, "SELECT id FROM chat_sessions")}
    assert old_only not in remaining  # メッセージが 0 件になった古いセッションは消える
    assert {old_with_new_message, only_new_message_in_old_session, recent} <= remaining
    assert len(remaining) == 3

    _run(url, "DELETE FROM chat_messages")
    _run(url, "DELETE FROM chat_sessions")
