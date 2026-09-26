"""コンテンツ系（DS-TBL-22）。

FAQ・静的ページ・お知らせ・特集を 1 表で表す（設計仕様書 P2 追補a 5.1）。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class ContentKind(enum.StrEnum):
    """`feature`／`news`／`faq`／`static` の 4 値。"""

    feature = "feature"
    news = "news"
    faq = "faq"
    static = "static"


class Content(IdMixin, TimestampMixin, Base):
    """DS-TBL-22 contents。

    `published` 列は持たず、`publish_from`／`publish_to`（ともに UTC・naive）の
    掲載期間のみで公開・非公開を表す（DS-DEC-40。判定は `app.services.content` を参照）。
    """

    __tablename__ = "contents"
    __table_args__ = (
        Index("ix_contents_kind_publish_from", "kind", "publish_from"),
        MYSQL_TABLE_ARGS,
    )

    kind: Mapped[ContentKind] = mapped_column(
        Enum(ContentKind, name="content_kind", native_enum=False, length=20),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    publish_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    publish_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
