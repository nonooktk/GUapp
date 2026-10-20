"""再入荷通知の申込の要求／応答（DS-API-007。設計仕様書 P2 追補b 4.5）。

担当レーン: C（11.2）。レーン A がルーター骨格の型として先に置いた。**メールの正規化
（NFKC・前後空白除去・小文字化）と形式検査・`DEMO_EMAIL_DOMAINS` の判定は C が足す**
（DS-API-030 と同じ。B の `services/email_normalize.py` を共用してよい）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 本編 7.7 S7: variant_id は 1 以上 9223372036854775807 以下
VARIANT_ID_MAX = 9223372036854775807


class RestockIn(BaseModel):
    variant_id: int = Field(ge=1, le=VARIANT_ID_MAX)
    email: str = Field(max_length=254)


class RestockOut(BaseModel):
    """新規でも、同じ（variant, email）の再申込でも同じ応答。"""

    # 応答のキーは常に出す。既定値のある項目も OpenAPI の required に入れる
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: Literal["registered"] = "registered"
