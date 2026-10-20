"""認証 API の要求／応答の型（DS-API-030〜036。設計仕様書 P2 追補b 4.1・4.2）。

担当レーン: 型の置き場は B（11.2）。レーン A がルーター骨格の型として先に置いた最小の契約で、
**入力の検証（NFKC 正規化・メールの形式・パスワードのポリシー・長さ）は B が足す**:

- email: 254 文字以内。NFKC 正規化・前後空白除去・小文字化のあと `EmailStr` で検査
  （`mode="before"`。DS-DEC-69）
- password: NFKC 正規化のあと 8〜128 文字（ログインは 1〜128 文字）。禁止リスト等は
  サービス層で 422 `weak_password`（DS-DEC-69）
- name: 前後空白除去のあと 1〜50 文字。全角空白のみは `required`
- birth_date: 1900-01-01 以上・今日以下

応答に内部 ID・パスワードのハッシュ・生年月日・性別を出さない（4.0・4.2）。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TOKEN_RE = r"^[A-Za-z0-9_-]{43}$"

GenderIn = Literal["female", "male", "other", "no_answer"]


class RegisterIn(BaseModel):
    """DS-API-030 会員登録の要求。"""

    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    name: str = Field(max_length=50)
    birth_date: date | None = None
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

    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


class LoginMemberOut(BaseModel):
    name: str
    email_verified: bool


class LoginOut(BaseModel):
    """DS-API-032 の応答。BFF が `session_token` を Cookie `sid` にして本文から除く（DS-DEC-72）"""

    session_token: str = Field(description="32 バイト乱数の base64url 43 文字")
    member: LoginMemberOut


class PasswordResetRequestIn(BaseModel):
    """DS-API-034 パスワード再設定の要求。"""

    email: str = Field(max_length=254)


class PasswordResetConfirmIn(BaseModel):
    """DS-API-035 パスワード再設定の確定。パスワードは DS-API-030 と同じポリシー。"""

    token: str = Field(pattern=TOKEN_RE)
    password: str = Field(max_length=128)


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
