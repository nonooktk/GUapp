"""UT-ADM-08・09・11・19: 管理：商品・在庫の検査と条件（設計仕様書 P2 追補c 4.6・DS-DEC-114〜116）。

担当レーン: C-2。DB には触れない（SQL は MySQL 方言でコンパイルして文字列とパラメータを見る）。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import mysql

from app.core.errors import AppError
from app.repositories.admin_products import build_search_statements
from app.schemas.admin_products import (
    ProductUpdateIn,
    StockUpdateIn,
    normalize_q,
)
from app.services.admin_products import (
    is_restock,
    validate_price_range,
    validate_stock_range,
)


def _shape(stock: Any, expected: Any = 0) -> StockUpdateIn:
    return StockUpdateIn.model_validate({"stock": stock, "expected_stock": expected})


def _range_error(fn, value: int) -> tuple[str, dict[str, Any]] | None:
    try:
        fn(value)
    except AppError as exc:
        assert exc.status == 422
        return exc.code, exc.detail
    return None


# ── UT-ADM-08 在庫の検査 ─────────────────────────────────────────────────────


@pytest.mark.parametrize("stock", [0, 1, 9999])
def test_ut_adm_08_stock_in_range_is_accepted(stock: int) -> None:
    assert _shape(stock).stock == stock
    assert _range_error(validate_stock_range, stock) is None


def test_ut_adm_08_negative_is_unsupported_value() -> None:
    assert _shape(-1).stock == -1  # 形は正しい（業務の範囲で 422 にする）
    assert _range_error(validate_stock_range, -1) == ("unsupported_value", {"field": "stock"})


@pytest.mark.parametrize("stock", [10000, 2147483647])
def test_ut_adm_08_over_9999_is_limit_exceeded(stock: int) -> None:
    assert _shape(stock).stock == stock
    assert _range_error(validate_stock_range, stock) == (
        "limit_exceeded",
        {"field": "stock", "limit": 9999},
    )


@pytest.mark.parametrize("stock", [2147483648, -2147483648, True, False, 5.5, 5.0, "5", None])
def test_ut_adm_08_bad_shape_is_a_validation_error(stock: Any) -> None:
    with pytest.raises(ValidationError):
        _shape(stock)


@pytest.mark.parametrize("expected", [-1, 2147483648, True, 1.5, "0", None])
def test_ut_adm_08_expected_stock_shape(expected: Any) -> None:
    with pytest.raises(ValidationError):
        _shape(5, expected)
    with pytest.raises(ValidationError):
        StockUpdateIn.model_validate({"stock": 5})  # 欠落


# ── UT-ADM-09 価格の検査 ─────────────────────────────────────────────────────


@pytest.mark.parametrize("price", [1, 1990, 1_000_000])
def test_ut_adm_09_price_in_range_is_accepted(price: int) -> None:
    assert _range_error(validate_price_range, price) is None


@pytest.mark.parametrize("price", [0, -1])
def test_ut_adm_09_below_one_is_unsupported_value(price: int) -> None:
    assert _range_error(validate_price_range, price) == (
        "unsupported_value",
        {"field": "price_incl_tax"},
    )


def test_ut_adm_09_over_limit_is_limit_exceeded() -> None:
    assert _range_error(validate_price_range, 1_000_001) == (
        "limit_exceeded",
        {"field": "price_incl_tax", "limit": 1_000_000},
    )


@pytest.mark.parametrize("price", [2147483648, "1990", 1990.5, True, None])
def test_ut_adm_09_bad_shape_is_a_validation_error(price: Any) -> None:
    with pytest.raises(ValidationError):
        ProductUpdateIn.model_validate({"price_incl_tax": price, "expected_price_incl_tax": 1})


def test_ut_adm_09_update_needs_a_change_and_its_expected() -> None:
    def fields(body: dict[str, Any]) -> list[tuple[str, ...]]:
        with pytest.raises(ValidationError) as info:
            ProductUpdateIn.model_validate(body)
        return [tuple(e["loc"]) for e in info.value.errors()]

    assert fields({}) == [()]
    assert fields({"published": False}) == [("expected_published",)]
    assert fields({"price_incl_tax": 100}) == [("expected_price_incl_tax",)]
    ok = ProductUpdateIn.model_validate({"published": False, "expected_published": True})
    assert ok.price_incl_tax is None and ok.expected_price_incl_tax is None
    # 定義外の項目は無視する（mass assignment を許さない）
    extra = ProductUpdateIn.model_validate(
        {"published": False, "expected_published": True, "name": "x", "id": 9}
    )
    assert not hasattr(extra, "name") and not hasattr(extra, "id")


# ── UT-ADM-11 LIKE のエスケープ ───────────────────────────────────────────────


def _compile(q: str, **kw: Any) -> tuple[str, dict[str, Any]]:
    body, _count = build_search_statements(
        q=q,
        visibility=kw.get("visibility", "all"),
        stock=kw.get("stock", "all"),
        limit=20,
        offset=0,
    )
    compiled = body.compile(dialect=mysql.dialect())
    return str(compiled), dict(compiled.params)


@pytest.mark.parametrize(
    ("q", "name_param", "sku_param"),
    [
        ("%", "/%", "/%"),
        ("_", "/_", "/_"),
        ("\\", "\\", "\\"),
        ("a%b", "a/%b", "A/%B"),
        ("日本語", "日本語", "日本語"),
        ("gu-029", "gu-029", "GU-029"),
    ],
)
def test_ut_adm_11_wildcards_are_escaped_and_sku_is_uppercased(
    q: str, name_param: str, sku_param: str
) -> None:
    """`%`・`_` は escape 文字 `/` を前置してパラメータで渡す（`\\` は ESCAPE が `/` なので文字）"""
    statement, params = _compile(q)
    assert "LIKE concat('%%', %s, '%%') ESCAPE '/'" in statement  # 商品名の部分一致
    assert "LIKE concat(%s, '%%') ESCAPE '/'" in statement  # SKU の前方一致
    strings = [v for v in params.values() if isinstance(v, str)]
    assert strings == [name_param, sku_param], strings  # SKU は大文字に直して照合する
    # 値は SQL に連結されず、パラメータで渡される
    assert "LIKE '" not in statement


def test_ut_adm_11_empty_q_adds_no_like_and_filters_compose() -> None:
    statement, _ = _compile("")
    assert "LIKE" not in statement
    statement, _ = _compile("", visibility="public", stock="out")
    assert "products.published IS true" in statement
    assert "coalesce(anon_1.out_of_stock_variants" in statement
    statement, _ = _compile("", visibility="private")
    assert "products.published IS false" in statement


def test_ut_adm_11_q_is_normalized_and_length_checked() -> None:
    assert normalize_q("　ＧＵ-029　") == "GU-029"
    assert normalize_q("") == ""
    assert len(normalize_q("a" * 50)) == 50
    with pytest.raises(AppError) as info:
        normalize_q("a" * 51)
    assert info.value.status == 400 and info.value.code == "validation_error"
    assert info.value.detail == {"fields": [{"name": "q", "reason": "too_long"}]}
    # 全角の 51 文字は NFKC のあとでも 51 文字
    with pytest.raises(AppError):
        normalize_q("ａ" * 51)


# ── UT-ADM-19 再入荷の起動条件 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [(0, 5, True), (0, 1, True), (0, 0, False), (3, 5, False), (5, 0, False), (5, 5, False)],
)
def test_ut_adm_19_only_zero_to_positive_starts_notification(
    before: int, after: int, expected: bool
) -> None:
    assert is_restock(before, after) is expected
