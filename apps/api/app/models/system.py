"""設定・監査系（DS-TBL-21・23）。"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class SystemSetting(IdMixin, TimestampMixin, Base):
    """DS-TBL-21 system_settings。tax_rate は JSON 文字列 "0.10" で保持（DS-PRC-021）。"""

    __tablename__ = "system_settings"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")


class ActorType(enum.StrEnum):
    member = "member"
    staff = "staff"
    system = "system"


class AuditLog(IdMixin, TimestampMixin, Base):
    """DS-TBL-23 audit_logs。`at` に索引（90 日削除ジョブ用。P2）。"""

    __tablename__ = "audit_logs"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type", native_enum=False, length=20), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[Any] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
