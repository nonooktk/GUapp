"""注文・決済系（DS-TBL-14〜16）。"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MYSQL_TABLE_ARGS, Base, IdMixin, TimestampMixin


class OrderStatus(enum.StrEnum):
    """注文状態 8 値（設計仕様書 5.3）。遷移表は要件定義書 5.5 が正本。"""

    pending_payment = "pending_payment"
    accepted = "accepted"
    preparing = "preparing"
    shipped = "shipped"
    delivered = "delivered"
    pickup_expired = "pickup_expired"
    cancelled = "cancelled"
    payment_failed = "payment_failed"


class ReceiveMethod(enum.StrEnum):
    delivery = "delivery"
    store = "store"


class PaymentProvider(enum.StrEnum):
    stub = "stub"
    stripe = "stripe"


class PaymentResult(enum.StrEnum):
    ok = "ok"
    ng = "ng"
    refunded = "refunded"


class Order(IdMixin, TimestampMixin, Base):
    """DS-TBL-14 orders。配送先は注文時点の値をコピーして保持する。"""

    __tablename__ = "orders"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    order_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # P1 は列のみ。P2 で members への FK を張る
    member_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    guest_email: Mapped[str] = mapped_column(String(254), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", native_enum=False, length=20),
        nullable=False,
        default=OrderStatus.pending_payment,
        index=True,
    )
    receive_method: Mapped[ReceiveMethod] = mapped_column(
        Enum(ReceiveMethod, name="receive_method", native_enum=False, length=20),
        nullable=False,
        default=ReceiveMethod.delivery,
    )
    # stores は P3 なので FK 無し
    store_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pickup_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 金額（整数円。DS-DEC-31）
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    shipping_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    # "0.10" 形式の文字列（system_settings.tax_rate と同じ表現）
    tax_rate_at_order: Mapped[str] = mapped_column(String(10), nullable=False)

    # 配送先（DS-PRC-014-1 の入力形式）
    ship_name: Mapped[str] = mapped_column(String(50), nullable=False)
    ship_postal_code: Mapped[str] = mapped_column(String(7), nullable=False)
    ship_address: Mapped[str] = mapped_column(String(200), nullable=False)
    ship_phone: Mapped[str] = mapped_column(String(11), nullable=False)

    cart_id: Mapped[int] = mapped_column(
        ForeignKey("carts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    items: Mapped[list[OrderItem]] = relationship(back_populates="order", lazy="raise")
    payments: Mapped[list[Payment]] = relationship(back_populates="order", lazy="raise")


class OrderItem(IdMixin, TimestampMixin, Base):
    """DS-TBL-15 order_items。確定時単価・商品名を保持（REQ-FR-505）。"""

    __tablename__ = "order_items"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("variants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_name_at_order: Mapped[str] = mapped_column(String(200), nullable=False)
    color: Mapped[str] = mapped_column(String(50), nullable=False)
    size: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price_at_order: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # coupons は P2 なので FK 無し
    coupon_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")


class Payment(IdMixin, TimestampMixin, Base):
    """DS-TBL-16 payments。カード情報は持たない。"""

    __tablename__ = "payments"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, name="payment_provider", native_enum=False, length=20),
        nullable=False,
    )
    provider_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[PaymentResult] = mapped_column(
        Enum(PaymentResult, name="payment_result", native_enum=False, length=20),
        nullable=False,
    )
    refunded_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    order: Mapped[Order] = relationship(back_populates="payments", lazy="raise")
