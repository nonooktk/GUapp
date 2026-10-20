"""管理：注文 API の骨格（DS-API-053・053a・053b。設計仕様書 P2 追補c 4.4）。

担当レーン: C-3（C-1 が骨格だけを置いた。中身は C-3 が埋める）。
未実装のうちは 501 `not_implemented`。埋めるときの約束は `routers/admin/products.py` と同じ
（注文状態の更新は `expected_*` を使わず、遷移表で判定する。DS-DEC-113）。
注文は注文番号（`^GU-[0-9]{6}-[A-HJ-NP-Z2-9]{8}$`）で指し、内部 ID を宛先にしない。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(tags=["admin-orders"])


@router.get("/orders", summary="DS-API-053 注文の検索（C-3）")
async def search_orders() -> None:
    """設計書: 4.4 DS-API-053、4.6 DS-PRC-053。`GET /orders?status=&receive_method=&from=&to=
    &order_number=&email=&page=&per_page=`。個人情報はマスクしたメールだけ。"""
    raise not_implemented()


@router.get("/orders/{order_number}", summary="DS-API-053a 注文詳細（C-3）")
async def get_order(order_number: str) -> None:
    """設計書: 4.4 DS-API-053a。取得を `admin.order.view` に記録（できなければ 500）。"""
    raise not_implemented()


@router.patch("/orders/{order_number}/status", summary="DS-API-053b 注文状態の更新（C-3）")
async def update_order_status(order_number: str) -> None:
    """設計書: 4.4 DS-API-053b、4.6 DS-PRC-053b。更新先は preparing・shipped・delivered だけ。"""
    raise not_implemented()
