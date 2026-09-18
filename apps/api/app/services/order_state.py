"""注文状態の遷移検証（設計仕様書 5.3・UT-014-05）。遷移表は要件定義書 5.5 が正本。

決済待ち→受付済／決済失敗、受付済→出荷準備中／キャンセル済、出荷準備中→出荷済、
出荷済→配達完了／受取期限切れ、配達完了→（返品受付は P2 以降・P1 では遷移なし）、
受取期限切れ・キャンセル済・決済失敗→遷移なし。
"""

from __future__ import annotations

from app.core.errors import AppError
from app.models import OrderStatus

S = OrderStatus

TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    S.pending_payment: frozenset({S.accepted, S.payment_failed}),
    S.accepted: frozenset({S.preparing, S.cancelled}),
    S.preparing: frozenset({S.shipped}),
    S.shipped: frozenset({S.delivered, S.pickup_expired}),
    S.delivered: frozenset(),  # 返品受付は P2 以降
    S.pickup_expired: frozenset(),
    S.cancelled: frozenset(),
    S.payment_failed: frozenset(),
}


def can_transition(src: OrderStatus, dst: OrderStatus) -> bool:
    return dst in TRANSITIONS.get(src, frozenset())


def assert_transition(src: OrderStatus, dst: OrderStatus) -> None:
    """遷移表に無い遷移は 409 `invalid_transition {from, to}`。"""
    if not can_transition(src, dst):
        raise AppError(409, "invalid_transition", **{"from": src.value, "to": dst.value})
