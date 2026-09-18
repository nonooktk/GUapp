"""注文確定（DS-PRC-014-1 改訂版）と注文照会（DS-API-023）のサービス。

手順（プラン Wave 2 指示の「確定した手順」が正本）:
0. カート特定（無い／未知 → 404。`ordered` → 同じキーの自分の注文なら 200、
   無ければ 409 already_ordered）
1. 注文番号を生成し冪等キーで orders に INSERT（pending_payment）。UNIQUE 違反なら既存注文を
   SELECT し、他人のカートなら 404、payment_failed なら 409、それ以外は 200
2. `UPDATE carts SET status='ordered' WHERE id=? AND status='active'`。0 行 → ROLLBACK → 409
3. 金額を再計算して display と照合（引当の前）。非公開商品は在庫切れ扱い。不一致 → 409 price_changed
4. 明細を variant_id 昇順に条件付き UPDATE で引当。0 行が 1 つでもあれば ROLLBACK → 409 out_of_stock
5. 決済アダプタ authorize
6. ok → accepted・order_items・payments・audit_logs を COMMIT。ng → payment_failed・payments・
   audit_logs を COMMIT した後、別トランザクションで在庫とカートを戻して 409 payment_failed
7. メールアダプタ。例外でも注文は成立（audit_logs に mail.failed）
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Literal

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.mail import MailAdapter, mask_email
from app.adapters.payment import PaymentAdapter
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import CartStatus, Order, OrderStatus, PaymentResult
from app.repositories import carts as carts_repo
from app.repositories import orders as orders_repo
from app.repositories.carts import CartLineRow
from app.repositories.orders import DuplicateIdempotencyKey, OrderItemInput, PendingOrderInput
from app.schemas.order import OrderCreateIn, OrderItemOut, OrderOut
from app.services import order_state
from app.services.checkout import resolve_existing_cart
from app.services.pricing import calc_tax_included, calc_totals
from app.services.settings import get_public_settings

logger = logging.getLogger("app.services.orders")

SUPPORTED_RECEIVE_METHODS = frozenset({"delivery"})
SUPPORTED_PAYMENT_METHODS = frozenset({"card"})

# P1 は配送・カードのみなので応答値は固定（orders 表に payment_method 列は無い）
RECEIVE_METHOD_OUT = "delivery"
PAYMENT_METHOD_OUT = "card"

AUDIT_ORDER_CONFIRM = "order.confirm"
AUDIT_PAYMENT_FAILED = "order.payment_failed"
AUDIT_MAIL_FAILED = "mail.failed"


# ── 応答の組み立て ─────────────────────────────────────────────────────────────


async def build_order_response(session: AsyncSession, order: Order) -> OrderOut:
    items = await orders_repo.list_items(session, order.id)
    return OrderOut(
        order_number=order.order_number,
        status=order.status.value,
        items=[
            OrderItemOut(
                product_name=i.product_name_at_order,
                color=i.color,
                size=i.size,
                unit_price=i.unit_price_at_order,
                quantity=i.quantity,
                line_total=i.unit_price_at_order * i.quantity,
            )
            for i in items
        ],
        subtotal=order.subtotal,
        shipping_fee=order.shipping_fee,
        total=order.total,
        tax_included=calc_tax_included(order.total, order.tax_rate_at_order),
        tax_rate=order.tax_rate_at_order,
        ship_name=order.ship_name,
        ship_postal_code=order.ship_postal_code,
        ship_address=order.ship_address,
        ship_phone=order.ship_phone,
        guest_email=order.guest_email,
        receive_method=RECEIVE_METHOD_OUT,
        payment_method=PAYMENT_METHOD_OUT,
        ordered_at=order.created_at.replace(tzinfo=UTC),
    )


# ── 注文確定 ───────────────────────────────────────────────────────────────────


def _check_supported(body: OrderCreateIn) -> None:
    """P1 未対応の値は 422 unsupported_value（形は正しいので 400 ではない。4.5 の順序 4）。"""
    if body.receive_method not in SUPPORTED_RECEIVE_METHODS:
        raise AppError(422, "unsupported_value", field="receive_method")
    if body.payment_method not in SUPPORTED_PAYMENT_METHODS:
        raise AppError(422, "unsupported_value", field="payment_method")


async def _existing_order_result(
    session: AsyncSession, existing: Order, cart_id: int
) -> tuple[Literal[200], OrderOut]:
    """同じ冪等キーの既存注文を返す。他人のカートの注文なら 404（IDOR 防止・7.5）。"""
    if existing.cart_id != cart_id:
        raise AppError(404, "not_found")
    if existing.status == OrderStatus.payment_failed:
        raise AppError(409, "payment_failed", order_number=existing.order_number)
    return 200, await build_order_response(session, existing)


async def _reject_already_ordered(session: AsyncSession, cart_id: int) -> AppError:
    number = await orders_repo.get_latest_order_number_of_cart(session, cart_id)
    return AppError(409, "already_ordered", order_number=number)


async def _recalculate_and_compare(
    session: AsyncSession, cart_id: int, body: OrderCreateIn
) -> tuple[list[CartLineRow], str]:
    """手順 3。現在の単価・設定で再計算し display と照合する。戻り値は明細と税率。"""
    settings = await get_public_settings(session)
    rows = await carts_repo.fetch_lines(session, cart_id)
    unpublished = [r.variant_id for r in rows if not r.published]
    if unpublished:
        raise AppError(409, "out_of_stock", items=unpublished)
    totals = calc_totals([(r.unit_price, r.quantity) for r in rows], settings)  # 空なら empty_cart
    d = body.display
    if (d.subtotal, d.shipping_fee, d.total) != (
        totals.subtotal,
        totals.shipping_fee,
        totals.total,
    ):
        raise AppError(
            409,
            "price_changed",
            amounts={
                "subtotal": totals.subtotal,
                "shipping_fee": totals.shipping_fee,
                "total": totals.total,
            },
        )
    return rows, settings.tax_rate


async def _reserve_all(session: AsyncSession, rows: list[CartLineRow]) -> None:
    """手順 4。variant_id 昇順で引当（デッドロック回避）。0 行の明細を集めて 409。"""
    failed: list[int] = []
    for r in sorted(rows, key=lambda x: x.variant_id):
        affected = await orders_repo.reserve_stock(
            session, variant_id=r.variant_id, quantity=r.quantity
        )
        if affected == 0:
            failed.append(r.variant_id)
    if failed:
        raise AppError(409, "out_of_stock", items=failed)


async def _maybe_test_delay() -> None:
    """テストモード限定: 金額照合と引当の間の待ち（1.4 #7）。本番経路では import しない。"""
    if get_settings().is_test:
        from app.core import testing_hooks

        await testing_hooks.maybe_delay()


