"""レビュー（DS-TBL-19 reviews）。設計仕様書 P2 追補b 5.2・DS-DEC-81。

P2-b は seed だけが入れる。投稿は P3（F-020）。サイズ感の集計の元（DS-PRC-003a）。
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class ReviewFit(enum.StrEnum):
    """サイズ感。NULL は「サイズ感の回答なし」で集計に入れない。"""

    small = "small"
    just = "just"
    large = "large"


class Review(IdMixin, TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
        Index("ix_reviews_product_id_approved", "product_id", "approved"),
        MYSQL_TABLE_ARGS,
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    # seed のレビューは NULL。投稿（P3）で会員を入れる
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fit: Mapped[ReviewFit | None] = mapped_column(
        Enum(ReviewFit, name="review_fit", native_enum=False, length=20), nullable=True
    )
    # 真のものだけを集計・表示する
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
