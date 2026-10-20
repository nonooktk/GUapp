"""個人情報のマスク（DS-PRC-053c。設計仕様書 P2 追補c 4.6・DS-DEC-118）。

担当レーン: C-3。純粋関数だけを置く（DB・時計に触れない）。

- `mask_email`: 追補b の `adapters/mail.py` の `mask_email` を再利用する。
  `test@example.com` → `t***@example.com`。形が崩れていれば `***`
- `mask_phone`: ASCII 数字の電話番号。5 桁以上は末尾 4 桁だけ残して残りを `*`、4 桁以下は全部 `*`、
  空文字は空文字

氏名・郵便番号・住所は注文詳細にだけ出し、マスクしない（配送と受け渡しの本人確認に要る。
DS-DEC-118）。
"""

from __future__ import annotations

from app.adapters.mail import mask_email

__all__ = ["mask_email", "mask_phone"]

_VISIBLE_PHONE_DIGITS = 4


def mask_phone(phone: str) -> str:
    """末尾 4 桁だけ残す（`00000005678` → `*******5678`）。4 桁以下は全部 `*`、空は空。"""
    if len(phone) <= _VISIBLE_PHONE_DIGITS:
        return "*" * len(phone)
    return "*" * (len(phone) - _VISIBLE_PHONE_DIGITS) + phone[-_VISIBLE_PHONE_DIGITS:]
