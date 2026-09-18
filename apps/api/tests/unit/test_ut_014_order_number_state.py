"""UT-014-01／02 注文番号生成、UT-014-05 状態遷移検証（DB 不要）。"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import AppError
from app.models import OrderStatus
from app.services.order_number import (
    ORDER_NUMBER_ALPHABET,
    ORDER_NUMBER_RE,
    generate_order_number,
)
from app.services.order_state import TRANSITIONS, assert_transition

JST = ZoneInfo("Asia/Tokyo")


def test_ut_014_01_10000_numbers_match_format_and_are_unique() -> None:
    pattern = re.compile(r"^GU-\d{6}-[A-HJ-NP-Z2-9]{8}$")
    today_jst = datetime.now(JST).strftime("%y%m%d")
    numbers = [generate_order_number() for _ in range(10_000)]
    for n in numbers:
        assert pattern.match(n), n
        assert ORDER_NUMBER_RE.match(n), n
        assert n[3:9] == today_jst
    assert len(set(numbers)) == 10_000
    assert len(numbers[0]) == 18  # String(20) に収まる


def test_ut_014_01_date_is_jst_not_utc() -> None:
    # UTC 2026-09-17 23:30 は JST では 2026-09-18 08:30
    now_utc = datetime(2026, 9, 17, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert generate_order_number(now=now_utc)[3:9] == "260918"


def test_ut_014_02_no_confusable_characters() -> None:
    assert len(ORDER_NUMBER_ALPHABET) == 32
    for ch in "IO01":
        assert ch not in ORDER_NUMBER_ALPHABET
    seen = "".join(generate_order_number()[10:] for _ in range(10_000))
    assert not set(seen) & set("IO01")
    # 32 文字すべてが出る（偏りの粗い確認）
    assert set(seen) == set(ORDER_NUMBER_ALPHABET)


# ── UT-014-05 状態遷移（要件定義書 5.5） ────────────────────────────────────


def test_ut_014_05_pending_to_shipped_is_409_invalid_transition() -> None:
    with pytest.raises(AppError) as ei:
        assert_transition(OrderStatus.pending_payment, OrderStatus.shipped)
    assert ei.value.status == 409
    assert ei.value.to_body() == {
        "code": "invalid_transition",
        "from": "pending_payment",
        "to": "shipped",
    }


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        ("pending_payment", "accepted"),
        ("pending_payment", "payment_failed"),
        ("accepted", "preparing"),
        ("accepted", "cancelled"),
        ("preparing", "shipped"),
        ("shipped", "delivered"),
        ("shipped", "pickup_expired"),
    ],
)
def test_ut_014_05_allowed_transitions_pass(src: str, dst: str) -> None:
    assert_transition(OrderStatus(src), OrderStatus(dst))


@pytest.mark.parametrize("terminal", ["pickup_expired", "cancelled", "payment_failed", "delivered"])
def test_ut_014_05_terminal_states_have_no_transition(terminal: str) -> None:
    assert TRANSITIONS[OrderStatus(terminal)] == frozenset()
    for dst in OrderStatus:
        with pytest.raises(AppError):
            assert_transition(OrderStatus(terminal), dst)


def test_ut_014_05_table_covers_all_8_states() -> None:
    assert set(TRANSITIONS) == set(OrderStatus)
