"""FastAPI アプリ生成。`uvicorn app.main:app` で起動する。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, FastAPI

from app.adapters.llm import warn_if_misconfigured
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.core.rate_limit import SlidingWindowRateLimiter, build_rate_limiters
from app.core.security import install_cors, verify_internal_token
from app.core.security_headers import SecurityHeadersMiddleware
from app.routers import (
    auth,
    cart,
    catalog,
    chat,
    checkout,
    content,
    health,
    me,
    me_orders,
    orders,
    restock,
    search,
    stores,
)
from app.routers import settings as settings_router
from app.routers.admin import router as admin_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(logging.INFO, extra_secrets=[settings.INTERNAL_TOKEN, settings.OPENAI_API_KEY])
    warn_if_misconfigured(settings)

    docs_kwargs: dict[str, str | None] = {}
    if settings.is_production:
        # 本番は Swagger を無効化（設計仕様書 4.1・7.1）
        docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}

    app = FastAPI(title="GU EC API", version="0.1.0", **docs_kwargs)  # type: ignore[arg-type]

    install_error_handlers(app)
    install_cors(app, settings)
    # 全応答にセキュリティヘッダ（S5）。CORS より外側に置き、CORS の応答にも付ける
    app.add_middleware(SecurityHeadersMiddleware)

    # ゲスト注文照会のレート制限器（app ごとに 1 つ。100 回/時/IP。設計仕様書 7.5）
    app.state.lookup_rate_limiter = SlidingWindowRateLimiter()
    # P2-b の個別制限器（名前つき。IP ごとに 10 回/時 など。DS-DEC-84）。`enforce_rate_limit`・
    # `ip_rate_limit` が `app.state.rate_limiters[名前]` を引く
    app.state.rate_limiters = build_rate_limiters()
    # AI アシスタントの IP 回数制限器（既定 30 回/時/IP。P2 追補d DS-PRC-029-4）
    app.state.chat_rate_limiter = SlidingWindowRateLimiter(
        limit=settings.CHAT_IP_LIMIT_PER_HOUR, window_seconds=3600
    )

    # 死活監視だけは内部トークン不要
    app.include_router(health.router)
    # 以降のルーターはすべて内部トークン必須
    app.include_router(build_protected_router())

    if settings.is_test:
        # テスト専用ルートと同時性フック。本番経路ではこのブロックに入らず import もしない
        from app.core import testing_hooks
        from app.routers import testing as testing_router

        testing_hooks.set_delay_ms(settings.TEST_RESERVE_DELAY_MS)
        app.include_router(testing_router.router)
    return app


def build_protected_router(*extra: APIRouter) -> APIRouter:
    """内部トークン必須のルーター群を `/api/v1` 配下にまとめる。"""
    api = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_internal_token)])
    # Wave 1: 閲覧（DS-API-001〜003）・カート（010〜013）・公開設定（020）
    api.include_router(catalog.router)
    api.include_router(cart.router)
    api.include_router(settings_router.router)
    # Wave 2: 確認画面（021）・注文確定（022）・注文照会（023）
    api.include_router(checkout.router)
    api.include_router(orders.router)
    # P2-a: コンテンツ・お知らせ・FAQ・静的ページ（DS-API-005・006）
    api.include_router(content.router)
    # P2-a: 商品検索・検索サジェスト（DS-API-004・004a）
    api.include_router(search.router)
    # P2-b: 認証・会員・注文履歴・店舗・再入荷（DS-API-030〜036・024・024a・026・007）。
    # レーン A は骨格（501）。中身は B（auth・me）と C（me_orders・stores・restock）
    api.include_router(auth.router)
    api.include_router(me.router)
    api.include_router(me_orders.router)
    api.include_router(stores.router)
    api.include_router(restock.router)
    # P2-c: 管理 API（DS-API-050〜053b）。ログイン・ログアウトを除き、ルーター単位で
    # `require_staff` を掛けた既定拒否（DS-DEC-109）。骨格（501）は C-2・C-3 が埋める
    api.include_router(admin_router)
    # P2-d: AI アシスタント（DS-API-040・041）
    api.include_router(chat.router)
    for router in extra:
        api.include_router(router)
    return api


app = create_app()
