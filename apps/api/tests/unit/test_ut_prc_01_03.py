"""UT-PRC-01〜03 金額計算の送料の差分（DS-PRC-021a）。"""

from __future__ import annotations

import pytest

from app.services.pricing import PricingSettings, calc_totals

SETTINGS = PricingSettings(tax_rate="0.10", shipping_fee=550, free_shipping_threshold=4990)


@pytest.mark.parametrize("subtotal", [1490, 4980, 4990])
def test_ut_prc_01_store_pickup_has_no_shipping_fee(subtotal: int) -> None:
    totals = calc_totals([(subtotal, 1)], SETTINGS, receive_method="store")
    assert totals.shipping_fee == 0
    assert totals.subtotal == subtotal and totals.total == subtotal
    assert totals.tax_included == subtotal * 10 // 110


@pytest.mark.parametrize(("subtotal", "fee"), [(4989, 550), (4990, 0), (4991, 0)])
def test_ut_prc_02_delivery_keeps_the_existing_threshold(subtotal: int, fee: int) -> None:
    assert calc_totals([(subtotal, 1)], SETTINGS).shipping_fee == fee
    assert calc_totals([(subtotal, 1)], SETTINGS, receive_method="delivery").shipping_fee == fee


@pytest.mark.parametrize("bad", ["pickup", "", None, 1])
def test_ut_prc_03_unknown_receive_method_is_a_programming_error(bad: object) -> None:
    with pytest.raises(ValueError):
        calc_totals([(1990, 1)], SETTINGS, receive_method=bad)  # type: ignore[arg-type]
