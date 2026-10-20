"""メールアドレスの正規化と `DEMO_EMAIL_DOMAINS` の判定（DS-DEC-69・88。設計仕様書 4.1・9.1）。

正規化の順序: NFKC → 前後の空白除去 → 小文字化 → 検査。

- 全角英数・全角記号は半角に、前後の空白（全角空白を含む）は除かれ、大文字は小文字になる
- ゼロ幅文字・制御文字・内部の空白を含む値は拒否（見た目が同じ別のアドレスを作らせない）
- 254 文字以内（正規化後）。形式は `email-validator`（`pydantic[email]` の依存。到達性は見ない）
- 平文のメールは DB・ログに残さない方針のため、`login_identifier` は SHA-256 の 16 進を返す
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection
from typing import Literal

from email_validator import EmailNotValidError, validate_email

from app.core.session import hash_token

EMAIL_MAX_LENGTH = 254

# 拒否する文字カテゴリ（制御・書式〈ゼロ幅など〉・サロゲート・私用・未割り当て・行/段落区切り）
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})

InvalidReason = Literal["required", "too_long", "format"]


class InvalidEmail(ValueError):
    """メールアドレスとして受け付けない値。`reason` は 4.5 の reason 固定語に対応する。"""

    def __init__(self, reason: InvalidReason) -> None:
        super().__init__(reason)
        self.reason: InvalidReason = reason


def normalize_email(raw: str) -> str:
    """NFKC・前後空白除去・小文字化のうえ形式を検査して返す。不正なら `InvalidEmail`。"""
    text = unicodedata.normalize("NFKC", raw).strip().lower()
    if not text:
        raise InvalidEmail("required")
    if len(text) > EMAIL_MAX_LENGTH:
        raise InvalidEmail("too_long")
    for ch in text:
        if ch.isspace() or unicodedata.category(ch) in _FORBIDDEN_CATEGORIES:
            raise InvalidEmail("format")
    try:
        result = validate_email(text, check_deliverability=False)
    except EmailNotValidError as exc:
        raise InvalidEmail("format") from exc
    normalized = result.normalized.lower()
    if len(normalized) > EMAIL_MAX_LENGTH:
        raise InvalidEmail("too_long")
    return normalized


def login_identifier(email: str) -> str:
    """`login_attempts.identifier`・メールごとの回数制限のキー。正規化メールの SHA-256（16 進）。

    全角・半角・大文字違いは正規化で同じ値になる。`email` は `normalize_email` 済みを渡す。
    """
    return hash_token(email)


def email_domain(email: str) -> str:
    """正規化済みメールの `@` より後ろ（最後の `@` で分ける）。"""
    return email.rpartition("@")[2]


def is_email_domain_allowed(email: str, allowed_domains: Collection[str]) -> bool:
    """`DEMO_EMAIL_DOMAINS` の判定（DS-DEC-88）。

    許可ドメインが空なら制限なし。設定があるときは、小文字化したドメインが完全一致のときだけ可
    （サブドメインは不一致）。`allowed_domains` は `Settings.demo_email_domains`（小文字化済み）。
    """
    if not allowed_domains:
        return True
    return email_domain(email.lower()) in allowed_domains
