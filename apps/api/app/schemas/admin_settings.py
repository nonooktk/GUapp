"""管理：設定 API の要求／応答（DS-API-052・052a。設計仕様書 P2 追補c 4.3・4.7）。

担当レーン: C-2（ADR-0006 の削る順番の④。商品・在庫とはファイルを分けてある）。

- 型・形（`tax_rate` は `^[0-9]\\.[0-9]{2}$`）・桁あふれ・`expected_*` の欠落・変更するキーなしは
  **400**（このファイル）。業務の範囲（税率 0.00〜0.30、送料 0〜5000、送料無料の下限
  0〜100000）は **422**（`services/admin_settings.py`）
- `payment_timeout_minutes` は更新できない。送られても無視する（定義外の項目として捨てる）
"""

from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)
from pydantic_core import InitErrorDetails, ValidationError

from app.schemas.admin_common import INT32_MAX

TAX_RATE_PATTERN = r"^[0-9]\.[0-9]{2}$"
# 更新できるキー（表示の順。`expected_<key>` と対にする）
EDITABLE_KEYS: tuple[str, ...] = ("tax_rate", "shipping_fee", "free_shipping_threshold")


class _Out(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class AdminSettingItemOut(_Out):
    key: str
    label: str
    value: str | int = Field(description='`tax_rate` は `"0.10"` の文字列、ほかは整数')
    editable: bool
    unit: str | None = Field(description="表示用の単位。無ければ null")
    min: str | int | None = Field(description="更新できる下限。表示のみのキーは null")
    max: str | int | None = Field(description="更新できる上限。表示のみのキーは null")


class AdminSettingsOut(_Out):
    items: list[AdminSettingItemOut]


class SettingsUpdateIn(BaseModel):
    """変更するキーと、対応する `expected_<key>`（画面が表示していた値）。"""

    # `default=None` は「送られていない」の印。検証は通さないので、null は型違いで 400 になる
    tax_rate: StrictStr = Field(default=None, pattern=TAX_RATE_PATTERN)
    shipping_fee: StrictInt = Field(default=None, ge=-INT32_MAX, le=INT32_MAX)
    free_shipping_threshold: StrictInt = Field(default=None, ge=-INT32_MAX, le=INT32_MAX)
    expected_tax_rate: StrictStr = Field(default=None, max_length=20)
    expected_shipping_fee: StrictInt = Field(default=None, ge=-INT32_MAX, le=INT32_MAX)
    expected_free_shipping_threshold: StrictInt = Field(default=None, ge=-INT32_MAX, le=INT32_MAX)

    @model_validator(mode="after")
    def _check_pairs(self) -> SettingsUpdateIn:
        errors: list[InitErrorDetails] = []
        if all(getattr(self, key) is None for key in EDITABLE_KEYS):
            errors.append(InitErrorDetails(type="missing", loc=(), input=None))
        for key in EDITABLE_KEYS:
            if getattr(self, key) is not None and getattr(self, f"expected_{key}") is None:
                errors.append(
                    InitErrorDetails(type="missing", loc=(f"expected_{key}",), input=None)
                )
        if errors:
            raise ValidationError.from_exception_data("SettingsUpdateIn", errors)
        return self

    def requested(self) -> dict[str, tuple[str | int, str | int]]:
        """変更を求められたキーごとの `(新しい値, expected)`。表示の順。"""
        return {
            key: (getattr(self, key), getattr(self, f"expected_{key}"))
            for key in EDITABLE_KEYS
            if getattr(self, key) is not None
        }


class SettingsUpdateOut(_Out):
    items: list[AdminSettingItemOut]
    changed: list[str] = Field(description="値が変わったキー。全項目が同じ値なら空配列")
