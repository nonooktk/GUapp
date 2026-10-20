"""UT-STATUS-01・02 注文状態の表示名と追跡番号の表示条件（DS-PRC-024a）。"""

from __future__ import annotations

from app.models import OrderStatus, ReceiveMethod
from app.services import order_status

S = OrderStatus
D, ST = ReceiveMethod.delivery, ReceiveMethod.store

# 設計仕様書 4.8 DS-PRC-024a の表を、実装とは独立に書き写したもの
EXPECTED_LABELS = {
    S.pending_payment: ("決済待ち", "決済待ち"),
    S.accepted: ("受付済", "受付済"),
    S.preparing: ("出荷準備中", "店舗へ準備中"),
    S.shipped: ("出荷済（配送中）", "店舗に到着（受け取り可能）"),
    S.delivered: ("配達完了", "受け渡し済"),
    S.pickup_expired: ("受取期限切れ", "受取期限切れ"),
    S.cancelled: ("キャンセル済", "キャンセル済"),
    S.payment_failed: ("決済失敗", "決済失敗"),
}


def test_ut_status_01_labels_match_the_design_table_for_all_sixteen_combinations() -> None:
    # 状態が増えたのに表が追従していなければ、ここで検出できる（網羅の確認）
    assert set(EXPECTED_LABELS) == set(OrderStatus)
    for status, (delivery, store) in EXPECTED_LABELS.items():
        assert order_status.status_label(status, D) == delivery, status
        assert order_status.status_label(status, ST) == store, status


def test_ut_status_01_labels_accept_plain_strings_from_the_database() -> None:
    assert order_status.status_label("shipped", "store") == "店舗に到着（受け取り可能）"  # type: ignore[arg-type]


def test_ut_status_02_tracking_number_only_for_delivery_shipped_or_delivered() -> None:
    shown = {(S.shipped, D), (S.delivered, D)}
    for status in OrderStatus:
        for method in ReceiveMethod:
            got = order_status.visible_tracking_number(status, method, "TRACK-1")
            assert got == ("TRACK-1" if (status, method) in shown else None), (status, method)
            # 登録が無ければ、条件を満たしても None
            assert order_status.visible_tracking_number(status, method, None) is None
            assert order_status.visible_tracking_number(status, method, "") is None
