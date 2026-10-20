"""管理者（DS-TBL-04 staff。P2-c 先出し）。設計仕様書 P2 追補b 5.2・DS-DEC-82。

P2-b では表だけを作り、行も API も作らない。管理認証（F-035）は P2-c。
パスワードは会員と同じ argon2id（`app/core/passwords.py` を共用）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class Staff(IdMixin, TimestampMixin, Base):
    __tablename__ = "staff"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    login_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 本編 5.2 の「単一ロール」。P2-c で値の扱いを決める
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="staff", server_default="staff"
    )
    # members.locked_until と同じく予約（P2-b は使わない）
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
