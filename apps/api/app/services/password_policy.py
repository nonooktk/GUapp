"""パスワードのポリシー（DS-DEC-69。設計仕様書 4.1・7.1。G-17 で強化）。

- 正規化は NFKC のみ。**前後の空白は除去しない**（空白もパスワードの一部）
- 長さは正規化後のコードポイント数で 8〜128（構成ルールなし。NIST SP 800-63B に沿う）。
  長さの検査は Pydantic（`app/schemas/auth.py`）が行い、ここでは禁止パターンだけを見る
- 禁止パターンを 422 `weak_password` にする。比較は大文字小文字・全角半角を区別しない
  （NFKC のあと小文字化）。外部の漏えいリストは取り込まず、コード内の語彙だけで判定する
  1. 禁止語リスト（約 200 語。よくある弱いパスワードの全体一致）
  2. 禁止語の前後に数字・記号を足しただけのもの（`password2`・`Password123!`・`2024qwerty`）。
     `p@ssw0rd` のような記号・数字での置き換え（leet）も同じ語として見る
  3. 正規化後のメールアドレスと同一、またはメールの `@` より前の部分（4 文字以上）を含むもの
  4. 1 種類の文字の繰り返し、短い単位（2〜4 文字）の繰り返し、連番（`12345678`・`abcdefgh`）、
     キーボード配列の並び（`qwertyuiop`・`asdfghjkl`）
- ログインでは下限を課さない（ポリシー改定前の弱いパスワードの会員を締め出さないため）
"""

from __future__ import annotations

