"""管理者（DS-TBL-04 staff）。設計仕様書 P2 追補b 5.2・DS-DEC-82、P2 追補c 5.2・DS-DEC-111。

P2-b で表だけを作り、P2-c（F-035 管理認証）で行（seed）と API を足した。
パスワードは会員と同じ argon2id（`app/core/passwords.py` を共用）。
ロールは `staff` の 1 つ。DB の CHECK 制約 `ck_staff_role_allowed` で想定外の値を止める
（ロールを増やすときは、この制約を 1 リビジョンで差し替える）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class Staff(IdMixin, TimestampMixin, Base):
    __tablename__ = "staff"
    __table_args__ = (
        # 制約名は命名規則で `ck_staff_role_allowed` になる（DS-DEC-111）
        CheckConstraint("role IN ('staff')", name="role_allowed"),
        MYSQL_TABLE_ARGS,
    )

    login_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 本編 5.2 の「単一ロール」。許可する値は `ALLOWED_ROLES`（core/admin_session.py）と CHECK 制約
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="staff", server_default="staff"
    )
    # members.locked_until と同じく予約（P2-b は使わない）
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
