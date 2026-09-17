"""商品カタログ系（DS-TBL-05〜09）。"""

from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class Gender(enum.StrEnum):
    """カテゴリの性別区分。要件の 3 区分（women／men／kids_teen）＋ 共通 all。"""

    women = "women"
    men = "men"
    kids_teen = "kids_teen"
    all = "all"


class Category(IdMixin, TimestampMixin, Base):
    """DS-TBL-05 categories。階層（parent_id）＋性別。"""

    __tablename__ = "categories"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    gender: Mapped[Gender] = mapped_column(
        Enum(Gender, name="category_gender", native_enum=False, length=20),
        nullable=False,
        default=Gender.all,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    parent: Mapped[Category | None] = relationship(remote_side="Category.id", lazy="raise")


class Product(IdMixin, TimestampMixin, Base):
    """DS-TBL-06 products。価格は税込の整数円（DS-DEC-31）。"""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price_incl_tax >= 0", name="price_non_negative"),
        MYSQL_TABLE_ARGS,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    material: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    price_incl_tax: Mapped[int] = mapped_column(Integer, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    variants: Mapped[list[Variant]] = relationship(back_populates="product", lazy="raise")
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", lazy="raise", order_by="ProductImage.sort_order"
    )


class ProductCategory(IdMixin, TimestampMixin, Base):
    """DS-TBL-07 product_categories。複合 UNIQUE。"""

    __tablename__ = "product_categories"
    __table_args__ = (
        UniqueConstraint("product_id", "category_id"),
        MYSQL_TABLE_ARGS,
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class ProductImage(IdMixin, TimestampMixin, Base):
    """DS-TBL-08 product_images。

    `path` はパスのみ保存し、配信ベース URL は `IMAGE_BASE_URL` に持つ（DS-DEC-22）。
    """

    __tablename__ = "product_images"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    product: Mapped[Product] = relationship(back_populates="images", lazy="raise")


class Variant(IdMixin, TimestampMixin, Base):
    """DS-TBL-09 variants。stock は条件付き UPDATE でのみ減算（DS-DEC-08）。"""

    __tablename__ = "variants"
    __table_args__ = (
        CheckConstraint("stock >= 0", name="stock_non_negative"),
        MYSQL_TABLE_ARGS,
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    color: Mapped[str] = mapped_column(String(50), nullable=False)
    size: Mapped[str] = mapped_column(String(20), nullable=False)
    sku: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    product: Mapped[Product] = relationship(back_populates="variants", lazy="raise")