import unicodedata
from typing import Literal

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# 禁止リスト（約 200 語）。比較は NFKC・小文字化したあと。外部からの取り込みはしない
# （よく知られた弱いパスワードを書き並べたもの）。先頭の 20 語は旧リスト（UT-AUTH-06）
BANNED_PASSWORDS: frozenset[str] = frozenset(
    {
        # ── 旧リスト 20 語 ──
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
        # ── password 系 ──
        "passw0rd",
        "p@ssw0rd",
        "p@ssword",
        "passwd",
        "pass1234",
        "pass1word",
        "passpass",
        "password!",
        "パスワード",
        "ぱすわーど",
        "パスワード123",
        "パスワード1",
        # ── キーボード配列 ──
        "qwerty",
        "qwertyuiop",
        "qwerty12",
        "qwerty1234",
        "qwerty12345",
        "qwertz",
        "azerty",
        "asdfgh",
        "asdfghjk",
        "asdfghjkl",
        "zxcvbn",
        "zxcvbnm",
        "qwe123",
        "qwe12345",
        "asd123",
        "asdf1234",
        "zxc123",
        "1qaz2wsx",
        "1q2w3e4r",
        "1q2w3e4r5t",
        "1q2w3e",
        "qazwsx",
        "qazwsxedc",
        "zaq12wsx",
        "1qazxsw2",
        "qweasdzxc",
        "1234qwer",
        "qwer1234",
        # ── 数字・連番 ──
        "123456",
        "1234567",
        "12345",
        "1234",
        "123123",
        "123321",
        "654321",
        "987654321",
        "9876543210",
        "12345678910",
        "111111",
        "11111111",
        "000000",
        "00000000",
        "121212",
        "112233",
        "1122334455",
        "123123123",
        "147258369",
        "159753",
        "7777777",
        "20202020",
        # ── abc 系 ──
        "abc123",
        "abc1234",
        "abc123456",  # pragma: allowlist secret
        "abcd",
        "abcdef",
        "abcdefg",
        "abcdefgh",
        "abcdefghi",
        "abcdefghij",
        "abcabc123",
        "1234abcd",
        "a1b2c3d4",
        # ── 定番の英単語 ──
        "iloveu",
        "loveyou",
        "ilove",
        "letmein",
        "welcome",
        "welcome123",
        "admin",
        "administrator",
        "admin1234",
        "admin12345",
        "root",
        "root1234",
        "toor",
        "user",
        "user1234",
        "login",
        "login123",
        "master",
        "hello",
        "hello123",
        "hello1234",
        "helloworld",
        "monkey",
        "dragon",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "soccer",
        "basketball",
        "superman",
        "batman",
        "spiderman",
        "starwars",
        "michael",
        "jennifer",
        "jordan",
        "hunter",
        "shadow",
        "trustno1",
        "freedom",
        "whatever",
        "secret",
        "mustang",
        "ranger",
        "thomas",
        "tigger",
        "robert",
        "daniel",
        "george",
        "charlie",
        "andrew",
        "joshua",
        "matthew",
        "jessica",
        "ashley",
        "nicole",
        "pepper",
        "cookie",
        "summer",
        "winter",
        "spring",
        "autumn",
        "flower",
        "butterfly",
        "computer",
        "internet",
        "google",
        "facebook",
        "amazon",
        "iphone",
        "android",
        "samsung",
        "windows",
        "microsoft",
        "linux",
        "ubuntu",
        "test",
        "test123",
        "test1234",
        "testtest",
        "guest",
        "guest123",
        "default",
        "changeme",
        "temp123",
        "money",
        "lovelove",
        "happy",
        "angel",
        "monster",
        "lucky",
        "forever",
        "killer",
        "secret123",
        "access",
        "qwertyuiopasdfghjkl",
        # ── 日本語圏でよく使われる語 ──
        "sakura",
        "daisuki",
        "aishiteru",
        "konnichiwa",
        "arigatou",
        "arigato",
        "nihon",
        "nippon",
        "nihongo",
        "tokyo",
        "osaka",
        "kyoto",
        "japan",
        "samurai",
        "ninja",
        "kawaii",
        "naruto",
        "pokemon",
        "doraemon",
        "genki",
        "sayonara",
        "ganbare",
        "ichiban",
        "fujisan",
        "yamada",
        "tanaka",
        "suzuki",
        "takahashi",
        "さくら",
        "サクラ",
        "だいすき",
        "あいしてる",
        "にほん",
        "にっぽん",
        "とうきょう",
        "ひみつ",
        "あいうえお",
        "かきくけこ",
        # ── このサイトに関する語 ──
        "guapp",
        "guecsite",
        "ecsite",
        "demo",
        "demo1234",
        "demodemo",
        "gu1234",
    }
)
WeakReason = Literal[
    "banned",
    "banned_decorated",
    "same_as_email",
    "contains_email_local",
    "repeated",
    "sequence",
    "keyboard",
]

# メールの `@` より前の部分を「含むもの」を拒否するときの最小の長さ。短い部分（`ab` など）まで
# 見ると、ふつうの語にも当たって拒否が多すぎるため
EMAIL_LOCAL_MIN_LENGTH = 4
# 繰り返しの単位（1〜4 文字）。8 文字以上でこの単位だけの繰り返しなら拒否する
_REPEAT_UNIT_MAX = 4
# 連番・キーボード配列として拒否する最小の長さ（パスワードの最小長と同じ）
_SEQUENCE_MIN_LENGTH = PASSWORD_MIN_LENGTH
_KEYBOARD_MIN_LENGTH = 6

# キーボードの段（左から右）。逆順も見る
_KEYBOARD_ROWS = (
    "1234567890",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
    "qazwsxedc",
    "1qaz2wsx3edc",
    "qwertyuiopasdfghjklzxcvbnm",  # pragma: allowlist secret
)

# 記号・数字での置き換え（leet）。`1` は `i` と `l` のどちらにも読めるため 2 通りに直す
_LEET_COMMON = {"@": "a", "4": "a", "0": "o", "3": "e", "$": "s", "5": "s", "7": "t", "+": "t"}
_LEET_TABLES = (
    str.maketrans({**_LEET_COMMON, "1": "i", "!": "i"}),
    str.maketrans({**_LEET_COMMON, "1": "l", "!": "l"}),
)


