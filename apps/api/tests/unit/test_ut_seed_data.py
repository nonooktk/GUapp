"""UT: seed 定義データの整合（DB 不要。テスト設計書 1.3・6 章）。"""

from __future__ import annotations

import re

from app import seed_data
from app.models import Gender

SKU_PATTERN = re.compile(r"^GU-\d{3}-[A-Z]{2}-(S|M|L)$")


def test_ut_seed_01_sku_unique_and_well_formed() -> None:
    variants = seed_data.build_variants()
    skus = [v.sku for v in variants]
    assert len(skus) == len(set(skus)) == 180
    assert all(SKU_PATTERN.match(s) for s in skus), "SKU は GU-<3桁>-<色2文字>-<S|M|L>"


def test_ut_seed_02_products_30_with_required_prices() -> None:
    assert len(seed_data.PRODUCTS) == 30
    numbers = [p.number for p in seed_data.PRODUCTS]
    assert numbers == list(range(1, 31)), "商品番号は 1〜30 の連番"
    prices = {p.price_incl_tax for p in seed_data.PRODUCTS}
    assert seed_data.REQUIRED_PRICES <= prices
    assert all(
        isinstance(p.price_incl_tax, int) and p.price_incl_tax > 0 for p in seed_data.PRODUCTS
    )
    assert all(len(p.colors) == 2 and len(set(p.colors)) == 2 for p in seed_data.PRODUCTS)
    assert all(c in seed_data.COLORS for p in seed_data.PRODUCTS for c in p.colors)
    assert all(p.image_path == f"products/{p.number:03d}/1.jpg" for p in seed_data.PRODUCTS)


def test_ut_seed_03_test_skus_exist_with_fixed_stock() -> None:
    by_sku = {v.sku: v for v in seed_data.build_variants()}
    assert by_sku[seed_data.TEST_SKU_STOCK0].stock == 0
    assert by_sku[seed_data.TEST_SKU_STOCK1].stock == 1
    products = {p.number: p for p in seed_data.PRODUCTS}
    assert products[seed_data.TEST_PRODUCT_NUMBER_UNPUB].published is False
    all0 = products[seed_data.TEST_PRODUCT_NUMBER_ALL0]
    assert all0.published is True
    assert all(v.stock == 0 for v in by_sku.values() if v.product_number == all0.number)
    # テスト用データ以外の商品は 1 点だけ非公開
    assert sum(1 for p in seed_data.PRODUCTS if not p.published) == 1


def test_ut_seed_04_stock_reproducible_and_in_range() -> None:
    a = seed_data.build_variants()
    b = seed_data.build_variants()
    assert a == b, "在庫は seed 固定で再現可能"
    special = set(seed_data.FIXED_STOCKS) | {
        v.sku for v in a if v.product_number == seed_data.TEST_PRODUCT_NUMBER_ALL0
    }
    for v in a:
        if v.sku not in special:
            assert seed_data.STOCK_MIN <= v.stock <= seed_data.STOCK_MAX


def test_ut_seed_05_categories_three_genders_and_slugs() -> None:
    parents = [c for c in seed_data.CATEGORIES if c.parent_slug is None]
    assert {c.gender for c in parents} == {"women", "men", "kids_teen"}
    slugs = [c.slug for c in seed_data.CATEGORIES]
    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"[a-z]+(-[a-z]+)*", s) for s in slugs), "slug は英字 kebab-case"
    assert all(Gender(c.gender) for c in seed_data.CATEGORIES)
    parent_slugs = {c.slug for c in parents}
    assert all(c.parent_slug in parent_slugs for c in seed_data.CATEGORIES if c.parent_slug)
    # 全商品のカテゴリが実在する
    assert all(p.category_slug in set(slugs) for p in seed_data.PRODUCTS)


def test_ut_seed_06_system_settings_four_keys_tax_rate_string() -> None:
    settings = {k: v for k, v, _ in seed_data.SYSTEM_SETTINGS}
    assert set(settings) == {
        "tax_rate",
        "shipping_fee",
        "free_shipping_threshold",
        "payment_timeout_minutes",
    }
    assert settings["tax_rate"] == "0.10" and isinstance(settings["tax_rate"], str)
    assert settings["shipping_fee"] == 550
    assert settings["free_shipping_threshold"] == 4990
    assert settings["payment_timeout_minutes"] == 30
    assert all(desc for _, _, desc in seed_data.SYSTEM_SETTINGS), "description に用途を書く"
