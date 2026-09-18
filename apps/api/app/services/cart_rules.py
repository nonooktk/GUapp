"""カートの純粋な業務規則（DS-PRC-011・DS-API-010）。DB を見ない関数だけを置き UT で検証する。"""

from __future__ import annotations

import re
import secrets
from typing import Literal

from app.core.errors import AppError

# 1 明細の上限点数・カート合計の上限点数（設計仕様書 DS-PRC-011）
LINE_QUANTITY_LIMIT = 10
CART_TOTAL_LIMIT = 50

StockStatus = Literal["ok", "insufficient", "out_of_stock"]


def check_limits(*, line_quantity: int, cart_total_quantity: int) -> None:
    """加算後の数量で上限を検査する。超過なら 422 `limit_exceeded`（1 明細 → 合計の順）。"""
    if line_quantity > LINE_QUANTITY_LIMIT:
        raise AppError(422, "limit_exceeded", field="quantity", limit=LINE_QUANTITY_LIMIT)
    if cart_total_quantity > CART_TOTAL_LIMIT:
        raise AppError(422, "limit_exceeded", field="quantity", limit=CART_TOTAL_LIMIT)


def stock_status(*, stock: int, quantity: int, published: bool) -> StockStatus:
    """明細の在庫状態。非公開・在庫 0 → out_of_stock、0 < 在庫 < 数量 → insufficient。"""
    if not published or stock <= 0:
        return "out_of_stock"
    if stock < quantity:
        return "insufficient"
    return "ok"


def new_cart_token() -> str:
    """匿名トークン（32 バイト乱数の base64url・43 文字。DS-API-010）。"""
    return secrets.token_urlsafe(32)


# ヘッダで受けるトークンの形（base64url・列は String(64)）。合わなければ「未知」と同じ扱い
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def normalize_token(token: str | None) -> str | None:
    """形が合うトークンだけ返す（カート・注文の両サービスで共用）。"""
    if token and _TOKEN_RE.match(token):
        return token
    return None
