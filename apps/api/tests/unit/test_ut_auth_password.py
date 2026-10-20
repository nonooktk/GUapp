"""UT-AUTH-01〜08・12（パスワードのハッシュ・ポリシー・トークンの形）。

設計仕様書 P2 追補b DS-DEC-68・69、テスト設計書 P2 追補b 5.1。DB は使わない。
パスワードはすべてテスト用のダミー値（実在の資格情報ではない）。
"""

from __future__ import annotations

import asyncio
import re
import threading
import time

import pytest
from argon2 import PasswordHasher
from pydantic import ValidationError

from app.core import passwords
from app.core.errors import map_reason
from app.core.session import hash_token
from app.schemas.auth import LoginIn, RegisterIn
from app.services.auth import new_token
from app.services.password_policy import (
    BANNED_PASSWORDS,
    normalize_password,
    weak_password_reason,
)

PREFIX = "$argon2id$v=19$m=19456,t=2,p=1$"
EMAIL = "demo@example.com"
PLAIN = "correct-horse-battery-1"  # pragma: allowlist secret


def _to_fullwidth(text: str) -> str:
    """ASCII の印字可能文字を全角にする（U+FF01〜U+FF5E）。"""
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


def _reasons(**payload: object) -> dict[str, str]:
    """RegisterIn の検証エラーを {項目: reason} にする（errors.map_reason と同じ対応）。"""
    with pytest.raises(ValidationError) as info:
        RegisterIn(**payload)  # type: ignore[arg-type]
    return {
        str(e["loc"][0]): map_reason(str(e["type"]), e.get("input")) for e in info.value.errors()
    }


def _register(password: str, **over: object) -> RegisterIn:
    base: dict[str, object] = {"email": EMAIL, "password": password, "name": "テスト"}
    base.update(over)
    return RegisterIn(**base)  # type: ignore[arg-type]


# ── UT-AUTH-01〜03 ハッシュ化・検証・再ハッシュ（DS-DEC-68）─────────────────


def test_ut_auth_01_hash_has_argon2id_params_salt_and_no_plaintext() -> None:
    first = passwords.hash_password(PLAIN)
    second = passwords.hash_password(PLAIN)
    assert first.startswith(PREFIX)
    assert first != second, "ソルトが別なので同じ入力でもハッシュは変わる"
    assert PLAIN not in first
    assert (passwords.TIME_COST, passwords.MEMORY_COST_KIB, passwords.PARALLELISM) == (2, 19456, 1)
    assert passwords.dummy_hash().startswith(PREFIX), "ダミーも現行のパラメータ（処理時間を揃える）"


def test_ut_auth_02_verify_true_only_for_correct_value_and_never_raises() -> None:
    encoded = passwords.hash_password(PLAIN)
    assert passwords.verify_password(encoded, PLAIN) is True
    assert passwords.verify_password(encoded, PLAIN + "x") is False
    assert passwords.verify_password(encoded, "") is False
    for broken in ("not-a-hash", "", None, "$argon2id$broken", "$2b$12$" + "a" * 53):
        assert passwords.verify_password(broken, PLAIN) is False, broken
    # 別アルゴリズム（argon2i）のハッシュ
    argon2i = "$argon2i$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$aGFzaA"
    assert passwords.verify_password(argon2i, PLAIN) is False


def test_ut_auth_03_needs_rehash_only_when_params_differ() -> None:
    assert passwords.needs_rehash(passwords.hash_password(PLAIN)) is False
    low_time = PasswordHasher(time_cost=1, memory_cost=19456, parallelism=1).hash(PLAIN)
    low_memory = PasswordHasher(time_cost=2, memory_cost=8192, parallelism=1).hash(PLAIN)
    assert passwords.needs_rehash(low_time) is True
    assert passwords.needs_rehash(low_memory) is True
    assert passwords.needs_rehash("not-a-hash") is False, "壊れたハッシュで例外を投げない"


async def test_hashing_runs_at_most_two_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """DS-DEC-68: 同時に走る計算は 2 本まで（スレッドプールに載せても上限を超えない）。"""
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def slow_hash(plain: str) -> str:
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return "hashed"

    monkeypatch.setattr(passwords, "hash_password", slow_hash)
    results = await asyncio.gather(*(passwords.hash_password_async("x") for _ in range(8)))
    assert results == ["hashed"] * 8
    assert state["max"] == 2, "同時 2 本まで（1 本に潰れてもいない）"


# ── UT-AUTH-04 正規化 ────────────────────────────────────────────────────


