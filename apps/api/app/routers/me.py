"""会員情報 API の骨格（DS-API-036。設計仕様書 P2 追補b 4.2）。

担当レーン: ルーターの骨格は A、**中身は B**（`routers/me.py` は B の担当）。
BFF の窓口はなく、Server Component が `X-Session-Token` を付けて直接呼ぶ。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import not_implemented
from app.core.session import CurrentMember, get_current_member
from app.schemas.auth import MeOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeOut, summary="DS-API-036 会員情報の取得")
async def get_me(member: CurrentMember = Depends(get_current_member)) -> MeOut:
    """担当レーン: B。設計書: 4.2 DS-API-036。

    `member`（`app.core.session.CurrentMember`）から `name`・`email`・`email_verified`・
    `personalize_opt_in` を返す。パスワードのハッシュ・内部 ID・生年月日・性別は返さない。
    セッションが無い・無効なら `get_current_member` が 401 `unauthorized` を返す。
    """
    raise not_implemented()
