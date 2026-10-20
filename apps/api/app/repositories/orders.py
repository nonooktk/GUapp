"""注文の読み書き（DS-TBL-14〜16・23、DS-PRC-014-1）。

- 在庫引当は `UPDATE variants SET stock = stock - :q WHERE id = :id AND stock >= :q` の 1 文
  （SQLAlchemy Core。DS-DEC-08・プラン 5 章）。戻り値は影響行数
- カートの `active → ordered` も条件付き UPDATE 1 文（DS-DEC-07 層 2）
- 注文の INSERT は冪等キーの UNIQUE 違反を `DuplicateIdempotencyKey` に、注文番号の衝突は
  1 回だけ再生成に変換する（DS-PRC-014-1 手順 1・8）
- P2-b: 会員の紐づけ（`member_id`）・店舗受け取り（`store_id`・受け取りコード）を INSERT に含める。
  受け取りコード（`orders.pickup_code` UNIQUE）の衝突も注文番号と同じく 1 回だけ再生成する
  （DS-PRC-014-3 手順 1）
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import internal_error
from app.models import (
    ActorType,
    AuditLog,
    Cart,
    CartStatus,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentProvider,
    PaymentResult,
    ReceiveMethod,
    Variant,
)
from app.services.order_number import generate_order_number
from app.services.pickup_code import generate_pickup_code

logger = logging.getLogger("app.repositories.orders")


class DuplicateIdempotencyKey(Exception):
    """同じ冪等キーの注文が既にある（呼び手は ROLLBACK 後に既存注文を SELECT する）。"""


@dataclass(frozen=True)
class PendingOrderInput:
    idempotency_key: str
    cart_id: int
    guest_email: str
    subtotal: int
    shipping_fee: int
    total: int
    tax_rate_at_order: str
    ship_name: str
    ship_postal_code: str
    ship_address: str
    ship_phone: str
    # ── P2-b（DS-PRC-014-3）。既定値は P1 の呼び出しと互換 ──
    member_id: int | None = None
    receive_method: str = "delivery"
    store_id: int | None = None


def _violates(exc: IntegrityError, column: str) -> bool:
    """UNIQUE 違反がどの列か。

    MySQL: `for key 'orders.uq_orders_<col>'`／SQLite: `orders.<col>` のどちらも列名を含む。
    """
    return column in str(exc.orig)


async def insert_pending_order(
    session: AsyncSession,
    data: PendingOrderInput,
    *,
    generate: Callable[[], str] = generate_order_number,
    generate_pickup: Callable[[], str] | None = None,
) -> Order:
    """status=pending_payment で INSERT。注文番号・受け取りコードの衝突は 1 回だけ再生成。

    2 回目も衝突したら 500。冪等キーの衝突は `DuplicateIdempotencyKey`。SAVEPOINT
    （begin_nested）で囲むので、失敗しても外側のトランザクションは生きたまま
    （MySQL・SQLite とも）。受け取りコードは `receive_method="store"` のときだけ作る。
    `generate_pickup` を省略すると、呼び出し時点の `generate_pickup_code` を使う
    （テストがモジュール属性を差し替えられる）。
    """
    is_store = data.receive_method == ReceiveMethod.store.value
    pickup_gen = generate_pickup if generate_pickup is not None else generate_pickup_code
    last_exc: IntegrityError | None = None
    number: str | None = None
    pickup: str | None = None
    for attempt in range(2):
        # 衝突した項目だけ作り直す（もう一方は同じ値で再試行してよい）
        if number is None:
            number = generate()
        if is_store and pickup is None:
            pickup = pickup_gen()
        order = Order(
            order_number=number,
            idempotency_key=data.idempotency_key,
            member_id=data.member_id,
            guest_email=data.guest_email,
            status=OrderStatus.pending_payment,
            receive_method=ReceiveMethod(data.receive_method),
            store_id=data.store_id,
            pickup_code=pickup,
            subtotal=data.subtotal,
            shipping_fee=data.shipping_fee,
            discount=0,
            total=data.total,
            tax_rate_at_order=data.tax_rate_at_order,
            ship_name=data.ship_name,
            ship_postal_code=data.ship_postal_code,
            ship_address=data.ship_address,
            ship_phone=data.ship_phone,
            cart_id=data.cart_id,
        )
        try:
            async with session.begin_nested():
                session.add(order)
                await session.flush()
            return order
        except IntegrityError as exc:
            if _violates(exc, "idempotency_key"):
                raise DuplicateIdempotencyKey() from exc
            if _violates(exc, "order_number"):
                logger.warning("注文番号が衝突しました（再生成 %d 回目）", attempt + 1)
                last_exc = exc
                number = None
                continue
            if is_store and _violates(exc, "pickup_code"):
                logger.warning("受け取りコードが衝突しました（再生成 %d 回目）", attempt + 1)
                last_exc = exc
                pickup = None
                continue
            raise
    logger.error("注文番号または受け取りコードの再生成後も衝突しました")
    raise internal_error() from last_exc


async def get_by_idempotency_key(session: AsyncSession, key: str) -> Order | None:
    return (
        await session.execute(select(Order).where(Order.idempotency_key == key))
    ).scalar_one_or_none()


async def get_latest_order_number_of_cart(session: AsyncSession, cart_id: int) -> str | None:
    """カートに紐づく（決済失敗以外の）最新の注文番号。409 already_ordered の本文用。"""
    return (
        await session.execute(
            select(Order.order_number)
            .where(Order.cart_id == cart_id, Order.status != OrderStatus.payment_failed)
            .order_by(Order.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def mark_cart_ordered(session: AsyncSession, cart_id: int) -> int:
    """`UPDATE carts SET status='ordered' WHERE id=? AND status='active'`。影響行数を返す。"""
    result = await session.execute(
        update(Cart)
        .where(Cart.id == cart_id, Cart.status == CartStatus.active)
        .values(status=CartStatus.ordered)
    )
    return int(result.rowcount)


async def restore_cart_active(session: AsyncSession, cart_id: int) -> int:
    """決済 NG 後の戻し: `ordered → active`（影響行数を返す）。"""
    result = await session.execute(
        update(Cart)
        .where(Cart.id == cart_id, Cart.status == CartStatus.ordered)
        .values(status=CartStatus.active)
    )
    return int(result.rowcount)


async def reserve_stock(session: AsyncSession, *, variant_id: int, quantity: int) -> int:
    """在庫引当。`stock >= :q` のときだけ減算し、影響行数（0 か 1）を返す。"""
    result = await session.execute(
        update(Variant)
        .where(Variant.id == variant_id, Variant.stock >= quantity)
        .values(stock=Variant.stock - quantity)
    )
    return int(result.rowcount)


async def restore_stock(session: AsyncSession, *, variant_id: int, quantity: int) -> None:
    """引当の戻し（決済 NG 時。別トランザクションで呼ぶ）。"""
    await session.execute(
        update(Variant).where(Variant.id == variant_id).values(stock=Variant.stock + quantity)
    )


async def set_status(session: AsyncSession, order_id: int, status: OrderStatus) -> None:
    await session.execute(update(Order).where(Order.id == order_id).values(status=status))


@dataclass(frozen=True)
class OrderItemInput:
    variant_id: int
    product_name: str
    color: str
    size: str
    unit_price: int
    quantity: int


async def insert_order_items(
    session: AsyncSession, order_id: int, items: list[OrderItemInput]
) -> None:
    session.add_all(
        OrderItem(
            order_id=order_id,
            variant_id=i.variant_id,
            product_name_at_order=i.product_name,
            color=i.color,
            size=i.size,
            unit_price_at_order=i.unit_price,
            quantity=i.quantity,
            discount=0,
        )
        for i in items
    )
    await session.flush()


async def insert_payment(
    session: AsyncSession, order_id: int, *, provider: str, amount: int, result: PaymentResult
) -> None:
    session.add(
        Payment(
            order_id=order_id,
            provider=PaymentProvider(provider),
            provider_ref=None,
            amount=amount,
            result=result,
            refunded_amount=0,
        )
    )
    await session.flush()


async def insert_audit_log(
    session: AsyncSession, *, action: str, order_number: str, detail: dict | None = None
) -> None:
    session.add(
        AuditLog(
            actor_type=ActorType.system,
            actor_id=None,
            action=action,
            target_type="order",
            target_id=order_number,
            detail=detail,
        )
    )
    await session.flush()


async def get_by_id(session: AsyncSession, order_id: int) -> Order | None:
    return await session.get(Order, order_id)


async def get_by_number_and_email(
    session: AsyncSession, order_number: str, guest_email: str
) -> Order | None:
    """番号とメールの両方が一致する注文だけ返す（不一致・不存在は None → 404）。"""
    return (
        await session.execute(
            select(Order).where(
                Order.order_number == order_number, Order.guest_email == guest_email
            )
        )
    ).scalar_one_or_none()


async def list_items(session: AsyncSession, order_id: int) -> list[OrderItem]:
    rows = await session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
    )
    return list(rows.scalars().all())
