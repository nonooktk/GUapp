"""セッションとログイン試行（DS-TBL-03 sessions・DS-TBL-26 login_attempts）。P2 追補b 5.2。

どちらも会員と管理者（P2-c）の両方を指すため、`subject_id`・`identifier` に外部キーを張らない。
モジュール名は標準の `session` と紛れないよう `app.models.session`（`app.core.session` は別物）。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import CHAR, BigInteger, Boolean, DateTime, Enum, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class SubjectType(enum.StrEnum):
    member = "member"
    staff = "staff"


class AuthSession(IdMixin, TimestampMixin, Base):
    """DS-TBL-03 sessions。Cookie 値（43 文字）の SHA-256 の 16 進だけを保存する（DS-DEC-72）。

    クラス名は SQLAlchemy の `Session` と区別するため `AuthSession`。
    `last_seen_at` は作成時刻のまま。P2-b は更新しない（DS-PRC-035）。
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_subject_type_subject_id", "subject_type", "subject_id"),
        Index("ix_sessions_expires_at", "expires_at"),
        MYSQL_TABLE_ARGS,
    )

    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(SubjectType, name="session_subject_type", native_enum=False, length=20),
        nullable=False,
    )
    # members.id または staff.id。外部キーは張らない（2 つの表を指すため）
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LoginAttempt(IdMixin, TimestampMixin, Base):
    """DS-TBL-26 login_attempts。ロック（メール単位）と IP 単位の制限の判定元（DS-DEC-70）。

    `identifier` は正規化したメール（会員）またはログイン ID（管理者）の SHA-256 の 16 進。
    会員の有無に関係なく記録する（DS-DEC-71）。平文のメールは保存しない。
    `ip` は個人関連情報。24 時間を過ぎた行は削除する（DS-PRC-032 手順 8）。
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_subject_type_identifier_at", "subject_type", "identifier", "at"),
        Index("ix_login_attempts_ip_at", "ip", "at"),
        Index("ix_login_attempts_at", "at"),
        MYSQL_TABLE_ARGS,
    )

    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(SubjectType, name="login_attempt_subject_type", native_enum=False, length=20),
        nullable=False,
    )
    identifier: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # IPv6 の最大長（45 文字）
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    # created_at と同じ値。判定条件に使う（audit_logs.at と同じ形）
    at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
