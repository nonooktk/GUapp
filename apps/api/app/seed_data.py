"""seed の定義データ（設計仕様書 5.3・テスト設計書 1.3・6 章）。

DB に依存しない純粋な定数・関数だけを置く（unit テストから参照できるようにする）。
個人情報は含まない（会員・注文の seed は P1 では無し）。

テスト用データの印:
- `P-UNPUB` … 非公開商品（published=False）1 点
- `P-ALL0`  … 全 6 バリエーション在庫 0 の公開商品 1 点
- `V-STOCK0` … 在庫 0 のバリエーション（公開商品の 1 つ）
- `V-STOCK1` … 在庫 1 のバリエーション（公開商品の 1 つ。同時注文の競合用）
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# ── 乱数（在庫）。seed 固定で毎回同じ値になる ──
STOCK_RANDOM_SEED = 20260918
STOCK_MIN = 5
STOCK_MAX = 30

# ── 色コード → 表示名 ──
COLORS: dict[str, str] = {
    "BK": "ブラック",
    "WH": "ホワイト",
    "NV": "ネイビー",
    "GY": "グレー",
    "BE": "ベージュ",
    "KH": "カーキ",
    "BL": "ブルー",
    "PK": "ピンク",
}
SIZES: tuple[str, ...] = ("S", "M", "L")

# ── 送料閾値（4,990）の組み立てに必ず要る価格（AT-08・UT-021-02）──
REQUIRED_PRICES: frozenset[int] = frozenset({1990, 2990, 1490})

# ── system_settings 4 キー（DS-TBL-21）。tax_rate は JSON 文字列（DS-DEC-31）──
SYSTEM_SETTINGS: tuple[tuple[str, object, str], ...] = (
    ("tax_rate", "0.10", "消費税率。JSON 文字列で保持し API 内で Decimal に変換（DS-DEC-31）"),
    ("shipping_fee", 550, "送料（税込・円）"),
    ("free_shipping_threshold", 4990, "送料無料になる小計の下限（税込・円）"),
    ("payment_timeout_minutes", 30, "決済待ち（pending_payment）の期限（分）"),
)


@dataclass(frozen=True)
class CategorySeed:
    slug: str
    name: str
    gender: str  # Gender の値（women / men / kids_teen）
    parent_slug: str | None
    sort_order: int


# 性別 3 区分（親）× 子カテゴリ。slug は英字 kebab-case
_GENDERS: tuple[tuple[str, str], ...] = (
    ("women", "レディース"),
    ("men", "メンズ"),
    ("kids_teen", "キッズ・ティーン"),
)
_CHILDREN: dict[str, tuple[tuple[str, str], ...]] = {
    "women": (
        ("tops", "トップス"),
        ("bottoms", "ボトムス"),
        ("outer", "アウター"),
        ("dresses", "ワンピース"),
        ("inner-goods", "インナー・雑貨"),
    ),
    "men": (
        ("tops", "トップス"),
        ("bottoms", "ボトムス"),
        ("outer", "アウター"),
        ("inner-goods", "インナー・雑貨"),
    ),
    "kids_teen": (
        ("tops", "トップス"),
        ("bottoms", "ボトムス"),
        ("outer", "アウター"),
        ("inner-goods", "インナー・雑貨"),
    ),
}


def _gender_slug(gender: str) -> str:
    return gender.replace("_", "-")


def build_categories() -> list[CategorySeed]:
    """親（性別）→ 子の順に並べたカテゴリ一覧。親が先に来るので順に INSERT できる。"""
    out: list[CategorySeed] = []
    for gi, (gender, gname) in enumerate(_GENDERS):
        parent_slug = _gender_slug(gender)
        out.append(CategorySeed(parent_slug, gname, gender, None, gi))
        for ci, (child, cname) in enumerate(_CHILDREN[gender]):
            out.append(CategorySeed(f"{parent_slug}-{child}", cname, gender, parent_slug, ci))
    return out


CATEGORIES: tuple[CategorySeed, ...] = tuple(build_categories())


@dataclass(frozen=True)
class ProductSeed:
    number: int  # 商品番号（SKU の 3 桁）
    name: str
    price_incl_tax: int
    gender: str
    category: str  # 子カテゴリ（tops / bottoms / ...）
    colors: tuple[str, str]  # 色コード 2 つ
    material: str
    published: bool = True
    all_zero_stock: bool = False  # P-ALL0

    @property
    def category_slug(self) -> str:
        return f"{_gender_slug(self.gender)}-{self.category}"

    @property
    def image_path(self) -> str:
        return f"products/{self.number:03d}/1.jpg"


def make_sku(number: int, color: str, size: str) -> str:
    """SKU 形式 `GU-<商品番号3桁>-<色コード>-<サイズ>`。"""
    return f"GU-{number:03d}-{color}-{size}"


# 商品 30 点（各 色 2 × サイズ 3 = 6 バリエーション）。価格は税込整数円
PRODUCTS: tuple[ProductSeed, ...] = (
    # ── レディース 10 点 ──
    ProductSeed(
        1, "スムースコットンT（レディース）", 1490, "women", "tops", ("WH", "BK"), "綿100%"
    ),
    ProductSeed(
        2, "ソフトリブタンクトップ", 990, "women", "tops", ("BK", "BE"), "綿95%・ポリウレタン5%"
    ),
    ProductSeed(3, "オーバーサイズシャツ", 2990, "women", "tops", ("WH", "BL"), "綿100%"),
    ProductSeed(
        4,
        "ハイウエストストレートジーンズ",
        2990,
        "women",
        "bottoms",
        ("NV", "BK"),
        "綿99%・ポリウレタン1%",
    ),
    ProductSeed(
        5, "イージーワイドパンツ", 1990, "women", "bottoms", ("BK", "BE"), "ポリエステル100%"
    ),
    ProductSeed(
        6, "フレアロングスカート", 2490, "women", "bottoms", ("BK", "KH"), "ポリエステル100%"
    ),
    ProductSeed(
        7,
        "ライトダウンジャケット",
        3990,
        "women",
        "outer",
        ("BK", "GY"),
        "ナイロン100%・中綿ダウン",
    ),
    ProductSeed(
        8, "カットソーワンピース", 2990, "women", "dresses", ("BK", "NV"), "綿60%・ポリエステル40%"
    ),
    ProductSeed(
        9, "シアーロングワンピース", 3990, "women", "dresses", ("BE", "BK"), "ポリエステル100%"
    ),
    ProductSeed(
        10,
        "ブラフィールタンクトップ",
        1490,
        "women",
        "inner-goods",
        ("BK", "BE"),
        "ナイロン85%・ポリウレタン15%",
    ),
    # ── メンズ 10 点 ──
    ProductSeed(11, "ヘビーウェイトT（メンズ）", 1490, "men", "tops", ("WH", "BK"), "綿100%"),
    ProductSeed(12, "ドライポロシャツ", 1990, "men", "tops", ("NV", "WH"), "ポリエステル100%"),
    ProductSeed(13, "オックスフォードシャツ", 2990, "men", "tops", ("WH", "BL"), "綿100%"),
    ProductSeed(
        14, "スウェットプルパーカ", 2990, "men", "tops", ("GY", "BK"), "綿80%・ポリエステル20%"
    ),
    ProductSeed(
        15,
        "スリムテーパードジーンズ",
        2990,
        "men",
        "bottoms",
        ("NV", "BK"),
        "綿98%・ポリウレタン2%",
    ),
    ProductSeed(16, "チノショートパンツ", 1990, "men", "bottoms", ("BE", "KH"), "綿100%"),
    ProductSeed(
        17,
        "ストレッチイージーパンツ",
        2490,
        "men",
        "bottoms",
        ("BK", "GY"),
        "ポリエステル65%・レーヨン35%",
    ),
    ProductSeed(18, "MA-1ブルゾン", 3990, "men", "outer", ("BK", "KH"), "ナイロン100%"),
    ProductSeed(
        19, "ボアフリースジャケット", 2990, "men", "outer", ("BE", "GY"), "ポリエステル100%"
    ),
    ProductSeed(
        20,
        "ドライボクサーブリーフ 2枚組",
        990,
        "men",
        "inner-goods",
        ("BK", "GY"),
        "ポリエステル90%・ポリウレタン10%",
    ),
    # ── キッズ・ティーン 10 点 ──
    ProductSeed(21, "プリントT（キッズ）", 990, "kids_teen", "tops", ("WH", "PK"), "綿100%"),
    ProductSeed(22, "ボーダーロンT（キッズ）", 1490, "kids_teen", "tops", ("NV", "GY"), "綿100%"),
    ProductSeed(
        23,
        "スウェットトレーナー（キッズ）",
        1990,
        "kids_teen",
        "tops",
        ("GY", "PK"),
        "綿80%・ポリエステル20%",
    ),
    ProductSeed(
        24,
        "ストレッチデニム（キッズ）",
        1990,
        "kids_teen",
        "bottoms",
        ("NV", "BK"),
        "綿98%・ポリウレタン2%",
    ),
    ProductSeed(
        25, "イージーショートパンツ（キッズ）", 1490, "kids_teen", "bottoms", ("KH", "NV"), "綿100%"
    ),
    ProductSeed(
        26,
        "ウルトラライトダウン（キッズ）",
        2990,
        "kids_teen",
        "outer",
        ("NV", "PK"),
        "ナイロン100%・中綿ダウン",
    ),
    # V-STOCK1（在庫 1）を含む商品。GU-027-NV-M
    ProductSeed(
        27,
        "ウィンドブレーカー（キッズ）【V-STOCK1あり】",
        2490,
        "kids_teen",
        "outer",
        ("NV", "BL"),
        "ポリエステル100%",
    ),
    # P-ALL0: 全 6 バリエーション在庫 0（公開）
    ProductSeed(
        28,
        "【P-ALL0】撥水パーカ（キッズ）",
        2990,
        "kids_teen",
        "outer",
        ("BK", "KH"),
        "ポリエステル100%",
        all_zero_stock=True,
    ),
    # V-STOCK0（在庫 0）を含む商品。GU-029-BK-M
    ProductSeed(
        29,
        "リブレギンス（キッズ）【V-STOCK0あり】",
        990,
        "kids_teen",
        "inner-goods",
        ("BK", "GY"),
        "綿95%・ポリウレタン5%",
    ),
    # P-UNPUB: 非公開
    ProductSeed(
        30,
        "【P-UNPUB】非公開サンプル商品",
        1990,
        "kids_teen",
        "inner-goods",
        ("WH", "BK"),
        "綿100%",
        published=False,
    ),
)

# ── テスト用データの所在（テスト設計書 6 章）。テストはここを参照する ──
TEST_SKU_STOCK0 = make_sku(29, "BK", "M")  # V-STOCK0: 在庫 0
TEST_SKU_STOCK1 = make_sku(27, "NV", "M")  # V-STOCK1: 在庫 1
TEST_PRODUCT_NUMBER_UNPUB = 30  # P-UNPUB: published=False
TEST_PRODUCT_NUMBER_ALL0 = 28  # P-ALL0: 全バリエーション在庫 0
TEST_PRODUCT_NAME_UNPUB = PRODUCTS[TEST_PRODUCT_NUMBER_UNPUB - 1].name
TEST_PRODUCT_NAME_ALL0 = PRODUCTS[TEST_PRODUCT_NUMBER_ALL0 - 1].name

# 固定在庫（乱数より優先）
FIXED_STOCKS: dict[str, int] = {
    TEST_SKU_STOCK0: 0,
    TEST_SKU_STOCK1: 1,
}


@dataclass(frozen=True)
class VariantSeed:
    product_number: int
    color: str  # 表示名
    size: str
    sku: str
    stock: int


def build_variants(rng: random.Random | None = None) -> list[VariantSeed]:
    """全商品のバリエーション（30 × 6 = 180）。在庫は seed 固定の乱数 5〜30。"""
    rng = rng or random.Random(STOCK_RANDOM_SEED)
    out: list[VariantSeed] = []
    for p in PRODUCTS:
        for color in p.colors:
            for size in SIZES:
                sku = make_sku(p.number, color, size)
                # 乱数は毎回消費して、固定在庫の有無で他の SKU の値が変わらないようにする
                stock = rng.randint(STOCK_MIN, STOCK_MAX)
                if p.all_zero_stock:
                    stock = 0
                stock = FIXED_STOCKS.get(sku, stock)
                out.append(VariantSeed(p.number, COLORS[color], size, sku, stock))
    return out


EXPECTED_CATEGORY_COUNT = len(CATEGORIES)
EXPECTED_PRODUCT_COUNT = len(PRODUCTS)
EXPECTED_VARIANT_COUNT = len(PRODUCTS) * 2 * len(SIZES)
EXPECTED_IMAGE_COUNT = len(PRODUCTS)
EXPECTED_PRODUCT_CATEGORY_COUNT = len(PRODUCTS)
EXPECTED_SYSTEM_SETTING_COUNT = len(SYSTEM_SETTINGS)
