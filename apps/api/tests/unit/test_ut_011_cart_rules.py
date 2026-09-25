"""UT-011-01 カート追加判定（DS-PRC-011）と在庫状態・トークン形式。DB 不要。"""

from __future__ import annotations

import base64

import pytest

from app.core.errors import AppError
from app.services.cart_rules import (
    CART_TOTAL_LIMIT,
    LINE_QUANTITY_LIMIT,
    check_limits,
    new_cart_token,
    stock_status,
)


def test_ut_011_01_line_9_to_10_ok_10_to_11_rejected() -> None:
    assert LINE_QUANTITY_LIMIT == 10
    # 9 → 10 は可
    check_limits(line_quantity=10, cart_total_quantity=10)
    # 10 → 11 は不可（422 limit_exceeded, field=quantity, limit=10）
    with pytest.raises(AppError) as ei:
        check_limits(line_quantity=11, cart_total_quantity=11)
    assert ei.value.status == 422
    assert ei.value.to_body() == {"code": "limit_exceeded", "field": "quantity", "limit": 10}


def test_ut_011_01_cart_total_50_ok_51_rejected() -> None:
    assert CART_TOTAL_LIMIT == 50
    check_limits(line_quantity=10, cart_total_quantity=50)
    with pytest.raises(AppError) as ei:
        check_limits(line_quantity=10, cart_total_quantity=51)
    assert ei.value.status == 422
    assert ei.value.to_body() == {"code": "limit_exceeded", "field": "quantity", "limit": 50}


def test_ut_011_01_line_limit_checked_before_total() -> None:
    """両方超過なら 1 明細の上限（10）を先に返す。"""
    with pytest.raises(AppError) as ei:
        check_limits(line_quantity=11, cart_total_quantity=60)
    assert ei.value.detail["limit"] == 10


@pytest.mark.parametrize(
    ("stock", "quantity", "published", "expected"),
    [
        (5, 5, True, "ok"),
        (6, 5, True, "ok"),
        (4, 5, True, "insufficient"),
        (1, 2, True, "insufficient"),
        (0, 1, True, "out_of_stock"),
        (10, 1, False, "out_of_stock"),
    ],
)
def test_ut_011_stock_status(stock: int, quantity: int, published: bool, expected: str) -> None:
    assert stock_status(stock=stock, quantity=quantity, published=published) == expected


def test_ut_010_cart_token_is_base64url_43_chars() -> None:
    token = new_cart_token()
    assert len(token) == 43
    # base64url の文字集合のみ（パディング無し）
    assert (
        set(token)
        <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"  # pragma: allowlist secret  # noqa: E501
        )
    )
    raw = base64.urlsafe_b64decode(token + "=")
    assert len(raw) == 32
    assert new_cart_token() != token
