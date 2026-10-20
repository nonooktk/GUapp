"""UT-ADM-10: 管理：設定の検査（設計仕様書 P2 追補c 4.3・DS-DEC-119）。

担当レーン: C-2。DB には触れない。形の違反は 400（Pydantic）、業務の範囲は 422（サービス）。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.admin_settings import SettingsUpdateIn
from app.services.admin_settings import (
    ALL_KEYS,
    SETTING_SPECS,
    TAX_RATE_MAX_BP,
    validate_setting_range,
)
from app.services.pricing import tax_rate_basis_points


def _shape(key: str, value: Any) -> SettingsUpdateIn:
    expected: Any = "0.10" if key == "tax_rate" else 0
    return SettingsUpdateIn.model_validate({key: value, f"expected_{key}": expected})


def _range_error(key: str, value: Any) -> tuple[str, dict[str, Any]] | None:
    try:
        validate_setting_range(key, value)
    except AppError as exc:
        assert exc.status == 422
        return exc.code, exc.detail
    return None


@pytest.mark.parametrize("value", ["0.00", "0.30", "0.08", "0.10"])
def test_ut_adm_10_tax_rate_in_range(value: str) -> None:
    assert _shape("tax_rate", value).tax_rate == value
    assert _range_error("tax_rate", value) is None


@pytest.mark.parametrize("value", ["0.31", "1.00", "9.99"])
def test_ut_adm_10_tax_rate_over_030_is_limit_exceeded(value: str) -> None:
    assert _shape("tax_rate", value).tax_rate == value  # 形は正しい
    assert _range_error("tax_rate", value) == (
        "limit_exceeded",
        {"field": "tax_rate", "limit": "0.30"},
    )


@pytest.mark.parametrize(
    "value", ["0.1", "10%", "abc", "", "0.100", ".10", "-0.10", "0.10\n", 0.1, 10, None, True]
)
def test_ut_adm_10_tax_rate_bad_shape(value: Any) -> None:
    with pytest.raises(ValidationError):
        _shape("tax_rate", value)


def test_ut_adm_10_tax_rate_range_agrees_with_basis_points() -> None:
    assert tax_rate_basis_points("0.30") == TAX_RATE_MAX_BP == 30
    assert tax_rate_basis_points("0.31") > TAX_RATE_MAX_BP
    assert tax_rate_basis_points("0.00") == 0


@pytest.mark.parametrize(
    ("key", "low", "high"),
    [("shipping_fee", 0, 5000), ("free_shipping_threshold", 0, 100000)],
)
def test_ut_adm_10_integer_keys(key: str, low: int, high: int) -> None:
    for ok in (low, high, (low + high) // 2):
        assert _shape(key, ok) and _range_error(key, ok) is None
    assert _range_error(key, high + 1) == ("limit_exceeded", {"field": key, "limit": high})
    assert _range_error(key, low - 1) == ("unsupported_value", {"field": key})
    for bad in ("550", 5.5, True, None, 2147483648, -2147483648):
        with pytest.raises(ValidationError):
            _shape(key, bad)


def test_ut_adm_10_update_needs_a_key_and_its_expected() -> None:
    def locs(body: dict[str, Any]) -> list[tuple[str, ...]]:
        with pytest.raises(ValidationError) as info:
            SettingsUpdateIn.model_validate(body)
        return [tuple(e["loc"]) for e in info.value.errors()]

    assert locs({}) == [()]
    assert locs({"payment_timeout_minutes": 60, "expected_payment_timeout_minutes": 30}) == [()]
    assert locs({"shipping_fee": 660}) == [("expected_shipping_fee",)]
    assert locs({"tax_rate": "0.08", "shipping_fee": 660}) == [
        ("expected_tax_rate",),
        ("expected_shipping_fee",),
    ]
    body = SettingsUpdateIn.model_validate(
        {
            "shipping_fee": 660,
            "expected_shipping_fee": 550,
            "tax_rate": "0.08",
            "expected_tax_rate": "0.10",
            "payment_timeout_minutes": 1,
            "foo": 1,
        }
    )
    # 表示の順（tax_rate → shipping_fee）。定義外の項目・表示のみのキーは含めない
    assert body.requested() == {"tax_rate": ("0.08", "0.10"), "shipping_fee": (660, 550)}


def test_ut_adm_10_specs_match_the_design() -> None:
    assert ALL_KEYS == (
        "tax_rate",
        "shipping_fee",
        "free_shipping_threshold",
        "payment_timeout_minutes",
    )
    assert [s.editable for s in SETTING_SPECS] == [True, True, True, False]
    assert (SETTING_SPECS[0].min, SETTING_SPECS[0].max) == ("0.00", "0.30")
    assert (SETTING_SPECS[3].min, SETTING_SPECS[3].max) == (None, None)
