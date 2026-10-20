"""管理：注文の読み書き（DS-TBL-14〜16。設計仕様書 P2 追補c 4.6 DS-PRC-053・053b・5.6）。

担当レーン: C-3。

- 一覧は氏名・電話・住所の列を**読み出さない**（必要な列だけを選ぶ。DS-PRC-053 手順 6）。
  本体 1 回・件数の `COUNT` 1 回・ページ内の注文 ID に対する `order_items` の集計 1 回の合計 3 回で
  返す（N+1 にしない。ST-NFR-11）
- 状態の更新は `orders` の 1 行を `SELECT … FOR UPDATE` で読んでから行う（5.6）
- 期間の端は呼び出し側が UTC の naive datetime（`created_at` と同じ表現）にして渡す
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderItem, OrderStatus, Payment, ReceiveMethod, Store


@dataclass(frozen=True, slots=True)
class OrderSearchFilter:
    """一覧の絞り込み。すべて AND。`None` は条件なし。

    `created_from` は含む、`created_before` は含まない（排他）。どちらも UTC の naive datetime。
    """

    status: OrderStatus | None = None
    receive_method: ReceiveMethod | None = None
    created_from: datetime | None = None
    created_before: datetime | None = None
    order_number: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class OrderListRow:
    """一覧の 1 行（個人情報の列は含めない。メールはマスク前の値なのでサービス層でマスクする）。"""

    order_number: str
    created_at: datetime
    status: OrderStatus
    receive_method: ReceiveMethod
    total: int
    is_member: bool
    contact_email: str
    item_count: int


def _conditions(f: OrderSearchFilter) -> list:
    conds = []
    if f.status is not None:
        conds.append(Order.status == f.status)
    if f.receive_method is not None:
        conds.append(Order.receive_method == f.receive_method)
    if f.created_from is not None:
        conds.append(Order.created_at >= f.created_from)
    if f.created_before is not None:
        conds.append(Order.created_at < f.created_before)
    if f.order_number is not None:
        conds.append(Order.order_number == f.order_number)
    if f.email is not None:
        # 連絡先メール（会員の注文でも入っている）。完全一致だけ（部分一致は作らない）
        # 列の照合順序（utf8mb4_0900_ai_ci）は大文字小文字とアクセント記号を区別しない。
        # 1 つ目で索引を使い、2 つ目でアクセント記号違い（tàro と taro）を別のアドレスとして扱う
        conds.append(Order.guest_email == f.email)
        conds.append(Order.guest_email.collate("utf8mb4_0900_as_ci") == f.email)
    return conds


async def search(
    session: AsyncSession, f: OrderSearchFilter, *, limit: int, offset: int
) -> tuple[list[OrderListRow], int]:
    """新しい順（同時刻は id の降順）の 1 ページと総件数。SQL は 3 回以内。"""
    conds = _conditions(f)
    total = int(
        (await session.execute(select(func.count()).select_from(Order).where(*conds))).scalar_one()
    )
    if total == 0 or offset >= total:
        return [], total
    rows = (
        await session.execute(
            select(
                Order.id,
                Order.order_number,
                Order.created_at,
                Order.status,
                Order.receive_method,
                Order.total,
                Order.member_id,
                Order.guest_email,
            )
            .where(*conds)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    counts = await _item_counts(session, [r.id for r in rows])
    return (
        [
            OrderListRow(
                order_number=r.order_number,
                created_at=r.created_at,
                status=OrderStatus(r.status),
                receive_method=ReceiveMethod(r.receive_method),
                total=r.total,
                is_member=r.member_id is not None,
                contact_email=r.guest_email,
                item_count=counts.get(r.id, 0),
            )
            for r in rows
        ],
        total,
    )


async def _item_counts(session: AsyncSession, order_ids: list[int]) -> dict[int, int]:
    """注文 ID → 数量の合計。ページ内の注文をまとめて 1 回で集計する。"""
    if not order_ids:
        return {}
    rows = await session.execute(
        select(OrderItem.order_id, func.sum(OrderItem.quantity))
        .where(OrderItem.order_id.in_(order_ids))
        .group_by(OrderItem.order_id)
    )
    return {order_id: int(qty) for order_id, qty in rows.all()}


async def get_by_number(session: AsyncSession, order_number: str) -> Order | None:
    """注文番号で 1 件（詳細の読み取り。ロックしない）。"""
    return (
        await session.execute(
            select(Order)
            .where(Order.order_number == order_number)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def get_for_update(session: AsyncSession, order_number: str) -> Order | None:
    """注文の 1 行を `SELECT … FOR UPDATE` で排他して読む（状態の更新。5.6）。無ければ None。"""
    return (
        await session.execute(
            select(Order)
            .where(Order.order_number == order_number)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def list_items(session: AsyncSession, order_id: int) -> list[OrderItem]:
    """明細（id 順。注文時点の値）。"""
    rows = await session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
    )
    return list(rows.scalars().all())


async def latest_payment(session: AsyncSession, order_id: int) -> Payment | None:
    """最新の決済（id が最大の行）。無ければ None。"""
    return (
        await session.execute(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.id.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def get_store(session: AsyncSession, store_id: int) -> Store | None:
    """受け取り店舗（受け取り停止中の店舗も引く）。"""
    return await session.get(Store, store_id)


async def apply_status(
    session: AsyncSession,
    order: Order,
    *,
    new_status: OrderStatus,
    tracking_number: str | None,
) -> None:
    """ロック済みの注文の状態（と、あれば追跡番号）を更新して `flush` する（COMMIT は呼び出し側）。

    追跡番号は `None` のときは触らない。`updated_at` は DB が更新する。
    """
    order.status = new_status
    if tracking_number is not None:
        order.tracking_number = tracking_number
    await session.flush()
