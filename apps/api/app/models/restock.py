"""再入荷通知の申込（DS-TBL-20 restock_notifications）。設計仕様書 P2 追補b 5.2・DS-DEC-80。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class RestockNotification(IdMixin, TimestampMixin, Base):
    """(variant_id, email) で 1 行。再申込は `notified_at` を NULL に戻す（DS-PRC-007）。"""

    __tablename__ = "restock_notifications"
    __table_args__ = (
        UniqueConstraint("variant_id", "email"),
        Index("ix_restock_notifications_variant_id_notified_at", "variant_id", "notified_at"),
        Index("ix_restock_notifications_email", "email"),
        MYSQL_TABLE_ARGS,
    )

    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="CASCADE"), nullable=False
    )
    # DS-API-030 と同じ正規化（NFKC・小文字化・前後空白除去）
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    # 申込時に有効なセッションがあれば入れる
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    # NULL は未通知。通知の直前に設定する（DS-PRC-007a）
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
