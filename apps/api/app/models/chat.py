"""AI アシスタントの会話（DS-TBL-24・25。設計仕様書 P2 追補d 5 章）。

- `chat_sessions`: 利用者側の識別は Cookie `chat_token`（DB には SHA-256 の 16 進だけ保存）。
  `member_id` は作らない（P2-b の `members` に依存させない。DS-DEC-100）
- `chat_messages`: 質問はマスク後、応答は検査後の本文。IP・User-Agent・Cookie 値は保存しない
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CHAR,
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class ChatRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"


class ChatSession(IdMixin, TimestampMixin, Base):
    """DS-TBL-24 chat_sessions。`turns` は条件付き UPDATE でだけ増減する（DS-DEC-98）。"""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        # 90 日削除用（手動 SQL。8.5）
        Index("ix_chat_sessions_updated_at", "updated_at"),
        MYSQL_TABLE_ARGS,
    )

    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    # 範囲外の案内を最初に出した時刻（DS-DEC-103）
    handoff_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(IdMixin, TimestampMixin, Base):
    """DS-TBL-25 chat_messages。"""

    __tablename__ = "chat_messages"
    __table_args__ = (
        # 履歴の取得用
        Index("ix_chat_messages_session_id_id", "chat_session_id", "id"),
        # 日次の数え上げと 90 日削除用
        Index("ix_chat_messages_created_at", "created_at"),
        MYSQL_TABLE_ARGS,
    )

    chat_session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(
        Enum(ChatRole, name="chat_role", native_enum=False, length=20), nullable=False
    )
    body_masked: Mapped[str] = mapped_column(Text, nullable=False)
    # 応答で出したカードの商品 ID の配列
    product_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    # 応答行だけ入る: recommend／faq／clarify／out_of_scope
    intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 応答行だけ入る: LLM の usage の値（費用の確認用。DS-DEC-106）
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
