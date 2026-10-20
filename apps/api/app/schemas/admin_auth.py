"""管理認証 API の要求／応答の型（DS-API-050・050a・050b。設計仕様書 P2 追補c 4.1）。

入力の検査（Pydantic。形・長さ）:

- login_id: NFKC 正規化・前後空白除去・小文字化のあと `^[a-z0-9][a-z0-9._-]{2,49}$`
  （`BeforeValidator`。正規化は `services/admin_auth.normalize_login_id`）
- password: NFKC 正規化のあと 1〜128 文字（最小長は課さない。seed で入れた値を締め出さないため。
  会員のログインと同じ `LoginPasswordIn`）
- 未知の項目（`role` など）は無視する（mass assignment 対策）

応答に内部 ID・パスワードのハッシュを出さない（4.0）。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator
from pydantic_core import PydanticCustomError

from app.schemas.auth import LoginPasswordIn
from app.services.admin_auth import InvalidLoginId, normalize_login_id

# InvalidLoginId.reason → Pydantic のエラー型名（errors.map_reason が reason 固定語へ変換する）。
# `string_too_short` は入力が空・空白のみなら `required`、それ以外は `out_of_range`
_LOGIN_ID_ERROR_TYPES = {
    "required": "string_too_short",
    "too_long": "string_too_long",
    "too_short": "string_too_short",
    "format": "value_error",
}


def _normalize_login_id_input(value: object) -> object:
    if not isinstance(value, str):
        return value  # 型の違いは標準の検査（format）に任せる
    try:
        return normalize_login_id(value)
    except InvalidLoginId as exc:
        raise PydanticCustomError(
            _LOGIN_ID_ERROR_TYPES[exc.reason], "ログイン ID が不正です"
        ) from exc


LoginIdIn = Annotated[str, BeforeValidator(_normalize_login_id_input)]


class AdminLoginIn(BaseModel):
    """DS-API-050 管理ログインの要求。"""

    login_id: LoginIdIn
    password: LoginPasswordIn


class AdminStaffOut(BaseModel):
    """管理者の表示用の項目。内部 ID・パスワードのハッシュは返さない（DS-API-050b も同じ形）。"""

    login_id: str
    role: str


class AdminLoginOut(BaseModel):
    """DS-API-050 の応答。BFF が `session_token` を Cookie `asid` にして本文から除く。"""

    session_token: str
    staff: AdminStaffOut
