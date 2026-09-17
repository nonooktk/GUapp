"""カート系（DS-TBL-12・13）。"""

from __future__ import annotations

import enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class CartStatus(enum.StrEnum):
    active = "active"
    ordered = "ordered"
    merged = "merged"


class Cart(IdMixin, TimestampMixin, Base):
    """DS-TBL-12 carts。member_id は P1 では列のみ（FK は P2 で members 作成後に張る）。"""

    __tablename__ = "carts"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    member_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    anonymous_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    status: Mapped[CartStatus] = mapped_column(
        Enum(CartStatus, name="cart_status", native_enum=False, length=20),
        nullable=False,
        default=CartStatus.active,
    )

    items: Mapped[list[CartItem]] = relationship(back_populates="cart", lazy="raise")


class CartItem(IdMixin, TimestampMixin, Base):
    """DS-TBL-13 cart_items。(cart_id, variant_id) UNIQUE。"""

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "variant_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        MYSQL_TABLE_ARGS,
    )

    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), nullable=False)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    cart: Mapped[Cart] = relationship(back_populates="items", lazy="raise")
