"""DS-API-061 死活監視。内部トークン検証の対象外（security.INTERNAL_TOKEN_EXEMPT_PATHS）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import get_engine

logger = logging.getLogger("app.health")

router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
async def health() -> JSONResponse:
    try:
        # エンジン生成（URL 不正）も接続失敗も同じく 503 に丸める。詳細はログのみ
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("health: DB 接続失敗 %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"code": "db_unavailable"})
    return JSONResponse(status_code=200, content={"status": "ok", "db": "ok"})
