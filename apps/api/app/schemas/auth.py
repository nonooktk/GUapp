"""認証 API の要求／応答の型（DS-API-030〜036。設計仕様書 P2 追補b 4.1・4.2）。

入力の検査（Pydantic。形・長さ・範囲）:

- email: NFKC 正規化・前後空白除去・小文字化のあと形式を検査（`mode="before"`。DS-DEC-69）。
  254 文字以内（正規化後）。ゼロ幅・制御文字・内部の空白は拒否
- password: NFKC 正規化のあと 8〜128 文字（ログインは 1〜128 文字）。前後の空白は除去しない。
  禁止リスト等はサービス層で 422 `weak_password`（DS-DEC-69）
- name: 前後空白除去（全角空白を含む）のあと 1〜50 文字。空は `required`
- birth_date: 1900-01-01 以上・今日（JST）以下
- 未知の項目（`role`・`email_verified_at` など）は無視する（mass assignment 対策。A-03）

reason の固定語（required／format／too_long／out_of_range）は `app/core/errors.py` の
`map_reason` が決める。ここでは Pydantic の標準のエラー型名を使って対応させる。

応答に内部 ID・パスワードのハッシュ・生年月日・性別を出さない（4.0・4.2）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field
from pydantic_core import PydanticCustomError

from app.services.email_normalize import InvalidEmail, normalize_email
from app.services.password_policy import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    normalize_password,
)

TOKEN_RE = r"^[A-Za-z0-9_-]{43}$"

BIRTH_DATE_MIN = date(1900, 1, 1)
_JST = ZoneInfo("Asia/Tokyo")

GenderIn = Literal["female", "male", "other", "no_answer"]

# InvalidEmail.reason → Pydantic のエラー型名（errors.map_reason が reason 固定語へ変換する）
_EMAIL_ERROR_TYPES = {
    "required": "string_too_short",
    "too_long": "string_too_long",
    "format": "value_error",
}


def _normalize_email_input(value: object) -> object:
    if not isinstance(value, str):
        return value  # 型の違いは標準の検査（format）に任せる
    try:
        return normalize_email(value)
    except InvalidEmail as exc:
        raise PydanticCustomError(
            _EMAIL_ERROR_TYPES[exc.reason], "メールアドレスが不正です"
        ) from exc


def _nfkc(value: object) -> object:
    return normalize_password(value) if isinstance(value, str) else value


def _strip(value: object) -> object:
    # str.strip() は全角空白（U+3000）も除く
    return value.strip() if isinstance(value, str) else value


def _check_birth_date(value: date | None) -> date | None:
    if value is None:
        return None
    if value < BIRTH_DATE_MIN:
        raise PydanticCustomError("greater_than_equal", "生年月日が範囲外です")
    if value > datetime.now(UTC).astimezone(_JST).date():
        raise PydanticCustomError("less_than_equal", "生年月日が範囲外です")
    return value


# 長さの制約は str 自体に掛け（エラー型が string_too_short／string_too_long になる）、
# その外側に BeforeValidator を置く。正規化・strip が先に走り、正規化後の値に制約が効く
EmailIn = Annotated[str, Field(max_length=254), BeforeValidator(_normalize_email_input)]
NewPasswordIn = Annotated[
    str,
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
    BeforeValidator(_nfkc),
]
LoginPasswordIn = Annotated[
    str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH), BeforeValidator(_nfkc)
]
NameIn = Annotated[str, Field(min_length=1, max_length=50), BeforeValidator(_strip)]


class RegisterIn(BaseModel):
    """DS-API-030 会員登録の要求。"""

    email: EmailIn
    password: NewPasswordIn
    name: NameIn
    birth_date: Annotated[date | None, AfterValidator(_check_birth_date)] = None
    gender: GenderIn | None = None
    personalize_opt_in: bool = False


class AcceptedOut(BaseModel):
    """DS-API-030（202）・DS-API-034（200）の応答。新規でも既登録でも同じ（DS-DEC-71）。"""

    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: Literal["accepted"] = "accepted"


class VerifyEmailIn(BaseModel):
    """DS-API-031 メール確認の要求。"""

    token: str = Field(pattern=TOKEN_RE)


class VerifyEmailOut(BaseModel):
    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    verified: Literal[True] = True


class LoginIn(BaseModel):
    """DS-API-032 ログインの要求。パスワードの最小長は 8 にしない（既存の会員を締め出さない）。"""

    email: EmailIn
    password: LoginPasswordIn


class LoginMemberOut(BaseModel):
    name: str
    email_verified: bool


class LoginOut(BaseModel):
    """DS-API-032 の応答。BFF が `session_token` を Cookie `sid` にして本文から除く（DS-DEC-72）"""

    session_token: str = Field(description="32 バイト乱数の base64url 43 文字")
    member: LoginMemberOut


class PasswordResetRequestIn(BaseModel):
    """DS-API-034 パスワード再設定の要求。"""

    email: EmailIn


class PasswordResetConfirmIn(BaseModel):
    """DS-API-035 パスワード再設定の確定。パスワードは DS-API-030 と同じポリシー。"""

    token: str = Field(pattern=TOKEN_RE)
    password: NewPasswordIn


class OkOut(BaseModel):
    """DS-API-035 の応答。自動ログインはしない（DS-DEC-75）。"""

    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: Literal["ok"] = "ok"


class MeOut(BaseModel):
    """DS-API-036 会員情報の取得。内部 ID・ハッシュ・生年月日・性別は返さない。"""

    name: str
    email: str
    email_verified: bool
    personalize_opt_in: bool
