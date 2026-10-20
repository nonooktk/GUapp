"""UT-ADM-12〜16: 管理：注文 API の単体テスト（DS-PRC-053・053b・053c、DS-API-053b）。

テスト設計書 P2 追補c 4 章 / 設計仕様書 P2 追補c 4.4・4.6。DB・時計に触れない（純粋関数）。
期待値は設計書の表を、実装とは独立に書き写したもの。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.models import OrderStatus, ReceiveMethod
from app.schemas.admin_orders import OrderStatusUpdateIn
from app.services import admin_orders as svc
from app.services import order_status
from app.services.mask import mask_email, mask_phone

S = OrderStatus
D, ST = ReceiveMethod.delivery, ReceiveMethod.store

# ── UT-ADM-12: JST の暦日 → UTC の範囲 ─────────────────────────────────────────


def _utc(*args: int) -> datetime:
    return datetime(*args)


@pytest.mark.parametrize(
    ("date_from", "date_to", "start", "end"),
    [
        # 2026-10-27（JST 0:00 = 前日 15:00 UTC。終了は翌日の JST 0:00 = 10/27 15:00 UTC）
        (date(2026, 10, 27), date(2026, 10, 27), _utc(2026, 10, 26, 15), _utc(2026, 10, 27, 15)),
        # 月末をまたぐ（10/31 の翌日は 11/1）
        (date(2026, 10, 31), date(2026, 10, 31), _utc(2026, 10, 30, 15), _utc(2026, 10, 31, 15)),
        # 閏日
        (date(2028, 2, 29), date(2028, 2, 29), _utc(2028, 2, 28, 15), _utc(2028, 2, 29, 15)),
        # 年末をまたぐ
        (date(2026, 12, 31), date(2026, 12, 31), _utc(2026, 12, 30, 15), _utc(2026, 12, 31, 15)),
        # 複数日
        (date(2026, 10, 27), date(2026, 10, 28), _utc(2026, 10, 26, 15), _utc(2026, 10, 28, 15)),
        # from だけ・to だけ
        (date(2026, 10, 27), None, _utc(2026, 10, 26, 15), None),
        (None, date(2026, 10, 27), None, _utc(2026, 10, 27, 15)),
        (None, None, None, None),
    ],
)
def test_ut_adm_12_period_bounds_convert_jst_calendar_days_to_utc(
    date_from: date | None, date_to: date | None, start: datetime | None, end: datetime | None
) -> None:
    assert svc.period_bounds(date_from, date_to) == (start, end)


def test_ut_adm_12_the_jst_boundary_falls_between_the_two_seconds() -> None:
    """JST 23:59:59（UTC 14:59:59）は 10/27 に入り、JST 0:00（UTC 15:00:00）は 10/28 に入る。"""
    start27, end27 = svc.period_bounds(date(2026, 10, 27), date(2026, 10, 27))
    start28, end28 = svc.period_bounds(date(2026, 10, 28), date(2026, 10, 28))
    last_of_27 = _utc(2026, 10, 27, 14, 59, 59)
    first_of_28 = _utc(2026, 10, 27, 15, 0, 0)
    assert start27 is not None and end27 is not None and start28 is not None and end28 is not None
    assert start27 <= last_of_27 < end27
    assert not (start27 <= first_of_28 < end27)  # 終了は含まない（排他）
    assert start28 <= first_of_28 < end28
    assert end27 == start28  # 隣り合う日の間に隙間も重なりもない


@pytest.mark.parametrize(
    "text",
    [
        "2026-13-01",  # 月が範囲外
        "2026-02-30",  # 実在しない日
        "2027-02-29",  # 閏年ではない
        "2026/10/01",  # 区切りが違う
        "20261001",
        "2026-1-1",
        "２０２６-１０-０１",  # 全角数字
        "2026-10-01T00:00:00",
        "2026-10-01\n",
        " 2026-10-01",
        "",
        "0001-01-01",  # UTC に直せない
        "9999-12-31",  # 翌日が作れない
    ],
)
def test_ut_adm_12_non_existent_or_malformed_dates_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        svc.parse_ymd(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-27", date(2026, 10, 27)),
        ("2028-02-29", date(2028, 2, 29)),
        ("2026-12-31", date(2026, 12, 31)),
    ],
)
def test_ut_adm_12_valid_dates_parse(text: str, expected: date) -> None:
    assert svc.parse_ymd(text) == expected


def test_ut_adm_12_period_validation_rejects_reversed_and_over_366_days() -> None:
    svc.validate_period(None, None)
    svc.validate_period(date(2026, 1, 1), None)
    svc.validate_period(None, date(2026, 1, 1))
    svc.validate_period(date(2026, 10, 1), date(2026, 10, 1))  # 1 日
    # 366 日（両端を含む。閏年の丸 1 年）は通る
    svc.validate_period(date(2028, 1, 1), date(2028, 12, 31))
    with pytest.raises(AppError) as over:
        svc.validate_period(date(2028, 1, 1), date(2029, 1, 1))  # 367 日
    assert (over.value.status, over.value.code) == (422, "limit_exceeded")
    assert over.value.detail == {"field": "to", "limit": 366}
    with pytest.raises(AppError) as reversed_:
        svc.validate_period(date(2026, 10, 2), date(2026, 10, 1))
    assert (reversed_.value.status, reversed_.value.code) == (422, "unsupported_value")
    assert reversed_.value.detail == {"field": "to"}


# ── UT-ADM-13: マスク ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("phone", "masked"),
    [
        ("00000005678", "*******5678"),  # 11 桁
        ("09012345678", "*******5678"),
        ("0312345678", "******5678"),  # 10 桁
        ("12345", "*2345"),  # 5 桁
        ("1234", "****"),  # 4 桁
        ("123", "***"),  # 3 桁
        ("", ""),
    ],
)
def test_ut_adm_13_mask_phone_keeps_only_the_last_four_digits(phone: str, masked: str) -> None:
    assert mask_phone(phone) == masked
    assert len(mask_phone(phone)) == len(phone)


@pytest.mark.parametrize(
    ("email", "masked"),
    [
        ("test@example.com", "t***@example.com"),
        ("taro@example.com", "t***@example.com"),
        ("no-at-sign", "***"),
        ("@example.com", "***"),  # 局所部が空
        ("test@", "***"),  # ドメインが空
        ("", "***"),
    ],
)
def test_ut_adm_13_mask_email_reuses_the_mail_adapter_rule(email: str, masked: str) -> None:
    assert mask_email(email) == masked


# ── UT-ADM-14: 更新先の判定（8 × 8 = 64 通り）──────────────────────────────────


def _outcome(current: OrderStatus, target: OrderStatus, method: ReceiveMethod) -> str:
    try:
        svc.validate_status_update(current, target, method, None)
    except AppError as exc:
        return f"{exc.status} {exc.code}"
    return "ok"


@pytest.mark.parametrize("method", [D, ST])
def test_ut_adm_14_all_64_combinations_of_current_and_target(method: ReceiveMethod) -> None:
    allowed_pairs = {
        (S.accepted, S.preparing),
        (S.preparing, S.shipped),
        (S.shipped, S.delivered),
    }
    manageable = {S.preparing, S.shipped, S.delivered}
    results = {(c, t): _outcome(c, t, method) for c in OrderStatus for t in OrderStatus}
    assert len(results) == 64
    for (current, target), outcome in results.items():
        if target not in manageable:
            expected = "422 unsupported_value"  # 現在の状態に関係なく（遷移の判定より前）
        elif (current, target) in allowed_pairs:
            expected = "ok"
        else:
            expected = "409 invalid_transition"
        assert outcome == expected, (current, target)
    counts = {k: list(results.values()).count(k) for k in set(results.values())}
    assert counts == {"422 unsupported_value": 40, "ok": 3, "409 invalid_transition": 21}


def test_ut_adm_14_unsupported_target_reports_the_status_field() -> None:
    with pytest.raises(AppError) as exc:
        svc.validate_status_update(S.accepted, S.cancelled, D, None)
    assert exc.value.detail == {"field": "status"}


def test_ut_adm_14_invalid_transition_reports_from_and_to() -> None:
    with pytest.raises(AppError) as exc:
        svc.validate_status_update(S.accepted, S.shipped, D, None)
    assert (exc.value.status, exc.value.code) == (409, "invalid_transition")
    assert exc.value.detail == {"from": "accepted", "to": "shipped"}


# ── UT-ADM-15: 次の操作（available_transitions）────────────────────────────────

# 設計仕様書 4.6 の表（遷移表は変えない）。実装とは独立に書き写したもの
EXPECTED_NEXT = {
    S.accepted: S.preparing,
    S.preparing: S.shipped,
    S.shipped: S.delivered,
}


def test_ut_adm_15_available_transitions_for_all_16_combinations() -> None:
    assert len(list(OrderStatus)) * len(list(ReceiveMethod)) == 16
    for status in OrderStatus:
        for method in ReceiveMethod:
            got = svc.available_transitions(status, method)
            if status not in EXPECTED_NEXT:
                assert got == [], (status, method)
                continue
            target = EXPECTED_NEXT[status]
            assert [t.status for t in got] == [target.value], (status, method)
            assert got[0].label == order_status.status_label(target, method)
            assert got[0].accepts_tracking_number is (target == S.shipped and method == D)


def test_ut_adm_15_labels_differ_between_delivery_and_store() -> None:
    assert svc.available_transitions(S.accepted, D)[0].label == "出荷準備中"
    assert svc.available_transitions(S.accepted, ST)[0].label == "店舗へ準備中"
    assert svc.available_transitions(S.preparing, D)[0].label == "出荷済（配送中）"
    assert svc.available_transitions(S.preparing, ST)[0].label == "店舗に到着（受け取り可能）"
    assert svc.available_transitions(S.shipped, D)[0].label == "配達完了"
    assert svc.available_transitions(S.shipped, ST)[0].label == "受け渡し済"


def test_ut_adm_15_accepts_plain_strings_from_the_database() -> None:
    assert svc.available_transitions("accepted", "delivery")[0].status == "preparing"  # type: ignore[arg-type]


# ── UT-ADM-16: 追跡番号の検査 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("A", True),  # 1 文字
        ("A" * 50, True),
        ("A" * 51, False),
        ("ABC-123-xyz", True),  # ハイフン入り
        ("ＡＢＣ１２３", False),  # 全角
        ("AB 12", False),  # 空白入り
        (" AB12", False),
        ("AB12\n", False),  # 末尾の改行
        ("AB_12", False),
        ("", False),  # 空文字
    ],
)
def test_ut_adm_16_tracking_number_shape(value: str, valid: bool) -> None:
    if valid:
        assert OrderStatusUpdateIn(status=S.shipped, tracking_number=value).tracking_number == value
    else:
        with pytest.raises(ValidationError):
            OrderStatusUpdateIn(status=S.shipped, tracking_number=value)


def test_ut_adm_16_tracking_number_is_optional_and_null_means_absent() -> None:
    assert OrderStatusUpdateIn(status=S.shipped).tracking_number is None
    assert OrderStatusUpdateIn(status=S.shipped, tracking_number=None).tracking_number is None


@pytest.mark.parametrize("method", [D, ST])
@pytest.mark.parametrize("target", [S.preparing, S.shipped, S.delivered])
def test_ut_adm_16_tracking_number_is_allowed_only_for_delivery_shipped(
    method: ReceiveMethod, target: OrderStatus
) -> None:
    current = {S.preparing: S.accepted, S.shipped: S.preparing, S.delivered: S.shipped}[target]
    if method == D and target == S.shipped:
        svc.validate_status_update(current, target, method, "TRACK-1")  # 通る
        return
    with pytest.raises(AppError) as exc:
        svc.validate_status_update(current, target, method, "TRACK-1")
    assert (exc.value.status, exc.value.code) == (422, "unsupported_value")
    assert exc.value.detail == {"field": "tracking_number"}


def test_ut_adm_16_tracking_check_comes_before_the_transition_check() -> None:
    """店舗の注文や出荷以外に付けたときは、遷移として正しくなくても 422（4.6 手順 4 → 5）。"""
    with pytest.raises(AppError) as exc:
        svc.validate_status_update(S.delivered, S.preparing, ST, "TRACK-1")
    assert (exc.value.status, exc.value.code) == (422, "unsupported_value")
    assert exc.value.detail == {"field": "tracking_number"}


@pytest.mark.parametrize("bad", ["foo", "", "SHIPPED", None, 5, True, ["shipped"]])
def test_ut_adm_16_status_must_be_one_of_the_eight_values(bad: object) -> None:
    with pytest.raises(ValidationError):
        OrderStatusUpdateIn.model_validate({"status": bad})


def test_ut_adm_16_unknown_body_fields_are_ignored() -> None:
    body = OrderStatusUpdateIn.model_validate(
        {"status": "preparing", "receive_method": "store", "total": 1, "member_id": 9}
    )
    assert body.model_dump() == {"status": S.preparing, "tracking_number": None}
