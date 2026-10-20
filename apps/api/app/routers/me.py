"""会員情報 API（DS-API-036。設計仕様書 P2 追補b 4.2）。

BFF の窓口はなく、Server Component が `X-Session-Token` を付けて直接呼ぶ。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.session import CurrentMember, get_current_member
from app.schemas.auth import MeOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeOut, summary="DS-API-036 会員情報の取得")
async def get_me(member: CurrentMember = Depends(get_current_member)) -> MeOut:
    """`name`・`email`・`email_verified`・`personalize_opt_in` だけを返す。

    パスワードのハッシュ・内部 ID・生年月日・性別は返さない。
    セッションが無い・無効（期限切れ・スタッフ・匿名化済みを含む）なら `get_current_member` が
    401 `unauthorized` を返す。
    """
    return MeOut(
        name=member.name,
        email=member.email,
        email_verified=member.email_verified,
        personalize_opt_in=member.personalize_opt_in,
    )