async def _confirm(
    session: AsyncSession,
    cart_id: int,
    body: OrderCreateIn,
    payment: PaymentAdapter,
) -> Order:
    """手順 1〜6。成功なら COMMIT 済みの注文（accepted）を返す。失敗は AppError。

    `cart_id` は int で受ける（ROLLBACK 後は ORM オブジェクトが expire され、
    属性参照が I/O になるため）。
    """
    try:
        # orders.tax_rate_at_order に要るので先に設定を読む（金額の照合自体は手順 3）
        settings = await get_public_settings(session)
        pending = PendingOrderInput(
            idempotency_key=body.idempotency_key,
            cart_id=cart_id,
            guest_email=str(body.guest_email),
            subtotal=body.display.subtotal,
            shipping_fee=body.display.shipping_fee,
            total=body.display.total,
            tax_rate_at_order=settings.tax_rate,
            ship_name=body.ship_name,
            ship_postal_code=body.ship_postal_code,
            ship_address=body.ship_address,
            ship_phone=body.ship_phone,
        )

        # 1. INSERT orders（pending_payment）
        order = await orders_repo.insert_pending_order(session, pending)

        # 2. カートを active → ordered（条件付き UPDATE）
        if await orders_repo.mark_cart_ordered(session, cart_id) == 0:
            await session.rollback()
            raise await _reject_already_ordered(session, cart_id)

        # 3. 金額の再計算と照合（引当の前）
        rows, _ = await _recalculate_and_compare(session, cart_id, body)

        await _maybe_test_delay()

        # 4. 引当
        await _reserve_all(session, rows)

        # 5. 決済
        result = await payment.authorize(order.order_number, order.total)

        if result == "ok":
            # 6-ok
            order_state.assert_transition(order.status, OrderStatus.accepted)
            await orders_repo.set_status(session, order.id, OrderStatus.accepted)
            await orders_repo.insert_order_items(
                session,
                order.id,
                [
                    OrderItemInput(
                        variant_id=r.variant_id,
                        product_name=r.product_name,
                        color=r.color,
                        size=r.size,
                        unit_price=r.unit_price,
                        quantity=r.quantity,
                    )
                    for r in rows
                ],
            )
            await orders_repo.insert_payment(
                session,
                order.id,
                provider=payment.provider,
                amount=order.total,
                result=PaymentResult.ok,
            )
            await orders_repo.insert_audit_log(
                session,
                action=AUDIT_ORDER_CONFIRM,
                order_number=order.order_number,
                detail={"total": order.total, "provider": payment.provider},
            )
            await session.commit()
            return order

        # 6-ng: 注文は決済失敗で残し、在庫とカートは別トランザクションで戻す
        order_state.assert_transition(order.status, OrderStatus.payment_failed)
        await orders_repo.set_status(session, order.id, OrderStatus.payment_failed)
        await orders_repo.insert_payment(
            session,
            order.id,
            provider=payment.provider,
            amount=order.total,
            result=PaymentResult.ng,
        )
        await orders_repo.insert_audit_log(
            session,
            action=AUDIT_PAYMENT_FAILED,
            order_number=order.order_number,
            detail={"total": order.total, "provider": payment.provider},
        )
        await session.commit()

        for r in rows:
            await orders_repo.restore_stock(session, variant_id=r.variant_id, quantity=r.quantity)
        await orders_repo.restore_cart_active(session, cart_id)
        await session.commit()
        logger.info("決済 NG order=%s（在庫・カートを戻しました）", order.order_number)
        raise AppError(409, "payment_failed", order_number=order.order_number)
    except AppError:
        raise
    except DuplicateIdempotencyKey:
        raise
    except Exception:
        await session.rollback()
        raise