def test_ut_auth_04_nfkc_makes_fullwidth_and_halfwidth_equal() -> None:
    assert normalize_password("ａｂｃｄｅｆｇｈ") == "abcdefgh"
    assert normalize_password("Ａ１２３４５６７８") == "A12345678"  # pragma: allowlist secret
    assert normalize_password("が") == "が", "結合文字は合成される"
    encoded = passwords.hash_password(normalize_password("ａｂｃｄｅｆｇｈ"))
    assert passwords.verify_password(encoded, normalize_password("abcdefgh")) is True


def test_ut_auth_04_surrounding_spaces_are_kept() -> None:
    assert normalize_password("  pass word  ") == "  pass word  "
    assert _register("  pass word  ").password == "  pass word  "
    assert _register("ａｂｃｄｅｆｇｈ").password == "abcdefgh", "スキーマで NFKC に揃う"
    assert LoginIn(email=EMAIL, password="ａｂｃ").password == "abc", "ログインも同じ正規化"


# ── UT-AUTH-05 長さ ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("", "required"),
        ("a" * 7, "out_of_range"),
        ("a" * 8, None),
        ("a" * 128, None),
        ("a" * 129, "too_long"),
        ("😀" * 8, None),
        ("😀" * 7, "out_of_range"),
        ("あ" * 128, None),
        ("ａ" * 129, "too_long"),
    ],
)
def test_ut_auth_05_length_boundaries_by_codepoints_after_nfkc(
    password: str, reason: str | None
) -> None:
    if reason is None:
        assert _register(password).password == normalize_password(password)
    else:
        assert _reasons(email=EMAIL, password=password, name="テスト") == {"password": reason}


def test_ut_auth_05_login_password_has_no_minimum_but_max_128() -> None:
    assert LoginIn(email=EMAIL, password="x").password == "x", "ポリシー改定前の短い値でも通す"
    with pytest.raises(ValidationError):
        LoginIn(email=EMAIL, password="")
    with pytest.raises(ValidationError):
        LoginIn(email=EMAIL, password="a" * 129)


# ── UT-AUTH-06 禁止リスト ────────────────────────────────────────────────


def test_ut_auth_06_banned_list_has_20_words() -> None:
    assert len(BANNED_PASSWORDS) == 20


@pytest.mark.parametrize("word", sorted(BANNED_PASSWORDS))
def test_ut_auth_06_banned_words_in_any_case_and_width(word: str) -> None:
    for variant in (
        word,
        word.upper(),
        word.title(),
        _to_fullwidth(word),
        _to_fullwidth(word.upper()),
    ):
        assert weak_password_reason(normalize_password(variant), EMAIL) == "banned", variant


def test_ut_auth_06_halfwidth_katakana_is_normalized_before_comparison() -> None:
    assert weak_password_reason(normalize_password("ﾊﾟｽﾜｰﾄﾞ1234"), EMAIL) == "banned"
    assert weak_password_reason("password-ok-2026", EMAIL) is None


# ── UT-AUTH-07 メールと同一 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "variant", ["demo@example.com", "DEMO@EXAMPLE.COM", "ｄｅｍｏ＠ｅｘａｍｐｌｅ．ｃｏｍ"]
)
def test_ut_auth_07_password_equal_to_email_is_rejected(variant: str) -> None:
    assert weak_password_reason(normalize_password(variant), EMAIL) == "same_as_email"


def test_ut_auth_07_local_part_only_is_rejected_by_length_not_policy() -> None:
    local_part = "demo"
    reasons = _reasons(email=EMAIL, password=local_part, name="テスト")
    assert reasons == {"password": "out_of_range"}  # pragma: allowlist secret


# ── UT-AUTH-08 同一文字の繰り返し ────────────────────────────────────────


@pytest.mark.parametrize(
    ("password", "weak"),
    [
        ("aaaaaaaa", True),
        ("ああああああああ", True),
        ("あああああああ", False),  # 7 文字は長さで拒否される側（ポリシーの対象外）
        ("aaaaaaab", False),
        ("a" * 128, True),
        ("        ", True),
    ],
)
def test_ut_auth_08_repeated_single_character(password: str, weak: bool) -> None:
    assert (weak_password_reason(password, EMAIL) == "repeated") is weak


# ── UT-AUTH-12 トークンの生成・保存形式 ───────────────────────────────────


def test_ut_auth_12_tokens_are_43_chars_unique_and_stored_as_sha256() -> None:
    tokens = [new_token() for _ in range(10_000)]
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", t) for t in tokens)
    assert len(set(tokens)) == len(tokens)
    stored = hash_token(tokens[0])
    assert re.fullmatch(r"[0-9a-f]{64}", stored) and stored != tokens[0]
