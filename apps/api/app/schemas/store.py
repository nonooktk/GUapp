"""受け取り店舗 API の応答（DS-API-026。設計仕様書 P2 追補b 4.3）。

担当レーン: C（11.2）。レーン A がルーター骨格の型として先に置いた。郵便番号・内部 ID は返さない。
"""

from __future__ import annotations

from pydantic import BaseModel


class StoreOut(BaseModel):
    code: str
    name: str
    prefecture: str
    address: str


class StoreListOut(BaseModel):
    """`pickup_enabled` が真の店舗を `sort_order`・`id` の順に返す。一覧が空でも 200。"""

    items: list[StoreOut]
