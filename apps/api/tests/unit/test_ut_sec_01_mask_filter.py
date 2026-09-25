"""UT-SEC-01 秘密マスクフィルタ（設計仕様書 7.2「ログ」）。"""

from __future__ import annotations

import logging

import pytest

from app.core.logging import MASK, SecretMaskFilter, setup_logging


def _emit(record_filter: SecretMaskFilter, message: str, *args: object) -> str:
    logger = logging.getLogger("test.mask")
    record = logger.makeRecord("test.mask", logging.INFO, __file__, 1, message, args, None)
    assert record_filter.filter(record) is True
    return record.getMessage()


def test_ut_sec_01_mask_stripe_key() -> None:
    out = _emit(
        SecretMaskFilter(), "key=sk_live_ABCdef0123456789XYZ done"
    )  # pragma: allowlist secret  # noqa: E501
    assert "sk_live_ABCdef0123456789XYZ" not in out  # pragma: allowlist secret
    assert f"sk_live_{MASK}" in out
    out2 = _emit(SecretMaskFilter(), "key=sk_test_zzz999 whsec_abc123")
    assert "sk_test_zzz999" not in out2 and "whsec_abc123" not in out2


def test_ut_sec_01_mask_connection_string_credentials() -> None:
    url = "mysql+asyncmy://guapp_user:S3cretPassw0rd@127.0.0.1:3306/guapp"  # pragma: allowlist secret  # noqa: E501
    out = _emit(SecretMaskFilter(), "connect %s", url)
    assert "S3cretPassw0rd" not in out
    assert "guapp_user" not in out
    # ホスト・DB 名は残る（トラブルシュートに必要）
    assert f"mysql+asyncmy://{MASK}:{MASK}@127.0.0.1:3306/guapp" in out


def test_ut_sec_01_mask_bearer_token() -> None:
    out = _emit(SecretMaskFilter(), "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def")
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert f"Bearer {MASK}" in out


def test_ut_sec_01_mask_internal_token_header_and_value() -> None:
    f = SecretMaskFilter(extra_secrets=["my-internal-token-value"])
    out = _emit(f, "headers: X-Internal-Token: my-internal-token-value ; x=1")
    assert "my-internal-token-value" not in out
    # ヘッダ形式（値が別物でも）もマスクされる
    out2 = _emit(f, 'req {"x-internal-token": "another-value-123"}')
    assert "another-value-123" not in out2
    # 実値が単独で出てもマスクされる
    out3 = _emit(f, "token=my-internal-token-value")
    assert "my-internal-token-value" not in out3


def test_ut_sec_01_mask_in_args_not_only_msg() -> None:
    """%s 引数側に秘密があっても潰れる。"""
    out = _emit(SecretMaskFilter(), "stripe %s / db %s", "sk_live_QQQ", "mysql://u:p@h/db")
    assert "sk_live_QQQ" not in out and "u:p@" not in out


def test_ut_sec_01_filter_keeps_args_structure_for_uvicorn_access_formatter() -> None:
    """uvicorn.access は record.args の 5 要素タプルを展開する。フィルタが構造を壊さないこと。"""
    from uvicorn.logging import AccessFormatter

    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:1",
            "GET",
            "/api/v1/health?token=sk_live_ABC123",
            "1.1",
            200,
        ),  # pragma: allowlist secret  # noqa: E501
        None,
    )
    assert SecretMaskFilter().filter(record) is True
    assert isinstance(record.args, tuple) and len(record.args) == 5
    text = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record)
    assert "sk_live_ABC123" not in text
    assert "200" in text and "GET" in text


def test_ut_sec_01_setup_logging_attaches_filter_to_all_handlers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = logging.getLogger()
    setup_logging(logging.INFO, extra_secrets=["tok-abcdef"])
    for handler in root.handlers:
        assert any(isinstance(fl, SecretMaskFilter) for fl in handler.filters), handler
    # 実際にハンドラを通した出力が潰れている
    import io

    stream = io.StringIO()
    h = logging.StreamHandler(stream)
    root.addHandler(h)
    try:
        setup_logging(logging.INFO, extra_secrets=["tok-abcdef"])
        logging.getLogger("app.x").info("using tok-abcdef and sk_live_123")
    finally:
        root.removeHandler(h)
    text = stream.getvalue()
    assert "tok-abcdef" not in text and "sk_live_123" not in text
