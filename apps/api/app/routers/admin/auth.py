"""管理認証 API（DS-API-050・050a・050b。設計仕様書 P2 追補c 4.1・4.6・5.6・7.3）。

担当レーン: C-1。ルーターは入出力の型と依存関係だけを持ち、処理は `app/services/admin_auth.py`・
`app/core/admin_session.py` にある。

- `public_router`: 管理用セッションを要しない 2 本（ログイン・ログアウト）。ログインの個別制限は
  DB の `login_attempts`（`subject_type=staff`。DS-DEC-110）。管理 API 全体の個別の回数制限は
  足さない（DS-DEC-126）
- `guarded_router`: `GET /me`。`routers/admin/__init__.py` が `require_staff` を掛けた
  ルーターに入れる（既定拒否。DS-DEC-109）
- 状態を変える POST は BFF 側で CSRF 必須（FastAPI では何もしない）
- 応答は全件 `Cache-Control: no-store`（既存のミドルウェア）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_session import ADMIN_SESSION_TOKEN_HEADER, CurrentStaff, require_staff
from app.core.db import get_session
from app.schemas.admin_auth import AdminLoginIn, AdminLoginOut, AdminStaffOut
from app.services import admin_auth as admin_auth_service

public_router = APIRouter(prefix="/auth")
guarded_router = APIRouter()


@public_router.post(
    "/login",
    response_model=AdminLoginOut,
    summary="DS-API-050 管理ログイン（DB の login_attempts で制限。DS-DEC-110）",
)
async def admin_login(
    body: AdminLoginIn,
    request: Request,
    x_admin_session_token: str | None = Header(default=None, alias=ADMIN_SESSION_TOKEN_HEADER),
    session: AsyncSession = Depends(get_session),
) -> AdminLoginOut:
    """設計書: 3.1（シーケンス）、4.1 DS-API-050、4.6 DS-PRC-050、5.6、7.3。

    `X-Admin-Session-Token` は古いセッションの削除（再発行）にだけ使う。IP は `client_ip(request)`。
    エラー: 400／401 `invalid_credentials`／403 `account_locked`／429（`Retry-After: 900`）。
    """
    result = await admin_auth_service.login(
        session,
        login_id=body.login_id,
        password=body.password,
        request=request,
        old_session_token=x_admin_session_token,
    )
    return AdminLoginOut(
        session_token=result.session_token,
        staff=AdminStaffOut(login_id=result.login_id, role=result.role),
    )


@public_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="DS-API-050a 管理ログアウト（無効・不明なセッションでも 204）",
)
async def admin_logout(
    x_admin_session_token: str | None = Header(default=None, alias=ADMIN_SESSION_TOKEN_HEADER),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """設計書: 4.1 DS-API-050a。`require_staff` は通さない（冪等）。

    `subject_type=staff` の該当行だけを削除し、行があったときだけ `admin.logout` を記録する。
    """
    await admin_auth_service.logout(session, x_admin_session_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@guarded_router.get(
    "/me",
    response_model=AdminStaffOut,
    summary="DS-API-050b 管理者情報の取得",
)
async def admin_me(staff: CurrentStaff = Depends(require_staff)) -> AdminStaffOut:
    """設計書: 4.1 DS-API-050b、4.6 DS-PRC-050b。`{login_id, role}` のみ（内部 ID・ハッシュなし）。

    エラー: 401 `unauthorized`／403 `forbidden`（会員のセッション・許可外のロール）。
    """
    return AdminStaffOut(login_id=staff.login_id, role=staff.role)
