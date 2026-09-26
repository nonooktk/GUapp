"""初期データ投入（設計仕様書 5.3・プラン 5 章「seed の冪等性」）。

    uv run python -m app.seed            # products に行があれば何もしない（データ保護側）
    uv run python -m app.seed --reset    # P1 12 表 + contents を TRUNCATE してから投入（確認あり）
    uv run python -m app.seed --reset --yes

接続先は環境変数 `DATABASE_URL`（`app.core.config`）。Alembic のマイグレーションとは分離し、
schema は先に `alembic upgrade head` で作っておく（本モジュールは DDL を発行しない）。
定義データは `app.seed_data`。個人情報は入れない。
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app import seed_data
from app.core.config import get_settings
from app.core.db import build_engine
from app.models import (
    ALL_TABLES,
    P1_TABLES,
    P2A_TABLES,
    Category,
    Content,
    ContentKind,
    Gender,
    Product,
    ProductCategory,
    ProductImage,
    SystemSetting,
    Variant,
)

# TRUNCATE の順（FK の子 → 親）。FOREIGN_KEY_CHECKS=0 で囲うが、順も守っておく
TRUNCATE_ORDER: tuple[str, ...] = (
    "payments",
    "order_items",
    "orders",
    "cart_items",
    "carts",
    "product_images",
    "product_categories",
    "variants",
    "products",
    "categories",
    "system_settings",
    "audit_logs",
)
assert set(TRUNCATE_ORDER) == set(P1_TABLES), "TRUNCATE_ORDER は P1 の 12 表と一致させる"

# P2-a で追加した表（DS-TBL-22 contents）。他表への FK を持たないため順は問わない
CONTENT_TRUNCATE_ORDER: tuple[str, ...] = ("contents",)
assert set(CONTENT_TRUNCATE_ORDER) == set(P2A_TABLES), "P2A_TABLES と一致させる"

COUNT_TABLES: tuple[str, ...] = (
    "categories",
    "products",
    "variants",
    "product_images",
    "product_categories",
    "system_settings",
    "contents",
)


@dataclass(frozen=True)
class SeedResult:
    skipped: bool  # True なら既存データがあり何もしなかった
    counts: dict[str, int]  # 実行後の件数（COUNT_TABLES）


async def count_rows(
    conn: AsyncConnection, tables: tuple[str, ...] = COUNT_TABLES
) -> dict[str, int]:
    """件数を数える。表名は ALL_TABLES（P1 + P2-a）に限定して SQL に埋め込む（外部入力は不可）。"""
    out: dict[str, int] = {}
    for name in tables:
        if name not in ALL_TABLES:
            raise ValueError(f"既知の表ではありません: {name}")
        out[name] = int((await conn.execute(text(f"SELECT COUNT(*) FROM `{name}`"))).scalar_one())
    return out


async def truncate_all_tables(conn: AsyncConnection) -> None:
    """P1 の 12 表 + P2-a の contents（ALL_TABLES 全件）を空にする（--reset とテストの後片付け用）。

    P2-a で contents が増えたため、関数名を中身（全表を対象にする）に合わせて改名した
    （旧名 `truncate_p1_tables`。呼び出し元・テストも本改名に合わせて更新済み）。
    """
    await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    try:
        for name in TRUNCATE_ORDER + CONTENT_TRUNCATE_ORDER:
            await conn.execute(text(f"TRUNCATE TABLE `{name}`"))
    finally:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


async def _insert_all(session: AsyncSession) -> None:
    # categories（親 → 子。slug → id を控える）
    category_ids: dict[str, int] = {}
    for c in seed_data.CATEGORIES:
        row = Category(
            name=c.name,
            slug=c.slug,
            gender=Gender(c.gender),
            sort_order=c.sort_order,
            parent_id=category_ids[c.parent_slug] if c.parent_slug else None,
        )
        session.add(row)
        await session.flush()
        category_ids[c.slug] = row.id

    # products ＋ 画像 ＋ カテゴリ割当
    product_ids: dict[int, int] = {}
    for i, p in enumerate(seed_data.PRODUCTS):
        row = Product(
            name=p.name,
            description=f"{p.name}。{p.material}。",
            material=p.material,
            price_incl_tax=p.price_incl_tax,
            published=p.published,
            sort_order=i,
        )
        session.add(row)
        await session.flush()
        product_ids[p.number] = row.id
        session.add(ProductImage(product_id=row.id, path=p.image_path, sort_order=0))
        session.add(ProductCategory(product_id=row.id, category_id=category_ids[p.category_slug]))

    # variants（在庫は seed 固定の乱数。テスト用 SKU は固定値）
    rng = random.Random(seed_data.STOCK_RANDOM_SEED)
    for v in seed_data.build_variants(rng):
        session.add(
            Variant(
                product_id=product_ids[v.product_number],
                color=v.color,
                size=v.size,
                sku=v.sku,
                stock=v.stock,
            )
        )

    # system_settings
    for key, value, description in seed_data.SYSTEM_SETTINGS:
        session.add(SystemSetting(key=key, value=value, description=description))

    # contents（P2-a・DS-TBL-22）。publish_from/to は seed 実行時刻からの相対値（設計仕様書 5.2）
    now = datetime.now(UTC).replace(tzinfo=None)
    for c in seed_data.CONTENTS:
        publish_to = (
            now + timedelta(days=c.publish_to_offset_days)
            if c.publish_to_offset_days is not None
            else None
        )
        session.add(
            Content(
                kind=ContentKind(c.kind),
                slug=c.slug,
                title=c.title,
                body=c.body,
                publish_from=now + timedelta(days=c.publish_from_offset_days),
                publish_to=publish_to,
                sort_order=c.sort_order,
            )
        )

    await session.flush()


async def seed(engine: AsyncEngine, *, reset: bool = False) -> SeedResult:
    """seed を投入する。

    - `reset=False`（既定）: products に 1 行でもあれば何もせず `skipped=True` を返す
    - `reset=True`: 12 表 + contents を TRUNCATE してから投入
    """
    if reset:
        async with engine.begin() as conn:
            await truncate_all_tables(conn)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        existing = (await session.execute(select(func.count()).select_from(Product))).scalar_one()
        if existing > 0:
            async with engine.connect() as conn:
                return SeedResult(skipped=True, counts=await count_rows(conn))
        await _insert_all(session)
        await session.commit()

    async with engine.connect() as conn:
        return SeedResult(skipped=False, counts=await count_rows(conn))


def _format_counts(counts: dict[str, int]) -> str:
    return " / ".join(f"{k}={v}" for k, v in counts.items())


def _database_name(url: str) -> str:
    return (make_url(url).database or "").split("?")[0]


async def _amain(args: argparse.Namespace) -> int:
    settings = get_settings()
    url = settings.DATABASE_URL
    if not url:
        print("DATABASE_URL が未設定です（環境変数で与えてください）", file=sys.stderr)
        return 2
    db_name = _database_name(url)

    if args.reset and not args.yes:
        answer = input(
            f"DB '{db_name}' の P1 12 表 + contents を TRUNCATE して"
            " seed を投入します。続けますか？ [y/N]: "
        )
        if answer.strip().lower() not in {"y", "yes"}:
            print("中止しました（何も変更していません）")
            return 1

    # DB_POOL_SIZE・DB_MAX_OVERFLOW（DS-DEC-46）を尊重する。共用の講義サーバーに
    # 対しては 5／5 を渡すことで、seed 実行時も接続数を絞れる
    engine = build_engine(
        url, pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW
    )
    try:
        result = await seed(engine, reset=args.reset)
    finally:
        await engine.dispose()

    if result.skipped:
        print(
            f"[seed] DB '{db_name}': 既に products に行があるため何もしませんでした"
            f"（{_format_counts(result.counts)}）。投入し直すには --reset を付けてください"
        )
    else:
        print(f"[seed] DB '{db_name}': 投入完了（{_format_counts(result.counts)}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GUapp P1 初期データ投入")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="P1 の 12 表 + contents を TRUNCATE してから投入する（破壊的）",
    )
    parser.add_argument("--yes", action="store_true", help="--reset の確認プロンプトを省略する")
    args = parser.parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
