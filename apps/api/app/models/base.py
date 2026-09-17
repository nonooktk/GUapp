"""モデル共通基底（設計仕様書 5.2 共通事項）。

- 主キー `id BIGINT AUTO_INCREMENT`
- 全表に `created_at`・`updated_at`（DATETIME・UTC・server_default now・onupdate）
- 文字コードは utf8mb4（MySQL 側のテーブルオプション）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 制約名を一定にして Alembic の autogenerate と衝突しないようにする
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """`created_at`・`updated_at`。

    UTC。MySQL の DATETIME はタイムゾーンを持たないため naive で扱う。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class IdMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


# MySQL 用の共通テーブルオプション（SQLite などでは無視される）
MYSQL_TABLE_ARGS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}
