"""管理：商品・在庫 API（DS-API-051・051a・051b・051c。設計仕様書 P2 追補c 4.2）。

担当レーン: C-2。管理用セッションの検証は `routers/admin/__init__.py` がルーター単位で掛ける
（既定拒否）。ルーターは入出力の型と依存関係だけを持ち、処理は `services/admin_products.py`。

- `GET /products`・`GET /products/{id}`: 読み取り。BFF の窓口なし（ページが FastAPI を直接呼ぶ）
- `PATCH /products/{id}`・`PATCH /variants/{id}/stock`: 更新前の値（`expected_*`）の照合つき。
  CSRF は BFF 側。回数制限は BFF の全体制限のみ（DS-DEC-126）
- 在庫が 0 から 1 以上になったときは、応答を返したあとの後処理（`BackgroundTasks`）で
  再入荷通知を起動する
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.mail import MailAdapter, get_mail_adapter
from app.core.admin_session import CurrentStaff, require_staff
from app.core.db import get_session
from app.schemas.admin_common import Page, PageParams, page_params
from app.schemas.admin_products import (
    ID_MAX,
    AdminProductDetailOut,
    AdminProductListItemOut,
    ProductListParams,
    ProductUpdateIn,
    ProductUpdateOut,
    StockUpdateIn,
    StockUpdateOut,
    product_list_params,
)
from app.services import admin_products as service

router = APIRouter(tags=["admin-products"])


@router.get(
    "/products",
    response_model=Page[AdminProductListItemOut],
    summary="DS-API-051 商品一覧",
)
async def list_products(
    params: ProductListParams = Depends(product_list_params),
    paging: PageParams = Depends(page_params),
    session: AsyncSession = Depends(get_session),
) -> Page[AdminProductListItemOut]:
    """設計書: 4.2 DS-API-051、4.6 DS-PRC-051。
    `GET /products?q=&visibility=&stock=&page=&per_page=`。`product_id` の昇順。
    エラー: 400 `validation_error`／401／403。"""
    return await service.list_products(session, params, paging)


@router.get(
    "/products/{product_id}",
    response_model=AdminProductDetailOut,
    summary="DS-API-051a 商品詳細（非公開でも返す）",
)
async def get_product(
    product_id: int = Path(ge=1, le=ID_MAX),
    session: AsyncSession = Depends(get_session),
) -> AdminProductDetailOut:
    """設計書: 4.2 DS-API-051a。`restock_waiting` は未通知の申込の件数だけ（メールは返さない）。
    エラー: 400／401／403／404 `not_found`。"""
    return await service.get_product(session, product_id)


@router.patch(
    "/products/{product_id}",
    response_model=ProductUpdateOut,
    summary="DS-API-051b 商品の更新（公開・価格。expected_* 必須）",
)
async def update_product(
    body: ProductUpdateIn,
    product_id: int = Path(ge=1, le=ID_MAX),
    staff: CurrentStaff = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> ProductUpdateOut:
    """設計書: 4.2 DS-API-051b、4.6 DS-PRC-051b。
    エラー: 400／401／403／404／422 `unsupported_value`・`limit_exceeded`（価格）／
    409 `stale_data`。"""
    return await service.update_product(session, staff, product_id, body)


@router.patch(
    "/variants/{variant_id}/stock",
    response_model=StockUpdateOut,
    summary="DS-API-051c 在庫の更新（絶対値の SET。0→正で再入荷通知を起動）",
)
async def set_variant_stock(
    body: StockUpdateIn,
    background: BackgroundTasks,
    variant_id: int = Path(ge=1, le=ID_MAX),
    staff: CurrentStaff = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
    mail: MailAdapter = Depends(get_mail_adapter),
) -> StockUpdateOut:
    """設計書: 4.2 DS-API-051c、4.6 DS-PRC-051c、DS-DEC-114・115。

    再入荷（0 から 1 以上）のときだけ、COMMIT のあとの後処理で `notify_restock` を呼ぶ。
    エラー: 400／401／403／404／422 `unsupported_value`・`limit_exceeded`／409 `stale_data`。"""
    result = await service.set_stock(session, staff, variant_id, body)
    if result.restocked:
        background.add_task(service.notify_in_background, variant_id, mail)
    return result.out
