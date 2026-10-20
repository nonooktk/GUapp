"""管理：設定 API（DS-API-052・052a。設計仕様書 P2 追補c 4.3）。

担当レーン: C-2（ADR-0006 の削る順番の④なので、商品・在庫より後に作った）。
公開用の `routers/settings.py`（DS-API-020）とは別物。処理は `services/admin_settings.py`。
ファイルを分けてあるので、削る場合はこのファイルと `services/admin_settings.py`・
`repositories/admin_settings.py`・`schemas/admin_settings.py` を外し、`routers/admin/__init__.py` の
登録を消す（他に影響しない）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_session import CurrentStaff, require_staff
from app.core.db import get_session
from app.schemas.admin_settings import AdminSettingsOut, SettingsUpdateIn, SettingsUpdateOut
from app.services import admin_settings as service

router = APIRouter(tags=["admin-settings"])


@router.get(
    "/settings",
    response_model=AdminSettingsOut,
    summary="DS-API-052 設定の取得",
)
async def get_settings_admin(
    session: AsyncSession = Depends(get_session),
) -> AdminSettingsOut:
    """設計書: 4.3 DS-API-052。4 件（tax_rate・shipping_fee・free_shipping_threshold・
    payment_timeout_minutes〈表示のみ〉）をこの順で返す。エラー: 401／403／500 `internal_error`。"""
    return await service.get_settings(session)


@router.patch(
    "/settings",
    response_model=SettingsUpdateOut,
    summary="DS-API-052a 設定の更新（expected_* 必須。全か無か）",
)
async def update_settings_admin(
    body: SettingsUpdateIn,
    staff: CurrentStaff = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> SettingsUpdateOut:
    """設計書: 4.3 DS-API-052a、4.6 DS-PRC-052。キー名の昇順に `FOR UPDATE`。
    エラー: 400／401／403／422 `unsupported_value`・`limit_exceeded`／409 `stale_data`。"""
    return await service.update_settings(session, staff, body)
