"""受け取り店舗（DS-TBL-10 stores。P3 から前倒し）。設計仕様書 P2 追補b 5.2・DS-DEC-79。"""

from __future__ import annotations

from sqlalchemy import CHAR, Boolean, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class Store(IdMixin, TimestampMixin, Base):
    """API は店舗を `code` で指す（内部 ID は応答に出さない）。

    `postal_code`・`address` は店舗受け取りの注文の `ship_postal_code`・`ship_address` に
    コピーする（DS-PRC-014-3）。実在の店舗・住所に似せない（DS-DEC-41）。
    """

    __tablename__ = "stores"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    # 英小文字・数字・ハイフン（^[a-z0-9-]{1,32}$）
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefecture: Mapped[str] = mapped_column(String(20), nullable=False)
    # ハイフンなし 7 桁
    postal_code: Mapped[str] = mapped_column(CHAR(7), nullable=False)
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    pickup_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
