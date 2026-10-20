"""パスワードのポリシー（DS-DEC-69。設計仕様書 4.1・7.1）。

- 正規化は NFKC のみ。**前後の空白は除去しない**（空白もパスワードの一部）
- 長さは正規化後のコードポイント数で 8〜128（構成ルールなし。NIST SP 800-63B に沿う）。
  長さの検査は Pydantic（`app/schemas/auth.py`）が行い、ここでは禁止パターンだけを見る
- 禁止パターン 3 種を 422 `weak_password` にする: 禁止リスト 20 語（大文字・全角を同一視）／
  正規化後のメールアドレスと同一／同一文字の繰り返し（8 文字以上で全文字が同じ）
- ログインでは下限を課さない（ポリシー改定前の短いパスワードの会員を締め出さないため）
"""

from __future__ import annotations

import unicodedata
from typing import Literal

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# 禁止リスト 20 語（テスト設計書 UT-AUTH-06）。比較は NFKC・小文字化したあと
BANNED_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password12",
        "password123",
        "12345678",
        "123456789",
        "1234567890",
        "12341234",
        "01234567",
        "qwertyui",
        "qwerty123",
        "abcd1234",
        "abc12345",
        "iloveyou",
        "letmein1",
        "welcome1",
        "admin123",
        "guapp123",
        "パスワード1234",
        "ぱすわーど1234",
    }
)
assert len(BANNED_PASSWORDS) == 20

WeakReason = Literal["banned", "same_as_email", "repeated"]


def normalize_password(raw: str) -> str:
    """NFKC のみ（空白は除去しない）。登録・ログイン・再設定で同じ関数を通す。"""
    return unicodedata.normalize("NFKC", raw)


def weak_password_reason(password: str, email: str) -> WeakReason | None:
    """弱いパスワードなら理由、そうでなければ None。DB を見ない（メールの登録有無に依存させない）。

    `password` は `normalize_password` 済み、`email` は正規化済みのメールを渡す。
    """
    lowered = password.lower()
    if lowered in BANNED_PASSWORDS:
        return "banned"
    if lowered == email.lower():
        return "same_as_email"
    if len(password) >= PASSWORD_MIN_LENGTH and len(set(password)) == 1:
        return "repeated"
    return None
