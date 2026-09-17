"""FastAPI アプリ生成。`uvicorn app.main:app` で起動する。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, FastAPI

from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.core.security import install_cors, verify_internal_token
from app.routers import health


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

    # 死活監視だけは内部トークン不要
    app.include_router(health.router)
    # 以降のルーターはすべて内部トークン必須
    app.include_router(build_protected_router())
    return app


def build_protected_router(*extra: APIRouter) -> APIRouter:
    """内部トークン必須のルーター群を `/api/v1` 配下にまとめる。Wave 1 以降で追記する。"""
    api = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_internal_token)])
    for router in extra:
        api.include_router(router)
    return api


app = create_app()
