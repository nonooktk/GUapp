"""管理：設定 API の骨格（DS-API-052・052a。設計仕様書 P2 追補c 4.3）。

担当レーン: C-2（C-1 が骨格だけを置いた。中身は C-2 が埋める。ADR-0006 の削る順番の④なので、
商品・在庫より後に作る）。未実装のうちは 501 `not_implemented`。埋めるときの約束は
`routers/admin/products.py` と同じ。公開用の `routers/settings.py`（DS-API-020）とは別物。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["admin-settings"])


@router.get("/settings", summary="DS-API-052 設定の取得（C-2）")
async def get_settings_admin() -> None:
    """設計書: 4.3 DS-API-052。4 件（tax_rate・shipping_fee・free_shipping_threshold・
    payment_timeout_minutes〈表示のみ〉）を返す。"""
    raise not_implemented()


@router.patch("/settings", summary="DS-API-052a 設定の更新（C-2）")
async def update_settings_admin() -> None:
    """設計書: 4.3 DS-API-052a、4.6 DS-PRC-052。キー名の昇順に `FOR UPDATE`。`expected_*` 必須。"""
    raise not_implemented()
