"""FastAPI アプリ生成。`uvicorn app.main:app` で起動する。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, FastAPI

from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import install_cors, verify_internal_token
from app.routers import cart, catalog, checkout, content, health, orders, search
from app.routers import settings as settings_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(logging.INFO, extra_secrets=[settings.INTERNAL_TOKEN])

    docs_kwargs: dict[str, str | None] = {}
    if settings.is_production:
        # 本番は Swagger を無効化（設計仕様書 4.1・7.1）
        docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}

    app = FastAPI(title="GU EC API", version="0.1.0", **docs_kwargs)  # type: ignore[arg-type]

    install_error_handlers(app)
    install_cors(app, settings)

    # ゲスト注文照会のレート制限器（app ごとに 1 つ。100 回/時/IP。設計仕様書 7.5）
    app.state.lookup_rate_limiter = SlidingWindowRateLimiter()

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
    for router in extra:
        api.include_router(router)
    return api


app = create_app()
