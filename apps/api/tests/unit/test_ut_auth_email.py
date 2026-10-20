"""UT-AUTH-09・10・13（メールの正規化・ログインの識別子・DEMO_EMAIL_DOMAINS の判定）。

設計仕様書 P2 追補b DS-DEC-69・70・88、テスト設計書 P2 追補b 5.1。DB は使わない。
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import map_reason
from app.schemas.auth import LoginIn, PasswordResetRequestIn, RegisterIn
from app.services.email_normalize import (
    InvalidEmail,
    is_email_domain_allowed,
    login_identifier,
    normalize_email,
)

# ── UT-AUTH-09 メールの正規化 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "demo@example.com",
        "ＤＥＭＯ＠ＥＸＡＭＰＬＥ．ＣＯＭ",  # 全角
        "  demo@example.com  ",  # 前後の空白
        "　demo@example.com　",  # 全角空白
        "DEMO@Example.COM",  # 大文字
    ],
)
def test_ut_auth_09_variants_normalize_to_same_halfwidth_lowercase(raw: str) -> None:
    assert normalize_email(raw) == "demo@example.com"


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("demo​@example.com", "format"),  # ゼロ幅スペース
        ("de‍mo@example.com", "format"),  # ゼロ幅接合子
        ("de\u0007mo@example.com", "format"),  # 制御文字
        ("de\nmo@example.com", "format"),
        ("de mo@example.com", "format"),  # 内部の空白
        ("a@b", "format"),
        ("abc", "format"),
        ("a@", "format"),
        ("@example.com", "format"),
        ("", "required"),
        ("   ", "required"),
        ("　", "required"),
    ],
)
def test_ut_auth_09_rejects_invisible_chars_and_bad_format(raw: str, reason: str) -> None:
    with pytest.raises(InvalidEmail) as info:
        normalize_email(raw)
    assert info.value.reason == reason


def test_ut_auth_09_length_boundary_254_ok_255_rejected() -> None:
    domain = "@example.com"
    ok = "a" * (254 - len(domain)) + domain
    ng = "a" * (255 - len(domain)) + domain
    assert len(ok) == 254 and len(ng) == 255
    assert normalize_email(ok) == ok
    with pytest.raises(InvalidEmail) as info:
        normalize_email(ng)
    assert info.value.reason == "too_long"


def _email_reason(email: object) -> str:
    with pytest.raises(ValidationError) as info:
        PasswordResetRequestIn(email=email)  # type: ignore[arg-type]
    err = info.value.errors()[0]
    return map_reason(str(err["type"]), err.get("input"))


def test_ut_auth_09_schema_maps_errors_to_reason_words() -> None:
    assert PasswordResetRequestIn(email="ＡＢＣ＠Example.com ").email == "abc@example.com"
    assert _email_reason("") == "required"
    assert _email_reason("abc") == "format"
    assert _email_reason("a" * 250 + "@example.com") == "too_long"
    assert _email_reason(123) == "format", "文字列でない値は format"
    assert _email_reason("a​@example.com") == "format"


def test_ut_auth_09_register_and_login_share_the_same_normalization() -> None:
    reg = RegisterIn(email=" Ａ@Example.com", password="correct-horse-1", name="テスト")
    log = LoginIn(email=" Ａ@Example.com", password="x")
    assert reg.email == log.email == "a@example.com"


# ── UT-AUTH-10 ログインの識別子 ──────────────────────────────────────────


def test_ut_auth_10_identifier_is_sha256_of_normalized_email() -> None:
    a = login_identifier(normalize_email("ＤＥＭＯ＠ＥＸＡＭＰＬＥ．ＣＯＭ"))
    b = login_identifier(normalize_email("demo@example.com"))
    c = login_identifier(normalize_email("Demo@Example.com "))
    assert a == b == c
    assert re.fullmatch(r"[0-9a-f]{64}", a)
    assert a != login_identifier(normalize_email("other@example.com"))
    assert "demo" not in a


# ── UT-AUTH-13 DEMO_EMAIL_DOMAINS ────────────────────────────────────────

CASES = [
    # (設定, メール, 期待)
    ("", "a@example.com", True),
    ("", "a@anything.example.org", True),
    ("example.com", "a@example.com", True),
    ("example.com", "a@EXAMPLE.com", True),
    ("example.com", "a@sub.example.com", False),
    ("example.com", "a@example.org", False),
    ("example.com", "a@notexample.com", False),
    ("example.com, example.net", "a@example.net", True),
    ("example.com, example.net", "a@example.org", False),
    ("  Example.COM  ,, ", "a@example.com", True),
]


@pytest.mark.parametrize(("setting", "email", "expected"), CASES)
def test_ut_auth_13_domain_match_is_exact_after_lowercase(
    app_env: Callable[..., None], setting: str, email: str, expected: bool
) -> None:
    app_env(DEMO_EMAIL_DOMAINS=setting)
    allowed = get_settings().demo_email_domains
    assert is_email_domain_allowed(email, allowed) is expected


def test_ut_auth_13_settings_object_directly() -> None:
    settings = Settings(DEMO_EMAIL_DOMAINS="example.com, example.net")
    assert settings.demo_email_domains == frozenset({"example.com", "example.net"})
    assert is_email_domain_allowed("x@example.net", settings.demo_email_domains)
    assert not is_email_domain_allowed("x@sub.example.net", settings.demo_email_domains)
