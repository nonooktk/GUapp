"""UT-SEC-05 拒否ログの `subject`（G-19）。DB 不要。

ログイン失敗・ロック・再設定の拒否など、識別子があるものだけ、どのアカウントが狙われたかを追えるよう
「識別子の SHA-256 の先頭 12 桁」を 1 行ログに足す。生のメール・管理 ID は出さない。
"""

from __future__ import annotations

import hashlib
import json
import logging

import pytest
from starlette.requests import Request

from app.core.errors import AppError
from app.core.rate_limit import SlidingWindowRateLimiter, enforce_rate_limit
from app.core.reject_log import SUBJECT_LENGTH, log_rejection, subject_fingerprint
from app.services.email_normalize import login_identifier

SHA = hashlib.sha256(b"taro@example.com").hexdigest()


def _request(path: str = "/api/v1/auth/login") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def _lines(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "app.security"]


def test_ut_sec_05_subject_is_the_first_12_hex_digits_of_the_sha256(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.security"):
        log_rejection(
            _request(), status=401, code="invalid_credentials", ip="203.0.113.77", subject=SHA
        )
    (line,) = _lines(caplog)
    assert line == {
        "event": "request_rejected",
        "path": "/api/v1/auth/login",
        "method": "POST",
        "status": 401,
        "code": "invalid_credentials",
        "ip": "203.0.113.0",
        "subject": SHA[:12],
    }
    assert SUBJECT_LENGTH == 12 and len(line["subject"]) == 12
    assert SHA not in caplog.text, "64 桁の全体は出さない"


def test_ut_sec_05_without_subject_the_line_is_unchanged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.security"):
        log_rejection(_request(), status=429, code="rate_limited", ip="203.0.113.77")
    (line,) = _lines(caplog)
    assert "subject" not in line
    assert list(line) == ["event", "path", "method", "status", "code", "ip"]


@pytest.mark.parametrize(
    "raw",
    ["taro@example.com", "staff-admin", "", SHA[:12], SHA.upper(), SHA + "0", "g" * 64],
)
def test_ut_sec_05_a_value_that_is_not_a_sha256_is_never_written(
    raw: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert subject_fingerprint(raw) is None
    with caplog.at_level(logging.WARNING, logger="app.security"):
        log_rejection(
            _request(), status=401, code="invalid_credentials", ip="203.0.113.7", subject=raw
        )
    (line,) = _lines(caplog)
    assert "subject" not in line
    if raw:
        assert raw not in caplog.text


def test_ut_sec_05_per_email_rate_limit_logs_the_subject_but_per_ip_does_not(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """再設定の要求のメール単位の制限（キーはメールの SHA-256）だけ subject が付く。"""
    request = _request("/api/v1/auth/password-reset/request")
    request.scope["app"] = type("A", (), {})()
    request.app.state = type("S", (), {})()
    request.app.state.rate_limiters = {
        "password_reset_request_email": SlidingWindowRateLimiter(limit=1, window_seconds=60),
        "register": SlidingWindowRateLimiter(limit=1, window_seconds=60),
    }
    key = login_identifier("taro@example.com")
    assert key == hashlib.sha256(b"taro@example.com").hexdigest()
    with caplog.at_level(logging.WARNING, logger="app.security"):
        enforce_rate_limit(request, "password_reset_request_email", key=key)
        with pytest.raises(AppError):
            enforce_rate_limit(request, "password_reset_request_email", key=key)
        enforce_rate_limit(request, "register")
        with pytest.raises(AppError):
            enforce_rate_limit(request, "register")
    by_email, by_ip = _lines(caplog)
    assert by_email["subject"] == key[:12] and by_email["code"] == "rate_limited"
    assert "subject" not in by_ip
    assert "taro@example.com" not in caplog.text.lower()
