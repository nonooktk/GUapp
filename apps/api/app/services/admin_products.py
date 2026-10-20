"""管理：商品・在庫の処理（DS-PRC-051・051b・051c。設計仕様書 P2 追補c 4.2・4.6・5.4）。

担当レーン: C-2。更新は 1 トランザクションで、対象の行を `SELECT … FOR UPDATE` で読み、
業務の範囲 → 更新前の値の照合（`ensure_expected`）→ UPDATE → 監査ログの INSERT → COMMIT の順。
失敗は ROLLBACK してから例外を投げる（行ロックを残さない）。判定の順序は
認証 → 400 → 404 → 422 → 409（DS-DEC-124）。

在庫が 0 から 1 以上になったときは、COMMIT のあとにルーターが `BackgroundTasks` で
`notify_in_background` を呼ぶ（DS-PRC-051c 手順 10・11）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.mail import MailAdapter
from app.core.admin_session import CurrentStaff
from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.repositories import admin_products as repo
from app.schemas.admin_common import Page, PageParams, build_page
from app.schemas.admin_products import (
    AdminProductDetailOut,
    AdminProductListItemOut,
    AdminVariantOut,
    ProductListParams,
    ProductUpdateIn,
    ProductUpdateOut,
    StockUpdateIn,
    StockUpdateOut,
)
from app.services.admin_audit import ACTION_PRODUCT_UPDATE, ACTION_STOCK_SET, write_admin_audit
from app.services.optimistic import ensure_expected
from app.services.restock import notify_restock

logger = logging.getLogger("app.services.admin_products")

# 業務の範囲（DS-DEC-114・116。意見として置いた値）
STOCK_MIN = 0
STOCK_MAX = 9999
PRICE_MIN = 1
PRICE_MAX = 1_000_000


# ── 業務の範囲の検査（形の違反＝400 は Pydantic 済み）──────────────────────────────


def validate_stock_range(stock: int) -> None:
    """0〜9999。0 未満は 422 `unsupported_value`、9999 超は 422 `limit_exceeded`（`limit`）。"""
    if stock < STOCK_MIN:
        raise AppError(422, "unsupported_value", field="stock")
    if stock > STOCK_MAX:
        raise AppError(422, "limit_exceeded", field="stock", limit=STOCK_MAX)


def validate_price_range(price: int) -> None:
    """1〜1,000,000。1 未満は 422 `unsupported_value`、超過は 422 `limit_exceeded`。"""
    if price < PRICE_MIN:
        raise AppError(422, "unsupported_value", field="price_incl_tax")
    if price > PRICE_MAX:
        raise AppError(422, "limit_exceeded", field="price_incl_tax", limit=PRICE_MAX)


def is_restock(before: int, after: int) -> bool:
    """再入荷（在庫が 0 から 1 以上になった更新）か。DS-DEC-115。"""
    return before == 0 and after >= 1


# ── 一覧・詳細（読み取り）─────────────────────────────────────────────────────


async def list_products(
    session: AsyncSession, params: ProductListParams, paging: PageParams
) -> Page[AdminProductListItemOut]:
    """DS-PRC-051。本体 1 回と件数 1 回。読み取りだけなので最後に終える。"""
    try:
        rows, total = await repo.search_products(
            session,
            q=params.q,
            visibility=params.visibility,
            stock=params.stock,
            limit=paging.limit,
            offset=paging.offset,
        )
    finally:
        await session.rollback()
    items = [
        AdminProductListItemOut(
            product_id=r.product_id,
            name=r.name,
            price_incl_tax=r.price_incl_tax,
            published=r.published,
            variant_count=r.variant_count,
            total_stock=r.total_stock,
            out_of_stock_variants=r.out_of_stock_variants,
        )
        for r in rows
    ]
    return build_page(items, paging, total)


async def get_product(session: AsyncSession, product_id: int) -> AdminProductDetailOut:
    """DS-API-051a。非公開でも返す。無ければ 404 `not_found`。"""
    try:
        product = await repo.get_product_detail(session, product_id)
        if product is None:
            raise AppError(404, "not_found")
        variants = await repo.list_variants(session, product_id)
    finally:
        await session.rollback()
    return AdminProductDetailOut(
        product_id=product.product_id,
        name=product.name,
        price_incl_tax=product.price_incl_tax,
        published=product.published,
        updated_at=product.updated_at.replace(tzinfo=UTC),
        variants=[
            AdminVariantOut(
                variant_id=v.variant_id,
                sku=v.sku,
                color=v.color,
                size=v.size,
                stock=v.stock,
                restock_waiting=v.restock_waiting,
            )
            for v in variants
        ],
    )


# ── 商品の更新（DS-PRC-051b）──────────────────────────────────────────────────


async def update_product(
    session: AsyncSession, staff: CurrentStaff, product_id: int, body: ProductUpdateIn
) -> ProductUpdateOut:
    try:
        # 2. 行を排他で読む。無ければ 404
        row = await repo.get_product_for_update(session, product_id)
        if row is None:
            raise AppError(404, "not_found")
        # 3. 業務の範囲（外れたら 422）
        if body.price_incl_tax is not None:
            validate_price_range(body.price_incl_tax)
        # 4. 変更する項目ごとに照合（published → price_incl_tax の順）
        if body.published is not None:
            ensure_expected("published", body.expected_published, row.published)
        if body.price_incl_tax is not None:
            ensure_expected("price_incl_tax", body.expected_price_incl_tax, row.price_incl_tax)
        # 5. 現在の値と同じ項目は更新から外す。残りが無ければ changed: false
        new_published = body.published if body.published != row.published else None
        new_price = body.price_incl_tax if body.price_incl_tax != row.price_incl_tax else None
        if new_published is None and new_price is None:
            await session.rollback()
            return ProductUpdateOut(
                product_id=row.product_id,
                published=row.published,
                price_incl_tax=row.price_incl_tax,
                changed=False,
                updated_at=row.updated_at.replace(tzinfo=UTC),
            )
        # 6. UPDATE（変更する項目だけ。updated_at は DB が更新）
        updated_at = await repo.update_product(
            session, product_id, published=new_published, price_incl_tax=new_price
        )
        # 7. 監査ログ（変更した項目の前後の値）
        detail: dict[str, dict[str, object]] = {}
        if new_published is not None:
            detail["published"] = {"before": row.published, "after": new_published}
        if new_price is not None:
            detail["price_incl_tax"] = {"before": row.price_incl_tax, "after": new_price}
        await write_admin_audit(
            session,
            staff,
            action=ACTION_PRODUCT_UPDATE,
            target_type="product",
            target_id=str(product_id),
            detail=detail,
        )
        # 8. COMMIT
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return ProductUpdateOut(
        product_id=row.product_id,
        published=new_published if new_published is not None else row.published,
        price_incl_tax=new_price if new_price is not None else row.price_incl_tax,
        changed=True,
        updated_at=updated_at.replace(tzinfo=UTC),
    )


# ── 在庫の更新（DS-PRC-051c）──────────────────────────────────────────────────


@dataclass(frozen=True)
class StockUpdateResult:
    """応答と、COMMIT のあとに再入荷通知を起動するか。"""

    out: StockUpdateOut
    restocked: bool


async def set_stock(
    session: AsyncSession, staff: CurrentStaff, variant_id: int, body: StockUpdateIn
) -> StockUpdateResult:
    try:
        # 2. 行を排他で読む。無ければ 404
        row = await repo.get_variant_for_update(session, variant_id)
        if row is None:
            raise AppError(404, "not_found")
        # 3. 業務の範囲（0〜9999。外れたら 422）
        validate_stock_range(body.stock)
        # 4. 更新前の値の照合（不一致は 409。current は現在の在庫）
        ensure_expected("stock", body.expected_stock, row.stock)
        # 5. 現在と同じなら更新・監査・通知なし
        if body.stock == row.stock:
            await session.rollback()
            return StockUpdateResult(
                out=StockUpdateOut(
                    variant_id=row.variant_id,
                    sku=row.sku,
                    stock=row.stock,
                    previous_stock=row.stock,
                    changed=False,
                    restock_waiting=0,
                ),
                restocked=False,
            )
        # 6. 絶対値の SET
        await repo.set_variant_stock(session, variant_id, body.stock)
        # 7. 再入荷（0 から 1 以上）のときだけ、未通知の申込件数を数える
        restocked = is_restock(row.stock, body.stock)
        waiting = await repo.count_pending_restock(session, variant_id) if restocked else 0
        # 8. 監査ログ
        await write_admin_audit(
            session,
            staff,
            action=ACTION_STOCK_SET,
            target_type="variant",
            target_id=str(variant_id),
            detail={
                "sku": row.sku,
                "before": row.stock,
                "after": body.stock,
                "restock_waiting": waiting,
            },
        )
        # 9. COMMIT
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return StockUpdateResult(
        out=StockUpdateOut(
            variant_id=row.variant_id,
            sku=row.sku,
            stock=body.stock,
            previous_stock=row.stock,
            changed=True,
            restock_waiting=waiting,
        ),
        restocked=restocked,
    )


async def notify_in_background(variant_id: int, mail: MailAdapter) -> None:
    """応答を返したあとの後処理（DS-PRC-051c 手順 10）。自分の DB セッションを開く。

    申込が 0 件でも呼ぶ（COMMIT の直前に申し込んだ人を取りこぼさないため）。例外は握り、
    種別（例外の型名）だけをログに出す。在庫の更新の結果・応答には影響させない。
    後処理が動くまでに在庫が 0 に戻っていれば、`notify_restock` は何も送らない（手順 11）。
    """
    try:
        async with get_sessionmaker()() as session:
            await notify_restock(session, variant_id, mail=mail)
    except Exception as exc:  # noqa: BLE001  後処理の失敗で在庫更新の結果を変えない
        logger.error("再入荷通知の後処理に失敗 variant=%s (%s)", variant_id, type(exc).__name__)
