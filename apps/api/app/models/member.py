"""会員系（DS-TBL-01 members・DS-TBL-27 email_tokens）。設計仕様書 P2 追補b 5.2。

- `members.email` は NFKC 正規化・前後空白除去・小文字化のあとの値（DS-DEC-69）。
  照合順序 `utf8mb4_0900_ai_ci` は大文字小文字を区別しないため UNIQUE も同じ基準で働く。
- `locked_until` は P2-b では使わない（ロックは `login_attempts` の集計で判定。DS-DEC-70）。
  P3 の F-039（手動解除）のために残す。
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class MemberGender(enum.StrEnum):
    female = "female"
    male = "male"
    other = "other"
    no_answer = "no_answer"


class EmailTokenPurpose(enum.StrEnum):
    verify_email = "verify_email"
    reset_password = "reset_password"


class Member(IdMixin, TimestampMixin, Base):
    """DS-TBL-01 members。パスワードは argon2id のエンコード済み文字列（`$argon2id$…`）。"""

    __tablename__ = "members"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[MemberGender | None] = mapped_column(
        Enum(MemberGender, name="member_gender", native_enum=False, length=20), nullable=True
    )
    personalize_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # UTC。メール確認の完了時刻（DS-API-031）
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # P2-b は使わない（DS-DEC-70）。F-039 のために残す
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 削除請求時の匿名化（F-026・P3）。NULL でなければログインもセッションも無効
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmailToken(IdMixin, TimestampMixin, Base):
    """DS-TBL-27 email_tokens。メール確認（24 時間）とパスワード再設定（1 時間）のトークン。

    DB には SHA-256 の 16 進（64 文字）だけを保存し、生の値（43 文字）は保存しない。
    """

    __tablename__ = "email_tokens"
    __table_args__ = (
        Index("ix_email_tokens_member_id_purpose", "member_id", "purpose"),
        MYSQL_TABLE_ARGS,
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[EmailTokenPurpose] = mapped_column(
        Enum(EmailTokenPurpose, name="email_token_purpose", native_enum=False, length=20),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
