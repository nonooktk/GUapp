"""管理：商品・在庫 API の骨格（DS-API-051・051a・051b・051c。設計仕様書 P2 追補c 4.2）。

担当レーン: C-2（C-1 が骨格だけを置いた。中身は C-2 が埋める）。
未実装のうちは 501 `not_implemented`（管理用セッションの検証は `routers/admin/__init__.py` が
ルーター単位で掛けるので、骨格でも無認証では 501 まで届かない）。

C-2 が埋めるときの約束:

- `router` という名前の `APIRouter`（接頭辞なし）を残す。パスは `/api/v1/admin` からの相対
- 管理者を使うときは `staff: CurrentStaff = Depends(require_staff)`（`app.core.admin_session`）
- 更新は `SELECT … FOR UPDATE` で読んだあとに `ensure_expected`（`app.services.optimistic`）、
  同じトランザクションで `write_admin_audit`（`app.services.admin_audit`）
- 一覧は `page_params`・`Page`・`build_page`（`app.schemas.admin_common`）
- 骨格の `not_implemented()` の呼び出しはこのファイルから取り除く（本番に残さない）
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["admin-products"])


@router.get("/products", summary="DS-API-051 商品一覧（C-2）")
async def list_products() -> None:
    """設計書: 4.2 DS-API-051、4.6 DS-PRC-051。
    `GET /products?q=&visibility=&stock=&page=&per_page=`"""
    raise not_implemented()


@router.get("/products/{product_id}", summary="DS-API-051a 商品詳細（C-2）")
async def get_product(product_id: int) -> None:
    """設計書: 4.2 DS-API-051a。`GET /products/{product_id}`"""
    raise not_implemented()


@router.patch("/products/{product_id}", summary="DS-API-051b 商品の更新（C-2）")
async def update_product(product_id: int) -> None:
    """設計書: 4.2 DS-API-051b、4.6 DS-PRC-051b。公開・価格。`expected_*` 必須。"""
    raise not_implemented()


@router.patch("/variants/{variant_id}/stock", summary="DS-API-051c 在庫の更新（C-2）")
async def set_variant_stock(variant_id: int) -> None:
    """設計書: 4.2 DS-API-051c、4.6 DS-PRC-051c。絶対値の SET。0→正で `notify_restock` を起動。"""
    raise not_implemented()
