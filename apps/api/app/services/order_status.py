"""注文状態の表示名と表示条件（DS-PRC-024a。設計仕様書 P2 追補b 4.8・DS-DEC-78）。

`status_label`・`pickup_code`・`tracking_number` の出し分けは、このモジュールの関数 1 か所に置く。
DS-API-022（確定）・023（照会）・024a（履歴の詳細）・024（履歴の一覧）が同じ関数を使い、
画面ごとに値がずれないようにする。
"""

from __future__ import annotations

from app.models import OrderStatus, ReceiveMethod

S = OrderStatus

# (status, receive_method) → 表示名（設計仕様書 4.8 DS-PRC-024a の表）
_LABELS: dict[ReceiveMethod, dict[OrderStatus, str]] = {
    ReceiveMethod.delivery: {
        S.pending_payment: "決済待ち",
        S.accepted: "受付済",
        S.preparing: "出荷準備中",
        S.shipped: "出荷済（配送中）",
        S.delivered: "配達完了",
        S.pickup_expired: "受取期限切れ",
        S.cancelled: "キャンセル済",
        S.payment_failed: "決済失敗",
    },
    ReceiveMethod.store: {
        S.pending_payment: "決済待ち",
        S.accepted: "受付済",
        S.preparing: "店舗へ準備中",
        S.shipped: "店舗に到着（受け取り可能）",
        S.delivered: "受け渡し済",
        S.pickup_expired: "受取期限切れ",
        S.cancelled: "キャンセル済",
        S.payment_failed: "決済失敗",
    },
}

# 受け取りコードを見せる状態（店舗受け取りのみ）
PICKUP_CODE_VISIBLE_STATUSES: frozenset[OrderStatus] = frozenset(
    {S.accepted, S.preparing, S.shipped}
)
# 追跡番号を見せる状態（配送のみ）
TRACKING_VISIBLE_STATUSES: frozenset[OrderStatus] = frozenset({S.shipped, S.delivered})


def status_label(status: OrderStatus, receive_method: ReceiveMethod) -> str:
    """状態と受け取り方法から、利用者に見せる表示名を返す。"""
    return _LABELS[ReceiveMethod(receive_method)][OrderStatus(status)]


def pickup_code_visible(status: OrderStatus, receive_method: ReceiveMethod) -> bool:
    """`store` かつ `accepted`・`preparing`・`shipped` のときだけ真。"""
    return (
        ReceiveMethod(receive_method) == ReceiveMethod.store
        and OrderStatus(status) in PICKUP_CODE_VISIBLE_STATUSES
    )


def visible_pickup_code(
    status: OrderStatus, receive_method: ReceiveMethod, pickup_code: str | None
) -> str | None:
    """表示条件を満たすときだけ受け取りコードを返す（それ以外は None）。"""
    return pickup_code if pickup_code and pickup_code_visible(status, receive_method) else None


def visible_tracking_number(
    status: OrderStatus, receive_method: ReceiveMethod, tracking_number: str | None
) -> str | None:
    """`delivery` かつ `shipped`・`delivered` かつ登録済みのときだけ追跡番号を返す。"""
    if (
        tracking_number
        and ReceiveMethod(receive_method) == ReceiveMethod.delivery
        and OrderStatus(status) in TRACKING_VISIBLE_STATUSES
    ):
        return tracking_number
    return None
