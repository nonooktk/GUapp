"""UT-021-01〜05 金額計算（DS-PRC-021・DS-DEC-31）。DB 不要。"""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.services.pricing import (
    PricingSettings,
    Totals,
    calc_shipping_fee,
    calc_subtotal,
    calc_tax_included,
    calc_totals,
)

DEFAULT = PricingSettings(tax_rate="0.10", shipping_fee=550, free_shipping_threshold=4990)


def test_ut_021_01_default_rule_1990_x2() -> None:
    """単価 1,990×2 → 小計 3,980・送料 550・合計 4,530・内税 411。"""
    totals = calc_totals([(1990, 2)], DEFAULT)
    assert totals == Totals(subtotal=3980, shipping_fee=550, total=4530, tax_included=411)
    assert all(isinstance(v, int) for v in (totals.subtotal, totals.shipping_fee, totals.total))


@pytest.mark.parametrize(
    ("subtotal", "expected_fee"),
    [(4989, 550), (4990, 0), (4991, 0)],
)
def test_ut_021_02_shipping_threshold(subtotal: int, expected_fee: int) -> None:
    assert calc_shipping_fee(subtotal, shipping_fee=550, free_shipping_threshold=4990) == (
        expected_fee
    )


def test_ut_021_02_threshold_from_seed_prices() -> None:
    """seed の価格（1,990・2,990・1,490）で 4,989 は組めないが 1,990+2,990=4,980<4,990、
    1,490+1,490+1,990=4,970<4,990、2,990+1,990=4,980 → 550。2,990+2,990=5,980 → 0。"""
    assert calc_totals([(1990, 1), (2990, 1)], DEFAULT).shipping_fee == 550
    assert calc_totals([(2990, 2)], DEFAULT).shipping_fee == 0


def test_ut_021_03_empty_cart_raises_409_empty_cart() -> None:
    with pytest.raises(AppError) as ei:
        calc_totals([], DEFAULT)
    assert ei.value.status == 409
    assert ei.value.code == "empty_cart"


def test_ut_021_03_one_yen_tax_included_is_zero() -> None:
    assert calc_tax_included(1, "0.10") == 0
    # 送料込みで 1 円は作れないので関数単体で確認。4,530 と 6,520 も一緒に
    assert calc_tax_included(4530, "0.10") == 411
    assert calc_tax_included(6520, "0.10") == 592


def test_ut_021_04_tax_rate_0_08_changes_only_tax_included() -> None:
    eight = PricingSettings(tax_rate="0.08", shipping_fee=550, free_shipping_threshold=4990)
    t10 = calc_totals([(1990, 2)], DEFAULT)
    t08 = calc_totals([(1990, 2)], eight)
    assert t08.total == t10.total == 4530
    assert t08.tax_included == 4530 * 8 // 108  # 335
    assert t08.tax_included != t10.tax_included


@pytest.mark.parametrize(
    "bad",
    [1990.0, "1990", None, True],
)
def test_ut_021_05_non_int_raises_type_error(bad: object) -> None:
    with pytest.raises(TypeError):
        calc_subtotal([(bad, 2)])  # type: ignore[list-item]
    with pytest.raises(TypeError):
        calc_subtotal([(1990, bad)])  # type: ignore[list-item]
    with pytest.raises(TypeError):
        calc_shipping_fee(bad, shipping_fee=550, free_shipping_threshold=4990)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        calc_tax_included(bad, "0.10")  # type: ignore[arg-type]


def test_ut_021_05_all_results_are_int() -> None:
    totals = calc_totals([(1990, 2), (1490, 1)], DEFAULT)
    for v in (totals.subtotal, totals.shipping_fee, totals.total, totals.tax_included):
        assert type(v) is int


def test_ut_021_tax_rate_must_be_numeric_string() -> None:
    with pytest.raises(TypeError):
        calc_tax_included(4530, 0.10)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        calc_tax_included(4530, "abc")