async def create_order(
    session: AsyncSession,
    token: str | None,
    body: OrderCreateIn,
    *,
    payment: PaymentAdapter,
    mail: MailAdapter,
) -> tuple[Literal[200, 201], OrderOut]:
    """注文確定の入口。戻り値は (HTTP ステータス, 注文応答)。"""
    settings = get_settings()
    if settings.is_test:
        from app.core import testing_hooks

        async with testing_hooks.allocation_counter.track():
            return await _create_order_with_deadlock_retry(
                session, token, body, payment=payment, mail=mail
            )
    return await _create_order_with_deadlock_retry(session, token, body, payment=payment, mail=mail)


# MySQL: 1213 = Deadlock found、1205 = Lock wait timeout exceeded
_RETRYABLE_MYSQL_ERRORS = frozenset({1213, 1205})


def _is_retryable_lock_error(exc: OperationalError) -> bool:
    args = getattr(exc.orig, "args", ())
    return bool(args) and args[0] in _RETRYABLE_MYSQL_ERRORS


async def _create_order_with_deadlock_retry(
    session: AsyncSession,
    token: str | None,
    body: OrderCreateIn,
    *,
    payment: PaymentAdapter,
    mail: MailAdapter,
) -> tuple[Literal[200, 201], OrderOut]:
    """デッドロック（1213）なら ROLLBACK して手順 0 から 1 回だけやり直す。

    同じカートへの同時確定では、手順 1 の `INSERT orders` が FK 検査で carts 行の共有ロックを
    双方で取り、手順 2 の `UPDATE carts` で互いに排他ロック待ちになってデッドロックする
    （InnoDB が一方を犠牲にする）。犠牲側はやり直すと、相手の COMMIT 後の状態を見て
    409 already_ordered（キーが違う）または 200（同じキー）に正しく着地する。
    """
    for attempt in range(2):
        try:
            return await _create_order(session, token, body, payment=payment, mail=mail)
        except OperationalError as exc:
            if attempt == 0 and _is_retryable_lock_error(exc):
                logger.warning(
                    "注文確定でロック競合（%s）。ROLLBACK して 1 回やり直します", exc.orig.args[0]
                )
                await session.rollback()
                continue
            raise
    raise AssertionError("unreachable")  # pragma: no cover


async def _create_order(
    session: AsyncSession,
    token: str | None,
    body: OrderCreateIn,
    *,
    payment: PaymentAdapter,
    mail: MailAdapter,
) -> tuple[Literal[200, 201], OrderOut]:
    # 0. カート特定（404）→ P1 未対応値（422）
    cart = await resolve_existing_cart(session, token)
    cart_id, cart_status = cart.id, cart.status  # ROLLBACK 後も使えるよう素の値で持つ
    _check_supported(body)
    if cart_status != CartStatus.active:
        existing = await orders_repo.get_by_idempotency_key(session, body.idempotency_key)
        if existing is not None:
            return await _existing_order_result(session, existing, cart_id)
        raise await _reject_already_ordered(session, cart_id)

    # 1〜6
    try:
        order = await _confirm(session, cart_id, body, payment)
    except AppError:
        # ROLLBACK 済み（または NG を COMMIT 済み）のまま伝える
        await session.rollback()
        raise
    except DuplicateIdempotencyKey:
        await session.rollback()
        existing = await orders_repo.get_by_idempotency_key(session, body.idempotency_key)
        if existing is None:
            # UNIQUE 違反したのに見えない＝相手が ROLLBACK した。クライアントに再送させる
            logger.warning("冪等キー衝突後に既存注文が見つかりません（相手が ROLLBACK）")
            raise AppError(409, "already_ordered", order_number=None) from None
        return await _existing_order_result(session, existing, cart_id)

    # COMMIT 後の値（status は Core UPDATE で変えた、created_at は server_default）を読み直す
    await session.refresh(order)

    # 7. メール（失敗しても注文は成立）
    response = await build_order_response(session, order)
    try:
        await mail.send_order_confirmation(response)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "確認メール送信に失敗 order=%s to=%s (%s)",
            order.order_number,
            mask_email(order.guest_email),
            type(exc).__name__,
        )
        await orders_repo.insert_audit_log(
            session,
            action=AUDIT_MAIL_FAILED,
            order_number=order.order_number,
            detail={"error": type(exc).__name__},
        )
        await session.commit()
    logger.info(
        "注文確定 order=%s total=%d to=%s",
        order.order_number,
        order.total,
        mask_email(order.guest_email),
    )
    return 201, response


# ── 注文照会 ───────────────────────────────────────────────────────────────────


async def lookup_order(session: AsyncSession, order_number: str, guest_email: str) -> OrderOut:
    """番号不存在・メール不一致は区別せず 404（7.5）。"""
    order = await orders_repo.get_by_number_and_email(session, order_number, guest_email)
    if order is None:
        raise AppError(404, "not_found")
    return await build_order_response(session, order)
