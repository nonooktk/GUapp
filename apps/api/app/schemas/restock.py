"""再入荷通知の申込の要求／応答（DS-API-007。設計仕様書 P2 追補b 4.5）。

メールは DS-API-030 と同じ正規化（NFKC・前後空白除去・小文字化。B の `email_normalize`）のあと、
形式を検査して正規化後の値で保存する。`DEMO_EMAIL_DOMAINS` の判定はサービス層
（422 `unsupported_value`）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.services.email_normalize import EMAIL_MAX_LENGTH, InvalidEmail, normalize_email

# 本編 7.7 S7: variant_id は 1 以上 9223372036854775807 以下
VARIANT_ID_MAX = 9223372036854775807

# InvalidEmail.reason → Pydantic のエラー型（例外ハンドラが 4.5 の reason 固定語へ変換する）
_ERROR_TYPE_BY_REASON = {
    "required": "string_too_short",
    "too_long": "string_too_long",
    "format": "value_error",
}


class RestockIn(BaseModel):
    variant_id: int = Field(ge=1, le=VARIANT_ID_MAX)
    # DS-API-030 と同じ正規化（`services/email_normalize.py`。レーン B の部品を共用する）
    email: str = Field(max_length=EMAIL_MAX_LENGTH)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return normalize_email(value)
        except InvalidEmail as exc:
            raise PydanticCustomError(
                _ERROR_TYPE_BY_REASON[exc.reason], "メールアドレスを確認してください"
            ) from exc


class RestockOut(BaseModel):
    """新規でも、同じ（variant, email）の再申込でも同じ応答。"""

    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: Literal["registered"] = "registered"
