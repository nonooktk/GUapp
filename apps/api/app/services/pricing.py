"""金額計算（DS-PRC-021・DS-DEC-31・UT-021-01〜05）。

- 金額はすべて `int` の円。引数に `int` 以外（`bool` も含む）が来たら `TypeError`
- `Decimal` は `tax_rate` 文字列の変換にだけ使い、内税は基点整数（10 = 10%）の整数演算
- 送料無料の閾値は小計（送料・値引き前の明細合計）に対して判定する
- 空カートは金額計算の前に 409 `empty_cart`
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.errors import AppError

# 税率の基点（"0.10" → 10）。100 分率で扱う
_TAX_RATE_SCALE = 100


@dataclass(frozen=True)
class PricingSettings:
    """`system_settings` から読んだ金額規則（`app.services.settings.get_public_settings`）。"""

    tax_rate: str  # "0.10" 形式の文字列
    shipping_fee: int
    free_shipping_threshold: int


@dataclass(frozen=True)
class Totals:
    subtotal: int
    shipping_fee: int
    total: int
    tax_included: int


def _require_int(value: object, name: str) -> int:
    # bool は int の派生型なので明示的に拒否する
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} は int で与えてください（{type(value).__name__}）")
    return value


def tax_rate_basis_points(tax_rate: str) -> int:
    """`"0.10"` → 10（100 分率の整数）。数値文字列でなければ `ValueError`。"""
    if not isinstance(tax_rate, str):
        raise TypeError(f"tax_rate は文字列で与えてください（{type(tax_rate).__name__}）")
    try:
        rate = Decimal(tax_rate)
    except InvalidOperation as exc:
        raise ValueError(f"tax_rate を数値として解釈できません: {tax_rate!r}") from exc
    scaled = rate * _TAX_RATE_SCALE
    if scaled != scaled.to_integral_value() or scaled < 0:
        raise ValueError(f"tax_rate は 1% 刻みの 0 以上で与えてください: {tax_rate!r}")
    return int(scaled)


def calc_subtotal(lines: Iterable[tuple[int, int]]) -> int:
    """単価 × 数量の合計。"""
    subtotal = 0
    for unit_price, quantity in lines:
        subtotal += _require_int(unit_price, "unit_price") * _require_int(quantity, "quantity")
    return subtotal


def calc_shipping_fee(subtotal: int, *, shipping_fee: int, free_shipping_threshold: int) -> int:
    """小計が閾値以上なら 0、未満なら設定値（4,989→550、4,990→0）。"""
    _require_int(subtotal, "subtotal")
    _require_int(shipping_fee, "shipping_fee")
    _require_int(free_shipping_threshold, "free_shipping_threshold")
    return 0 if subtotal >= free_shipping_threshold else shipping_fee


def calc_tax_included(total: int, tax_rate: str) -> int:
    """税込合計から内税額を逆算（円未満切り捨て）。`total * 10 // 110`。"""
    _require_int(total, "total")
    bp = tax_rate_basis_points(tax_rate)
    return total * bp // (_TAX_RATE_SCALE + bp)


def calc_totals(lines: list[tuple[int, int]], settings: PricingSettings) -> Totals:
    """明細から小計・送料・合計・内税を出す。明細 0 件は 409 `empty_cart`。"""
    if not lines:
        raise AppError(409, "empty_cart")
    subtotal = calc_subtotal(lines)
    shipping_fee = calc_shipping_fee(
        subtotal,
        shipping_fee=settings.shipping_fee,
        free_shipping_threshold=settings.free_shipping_threshold,
    )
    total = subtotal + shipping_fee
    return Totals(
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=total,
        tax_included=calc_tax_included(total, settings.tax_rate),
    )
