"""認証 API（DS-API-030〜035。設計仕様書 P2 追補b 4.1・4.8・5.6・7）。

ルーターは入出力の型と依存関係だけを持ち、処理は `app/services/auth.py` にある。

- 状態を変える POST はすべて BFF 側で CSRF 必須（FastAPI では何もしない）
- 回数制限: 個別制限は `ip_rate_limit(名前)`（IP ごと）。DS-API-034 のメールごと（3 回/時）は
  サービス層で `enforce_rate_limit(request, "password_reset_request_email", key=…)`。
  ログインだけは DB の `login_attempts` で数える（DS-DEC-70）
- 「後処理」のメールは `BackgroundTasks` ＋ `safe_send`（応答のあとに送る。DS-DEC-71・89）
- `GET /me`（DS-API-036）は `routers/me.py`
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.mail import MailAdapter, get_mail_adapter
from app.core.db import get_session
from app.core.errors import AppError
from app.core.rate_limit import ip_rate_limit
from app.core.session import SESSION_TOKEN_HEADER
from app.schemas.auth import (
    AcceptedOut,
    LoginIn,
    LoginOut,
    OkOut,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RegisterIn,
    VerifyEmailIn,
    VerifyEmailOut,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=AcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(ip_rate_limit("register"))],
    summary="DS-API-030 会員登録（新規でも既登録でも 202。IP ごとに 10 回/時）",
)
async def register(
    body: RegisterIn,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    mail: MailAdapter = Depends(get_mail_adapter),
) -> AcceptedOut:
    """設計書: 4.1 DS-API-030、4.8 DS-PRC-030、5.6（登録）、DS-DEC-69・71・76。

    エラー: 400 `validation_error`／422 `weak_password`・`unsupported_value`／429。
    """
    await auth_service.register(session, body, background=background, mail=mail)
    return AcceptedOut()


@router.post(
    "/verify-email",
    response_model=VerifyEmailOut,
    dependencies=[Depends(ip_rate_limit("verify_email"))],
    summary="DS-API-031 メール確認（IP ごとに 20 回/時）",
)
async def verify_email(
    body: VerifyEmailIn, session: AsyncSession = Depends(get_session)
) -> VerifyEmailOut:
    """設計書: 4.1 DS-API-031、4.8 DS-PRC-031、DS-DEC-74。

    エラー: 400 `validation_error`／404 `not_found`（無効・期限切れ・使用済みを区別しない）／429。
    """
    await auth_service.verify_email(session, body)
    return VerifyEmailOut()


@router.post(
    "/login",
    response_model=LoginOut,
    summary="DS-API-032 ログイン（DB の login_attempts で制限。DS-DEC-70）",
)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    x_session_token: str | None = Header(default=None, alias=SESSION_TOKEN_HEADER),
    session: AsyncSession = Depends(get_session),
    mail: MailAdapter = Depends(get_mail_adapter),
) -> LoginOut | JSONResponse:
    """設計書: 3.1（シーケンス）、4.1 DS-API-032、4.8 DS-PRC-032、5.6、7.3。

    `X-Session-Token` は古いセッションの削除（再発行）にだけ使う。IP は `client_ip(request)`。
    エラー: 400／401 `invalid_credentials`／403 `account_locked`／429（`Retry-After: 900`）。
    """
    try:
        out = await auth_service.login(
            session,
            body,
            request=request,
            old_session_token=x_session_token,
            background=background,
            mail=mail,
        )
    except AppError as exc:
        # 例外ハンドラの応答には BackgroundTasks が付かない。5 回目の失敗（401）で積んだ
        # ロック通知メールを応答のあとに送れるよう、ハンドラと同じ形の応答に後処理を付けて返す
        return JSONResponse(
            status_code=exc.status,
            content=exc.to_body(),
            headers=exc.headers,
            background=background,
        )
    # セッショントークンを含む応答はキャッシュさせない
    response.headers["Cache-Control"] = "no-store"
    return out


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="DS-API-033 ログアウト（無効・不明なセッションでも 204）",
)
async def logout(
    x_session_token: str | None = Header(default=None, alias=SESSION_TOKEN_HEADER),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """設計書: 4.1 DS-API-033、7.3。`sessions` の該当行を削除する（冪等）。"""
    await auth_service.logout(session, x_session_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset/request",
    response_model=AcceptedOut,
    dependencies=[Depends(ip_rate_limit("password_reset_request"))],
    summary="DS-API-034 パスワード再設定の要求（常に 200。IP 5 回/時＋メール 3 回/時）",
)
async def password_reset_request(
    body: PasswordResetRequestIn,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    mail: MailAdapter = Depends(get_mail_adapter),
) -> AcceptedOut:
    """設計書: 4.1 DS-API-034、4.8 DS-PRC-034、DS-DEC-71・75。

    会員がいるときだけトークンを作り、再設定メールを後処理で送る。応答は会員の有無で変わらない。
    エラー: 400／422 `unsupported_value`／429。
    """
    await auth_service.password_reset_request(
        session, body, request=request, background=background, mail=mail
    )
    return AcceptedOut()


@router.post(
    "/password-reset/confirm",
    response_model=OkOut,
    dependencies=[Depends(ip_rate_limit("password_reset_confirm"))],
    summary="DS-API-035 パスワード再設定の確定（IP ごとに 10 回/時）",
)
async def password_reset_confirm(
    body: PasswordResetConfirmIn, session: AsyncSession = Depends(get_session)
) -> OkOut:
    """設計書: 4.1 DS-API-035、4.8（副作用欄）、5.6（再設定の確定）、DS-DEC-75。

    弱いパスワードの 422 `weak_password` ではトークンを消費しない。自動ログインしない。
    エラー: 400／404 `not_found`／422 `weak_password`／429。
    """
    await auth_service.password_reset_confirm(session, body)
    return OkOut()
