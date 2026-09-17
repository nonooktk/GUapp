"""内部トークン検証と CORS（設計仕様書 4.1・7.1・DS-DEC-27）。

- FastAPI は `X-Internal-Token` ヘッダで BFF からの呼び出しだけを受け付ける。
  不一致・欠落は 401 `unauthorized`（4.5 の順序 1）。
- `/api/v1/health` だけは死活監視用に対象外。
- CORS は `CORS_ALLOW_ORIGIN` の 1 オリジンのみ。ワイルドカード禁止。
"""

from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import AppError

INTERNAL_TOKEN_HEADER = "X-Internal-Token"
# 内部トークン検証の対象外パス（死活監視）
INTERNAL_TOKEN_EXEMPT_PATHS: frozenset[str] = frozenset({"/api/v1/health"})


def verify_internal_token(
    x_internal_token: str | None = Header(default=None, alias=INTERNAL_TOKEN_HEADER),
    settings: Settings = Depends(get_settings),
) -> None:
    """`X-Internal-Token` を検証する依存関数。

    ルーター単位で `dependencies=[Depends(...)]` に付ける。
    期待値が未設定なら全リクエストを拒否する（設定漏れで素通しにしない）。
    """
    expected = settings.INTERNAL_TOKEN
    if not expected or not x_internal_token:
        raise AppError(401, "unauthorized")
    if not hmac.compare_digest(x_internal_token.encode(), expected.encode()):
        raise AppError(401, "unauthorized")


def install_cors(app: FastAPI, settings: Settings) -> None:
    """許可オリジン 1 つだけの CORS を組み込む。未設定・ワイルドカードなら CORS 自体を付けない。"""
    origin = settings.CORS_ALLOW_ORIGIN.strip()
    if not origin or origin == "*":
        # ワイルドカード禁止（7.1）。設定漏れは「どこからも許可しない」側に倒す
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", INTERNAL_TOKEN_HEADER],
    )