def normalize_password(raw: str) -> str:
    """NFKC のみ（空白は除去しない）。登録・ログイン・再設定で同じ関数を通す。"""
    return unicodedata.normalize("NFKC", raw)


def _strip_non_letters(text: str) -> str:
    """前後の、文字（かな・漢字・英字）でないもの（数字・記号・空白）を取り除く。"""
    start, end = 0, len(text)
    while start < end and not text[start].isalpha():
        start += 1
    while end > start and not text[end - 1].isalpha():
        end -= 1
    return text[start:end]


def _alnum(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum())


def _is_banned_or_decorated(lowered: str) -> WeakReason | None:
    """禁止語そのもの、または禁止語の前後に数字・記号を足しただけのもの。"""
    if lowered in BANNED_PASSWORDS:
        return "banned"
    for candidate in (lowered, *(lowered.translate(t) for t in _LEET_TABLES)):
        if candidate in BANNED_PASSWORDS and candidate != lowered:
            return "banned_decorated"  # leet だけで禁止語になる（`p@ssw0rd` など）
        core = _strip_non_letters(candidate)
        if core and core != candidate and core in BANNED_PASSWORDS:
            return "banned_decorated"
    return None


def _is_repeated(text: str) -> bool:
    """1 種類の文字、または 2〜4 文字の単位だけの繰り返し（8 文字以上）。"""
    if len(text) < PASSWORD_MIN_LENGTH:
        return False
    if len(set(text)) == 1:
        return True
    for unit in range(2, _REPEAT_UNIT_MAX + 1):
        if len(text) % unit == 0 and text == text[:unit] * (len(text) // unit):
            return True
    return False


def _is_sequence(text: str) -> bool:
    """全体が 1 ずつ増える、または減る連番（`12345678`・`abcdefgh`・`87654321`）。"""
    if len(text) < _SEQUENCE_MIN_LENGTH or _alnum(text) != text:
        return False
    steps = {ord(b) - ord(a) for a, b in zip(text, text[1:], strict=False)}
    return steps == {1} or steps == {-1}


def _is_keyboard_run(text: str) -> bool:
    """キーボードの段の一部（逆順も）。"""
    if len(text) < _KEYBOARD_MIN_LENGTH:
        return False
    return any(text in row or text[::-1] in row for row in _KEYBOARD_ROWS)


def _contains_email_local(lowered: str, email: str) -> bool:
    """メールの `@` より前の部分（`+` より前だけも）を含むか。短い部分は見ない。"""
    local = email.lower().split("@", 1)[0]
    candidates = {local, local.split("+", 1)[0]}
    folded = _alnum(lowered)
    for candidate in candidates:
        if len(candidate) >= EMAIL_LOCAL_MIN_LENGTH and candidate in lowered:
            return True
        plain = _alnum(candidate)
        if len(plain) >= EMAIL_LOCAL_MIN_LENGTH and plain in folded:
            return True
    return False


def weak_password_reason(password: str, email: str) -> WeakReason | None:
    """弱いパスワードなら理由、そうでなければ None。DB を見ない（メールの登録有無に依存させない）。

    `password` は `normalize_password` 済み、`email` は正規化済みのメールを渡す。
    大文字小文字は区別しない。
    """
    lowered = password.lower()
    banned = _is_banned_or_decorated(lowered)
    if banned is not None:
        return banned
    if lowered == email.lower():
        return "same_as_email"
    if _is_repeated(lowered):
        return "repeated"
    core = _strip_non_letters(lowered)
    if _is_sequence(lowered) or _is_sequence(core):
        return "sequence"
    if _is_keyboard_run(lowered) or (core != lowered and _is_keyboard_run(core)):
        return "keyboard"
    if _contains_email_local(lowered, email):
        return "contains_email_local"
    return None
