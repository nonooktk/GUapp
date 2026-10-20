"""管理：注文の検索・詳細・状態の更新（DS-PRC-053・053b。設計仕様書 P2 追補c 3.3・4.4・4.6・5.6）。

担当レーン: C-3。

- **検索**: 状態・受け取り方法・期間・注文番号・メールで AND に絞る。注文番号とメールは完全一致だけ
  （部分一致・氏名・電話での検索は作らない。DS-DEC-118）。期間は JST の暦日で、両端を含み、
  最大 366 日（DS-DEC-125）。氏名・電話・住所は読み出さず、メールはマスクして返す
- **詳細**: 氏名、配送のときの郵便番号・住所は全文、電話は末尾 4 桁、メールはマスク。
  受け取りコードは返さない。取得を `admin.order.view` として `audit_logs` に記録し、
  記録できなければ個人情報を返さない（INSERT の失敗は未捕捉例外 → 500。
  応答はそのあとに組み立てる）
- **状態の更新**: 更新先は `preparing`・`shipped`・`delivered` の 3 つだけ（DS-DEC-117）。
  `expected_*` は使わず、行を `FOR UPDATE` で読んで遷移表（`order_state`）で判定する（DS-DEC-113）。
  判定の順序は 404 → 422（更新先）→ 422（追跡番号）→ 409（遷移表）。顧客へのメールは送らない

呼び出すだけのもの（変更しない）: `order_state`・`order_status`・`admin_audit`・`pricing`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_session import CurrentStaff
from app.core.errors import AppError
from app.models import Order, OrderStatus, ReceiveMethod
from app.repositories import admin_orders as repo
from app.schemas.admin_common import Page, PageParams, build_page
from app.schemas.admin_orders import (
    AdminCustomerOut,
    AdminOrderDetailOut,
    AdminOrderItemOut,
    AdminOrderListItemOut,
    AdminOrderStoreOut,
    AdminPaymentOut,
    OrderStatusUpdateOut,
    TransitionOut,
)
from app.services import admin_audit, order_state, order_status
from app.services.mask import mask_email, mask_phone
from app.services.order_history import is_order_number_shape
from app.services.order_number import JST
from app.services.pricing import calc_tax_included

# 期間の上限（暦日。両端を含む）
MAX_PERIOD_DAYS = 366

# 管理画面から更新できる先。表示の並びもこの順（4.6 の表）
MANAGEABLE_TARGETS: tuple[OrderStatus, ...] = (
    OrderStatus.preparing,
    OrderStatus.shipped,
    OrderStatus.delivered,
)


@dataclass(frozen=True, slots=True)
class OrderSearchParams:
    """検証・正規化済みの検索条件（形の検査は入口〈ルーター〉で済んでいる）。"""

    status: OrderStatus | None = None
    receive_method: ReceiveMethod | None = None
    date_from: date | None = None
    date_to: date | None = None
    order_number: str | None = None
    email: str | None = None


# ── 期間（JST の暦日 → UTC の範囲。DS-DEC-125）────────────────────────────────────

_YMD_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_ymd(text: str) -> date:
    """`YYYY-MM-DD`（ASCII 数字だけ・実在する日付・UTC に直せる範囲）。違えば `ValueError`。

    `2026-13-01`・`2026/10/01`・全角数字・`2026-02-30` は拒否する。
    """
    if _YMD_RE.fullmatch(text) is None:
        raise ValueError("YYYY-MM-DD の形ではありません")
    parsed = date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    period_bounds(parsed, parsed)  # UTC に直せない範囲（0001-01-01・9999-12-31）は ValueError
    return parsed


def jst_midnight_as_utc(day: date) -> datetime:
    """JST の `day` の 0:00 を UTC の naive datetime にする（DB の `created_at` と同じ表現）。"""
    return datetime(day.year, day.month, day.day, tzinfo=JST).astimezone(UTC).replace(tzinfo=None)


def period_bounds(
    date_from: date | None, date_to: date | None
) -> tuple[datetime | None, datetime | None]:
    """`(含む開始, 含まない終了)` の UTC。開始は `from` の JST 0:00、終了は `to` の翌日の JST 0:00。

    片方だけでもよい（指定の無い側は `None`）。日付が範囲外で変換できないときは `ValueError`。
    """
    try:
        start = jst_midnight_as_utc(date_from) if date_from is not None else None
        end = jst_midnight_as_utc(date_to + timedelta(days=1)) if date_to is not None else None
    except OverflowError as exc:
        raise ValueError("日付が範囲外です") from exc
    return start, end


def validate_period(date_from: date | None, date_to: date | None) -> None:
    """両方あるときだけ組み合わせを検査する（422）。

    - `from` が `to` より後 → `unsupported_value`（`field: "to"`）
    - 期間（両端を含む暦日数）が 366 日を超える → `limit_exceeded`（`field: "to"`・`limit: 366`）
    """
    if date_from is None or date_to is None:
        return
    if date_from > date_to:
        raise AppError(422, "unsupported_value", field="to")
    if (date_to - date_from).days + 1 > MAX_PERIOD_DAYS:
        raise AppError(422, "limit_exceeded", field="to", limit=MAX_PERIOD_DAYS)


# ── 次に更新できる状態（DS-PRC-053b の表）───────────────────────────────────────────


def available_transitions(
    status: OrderStatus, receive_method: ReceiveMethod
) -> list[TransitionOut]:
    """`TRANSITIONS[現在の状態]` と `{preparing, shipped, delivered}` の共通部分（固定の並び）。

    ラベルは `status_label(更新先, 受け取り方法)`。`accepts_tracking_number` は更新先が `shipped` で
    配送のときだけ真。
    """
    allowed = order_state.TRANSITIONS.get(OrderStatus(status), frozenset())
    method = ReceiveMethod(receive_method)
    return [
        TransitionOut(
            status=target.value,
            label=order_status.status_label(target, method),
            accepts_tracking_number=(
                target == OrderStatus.shipped and method == ReceiveMethod.delivery
            ),
        )
        for target in MANAGEABLE_TARGETS
        if target in allowed
    ]


def validate_status_update(
    current: OrderStatus,
    target: OrderStatus,
    receive_method: ReceiveMethod,
    tracking_number: str | None,
) -> None:
    """DS-PRC-053b の手順 3〜5（DB に触れない判定）。

    1. 更新先が `preparing`・`shipped`・`delivered` 以外
       → 422 `unsupported_value`（`field: "status"`）。現在の状態に関係なく同じ（遷移の判定より前）
    2. 追跡番号が付いていて、店舗受け取り、または更新先が `shipped` 以外 → 422 `unsupported_value`
       （`field: "tracking_number"`）
    3. 遷移表に無い → 409 `invalid_transition`（`from`・`to`）
    """
    if target not in MANAGEABLE_TARGETS:
        raise AppError(422, "unsupported_value", field="status")
    if tracking_number is not None and (
        ReceiveMethod(receive_method) != ReceiveMethod.delivery or target != OrderStatus.shipped
    ):
        raise AppError(422, "unsupported_value", field="tracking_number")
    order_state.assert_transition(OrderStatus(current), target)


# ── 検索（DS-API-053）───────────────────────────────────────────────────────────


async def search_orders(
    session: AsyncSession, params: OrderSearchParams, paging: PageParams
) -> Page[AdminOrderListItemOut]:
    validate_period(params.date_from, params.date_to)
    try:
        start, end = period_bounds(params.date_from, params.date_to)
    except ValueError:
        # 入口で弾いているので通常は来ない。来たら形の違反として扱う
        raise AppError(
            400, "validation_error", fields=[{"name": "from", "reason": "format"}]
        ) from None
    rows, total = await repo.search(
        session,
        repo.OrderSearchFilter(
            status=params.status,
            receive_method=params.receive_method,
            created_from=start,
            created_before=end,
            order_number=params.order_number,
            email=params.email,
        ),
        limit=paging.limit,
        offset=paging.offset,
    )
    # 読み取りだけなので、トランザクションを終えて接続を返す
    await session.rollback()
    items = [
        AdminOrderListItemOut(
            order_number=r.order_number,
            ordered_at=r.created_at.replace(tzinfo=UTC),
            status=r.status.value,
            status_label=order_status.status_label(r.status, r.receive_method),
            receive_method=r.receive_method.value,
            total=r.total,
            item_count=r.item_count,
            customer_type="member" if r.is_member else "guest",
            email_masked=mask_email(r.contact_email),
        )
        for r in rows
    ]
    return build_page(items, paging, total)


# ── 詳細（DS-API-053a）──────────────────────────────────────────────────────────


def _tracking_for_admin(order: Order, receive_method: ReceiveMethod) -> str | None:
    """配送のときだけ登録済みの追跡番号を返す（店舗受け取りには無い）。"""
    return order.tracking_number if receive_method == ReceiveMethod.delivery else None


async def get_order_detail(
    session: AsyncSession, staff: CurrentStaff, order_number: str
) -> AdminOrderDetailOut:
    """形が違う・存在しない注文番号は同じ 404。取得を `admin.order.view` に記録する。

    記録（INSERT）に失敗したら例外のまま伝わり（500）、個人情報は返らない。
    """
    if not is_order_number_shape(order_number):
        raise AppError(404, "not_found")
    order = await repo.get_by_number(session, order_number)
    if order is None:
        raise AppError(404, "not_found")
    receive_method = ReceiveMethod(order.receive_method)
    items = await repo.list_items(session, order.id)
    payment = await repo.latest_payment(session, order.id)
    store = None
    if receive_method == ReceiveMethod.store and order.store_id is not None:
        store = await repo.get_store(session, order.store_id)

    await admin_audit.write_admin_audit(
        session,
        staff,
        action=admin_audit.ACTION_ORDER_VIEW,
        target_type="order",
        target_id=order.order_number,
        detail={"receive_method": receive_method.value},
    )
    await session.commit()

    is_delivery = receive_method == ReceiveMethod.delivery
    return AdminOrderDetailOut(
        order_number=order.order_number,
        ordered_at=order.created_at.replace(tzinfo=UTC),
        status=order.status.value,
        status_label=order_status.status_label(order.status, receive_method),
        receive_method=receive_method.value,
        store=(
            AdminOrderStoreOut(name=store.name, prefecture=store.prefecture, address=store.address)
            if store is not None
            else None
        ),
        items=[
            AdminOrderItemOut(
                product_name=i.product_name_at_order,
                color=i.color,
                size=i.size,
                unit_price=i.unit_price_at_order,
                quantity=i.quantity,
            )
            for i in items
        ],
        subtotal=order.subtotal,
        shipping_fee=order.shipping_fee,
        discount=order.discount,
        total=order.total,
        tax_included=calc_tax_included(order.total, order.tax_rate_at_order),
        tax_rate=order.tax_rate_at_order,
        payment=(
            AdminPaymentOut(provider=payment.provider.value, result=payment.result.value)
            if payment is not None
            else None
        ),
        customer=AdminCustomerOut(
            type="member" if order.member_id is not None else "guest",
            name=order.ship_name,
            email_masked=mask_email(order.guest_email),
            phone_masked=mask_phone(order.ship_phone),
            postal_code=order.ship_postal_code if is_delivery else None,
            address=order.ship_address if is_delivery else None,
        ),
        tracking_number=_tracking_for_admin(order, receive_method),
        available_transitions=available_transitions(order.status, receive_method),
    )


# ── 状態の更新（DS-API-053b）─────────────────────────────────────────────────────


async def update_order_status(
    session: AsyncSession,
    staff: CurrentStaff,
    order_number: str,
    target: OrderStatus,
    tracking_number: str | None,
) -> OrderStatusUpdateOut:
    """図は 3.3。1 トランザクションで `FOR UPDATE` → 判定 → UPDATE → 監査ログ → COMMIT。

    404 `not_found`（形が違う番号を含む）／422 `unsupported_value`／409 `invalid_transition`。
    失敗したときは ROLLBACK し、状態も監査ログも残さない。
    """
    if not is_order_number_shape(order_number):
        raise AppError(404, "not_found")
    order = await repo.get_for_update(session, order_number)
    if order is None:
        await session.rollback()
        raise AppError(404, "not_found")
    receive_method = ReceiveMethod(order.receive_method)
    current = OrderStatus(order.status)
    try:
        validate_status_update(current, target, receive_method, tracking_number)
    except AppError:
        await session.rollback()
        raise

    await repo.apply_status(session, order, new_status=target, tracking_number=tracking_number)
    await admin_audit.write_admin_audit(
        session,
        staff,
        action=admin_audit.ACTION_ORDER_STATUS,
        target_type="order",
        target_id=order.order_number,
        detail={
            "from": current.value,
            "to": target.value,
            "receive_method": receive_method.value,
            "tracking_number_set": tracking_number is not None,
        },
    )
    await session.commit()

    return OrderStatusUpdateOut(
        order_number=order.order_number,
        status=target.value,
        status_label=order_status.status_label(target, receive_method),
        tracking_number=_tracking_for_admin(order, receive_method),
        available_transitions=available_transitions(target, receive_method),
    )
