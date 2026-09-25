"""決済・メールアダプタ（スタブ切替・マスク済みメール）とレート制限器の単体テスト。DB 不要。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.mail import OutboxMailAdapter, mask_email
from app.adapters.payment import StubPaymentAdapter, get_payment_adapter
from app.core.config import get_settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.schemas.order import OrderItemOut, OrderOut


@pytest.mark.parametrize(
    ("email", "masked"),
    [
        ("test@example.com", "t***@example.com"),
        ("a@example.com", "a***@example.com"),
        ("taro.yamada@sub.example.co.jp", "t***@sub.example.co.jp"),
        ("broken", "***"),
        ("", "***"),
    ],
)
def test_ut_mail_mask_email(email: str, masked: str) -> None:
    assert mask_email(email) == masked


def _order_out() -> OrderOut:
    return OrderOut(
        order_number="GU-260918-ABCDEFGH",
        status="accepted",
        items=[
            OrderItemOut(
                product_name="テスト商品",
                color="黒",
                size="M",
                unit_price=1990,
                quantity=2,
                line_total=3980,
            )
        ],
        subtotal=3980,
        shipping_fee=550,
        total=4530,
        tax_included=411,
        tax_rate="0.10",
        ship_name="テスト 太郎",
        ship_postal_code="1000001",
        ship_address="東京都千代田区千代田1-1",
        ship_phone="09012345678",
        guest_email="test@example.com",
        receive_method="delivery",
        payment_method="card",
        ordered_at="2026-09-18T00:00:00Z",
    )


async def test_ut_mail_outbox_writes_file_and_log_is_masked(tmp_path: Path, caplog) -> None:
    adapter = OutboxMailAdapter(tmp_path / "outbox")
    with caplog.at_level("INFO", logger="app.adapters.mail"):
        await adapter.send_order_confirmation(_order_out())
    path = tmp_path / "outbox" / "GU-260918-ABCDEFGH.txt"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "GU-260918-ABCDEFGH" in text and "4,530" in text and "テスト商品" in text
    # ログには注文番号とマスク済みメールだけ（生のメールは出ない）
    assert "t***@example.com" in caplog.text
    assert "test@example.com" not in caplog.text


async def test_ut_payment_stub_default_ok_and_switch_ng(app_env) -> None:
    assert await StubPaymentAdapter(None).authorize("GU-260918-ABCDEFGH", 100) == "ok"
    assert await StubPaymentAdapter("ok").authorize("GU-260918-ABCDEFGH", 100) == "ok"
    assert await StubPaymentAdapter("ng").authorize("GU-260918-ABCDEFGH", 100) == "ng"

    app_env(PAYMENT_STUB_RESULT="ng")
    adapter = get_payment_adapter(get_settings())
    assert await adapter.authorize("GU-260918-ABCDEFGH", 100) == "ng"
    app_env()
    assert await get_payment_adapter(get_settings()).authorize("x", 1) == "ok"


def test_ut_rate_limit_100_ok_101_limited_with_retry_after() -> None:
    now = [1000.0]
    limiter = SlidingWindowRateLimiter(limit=100, window_seconds=3600, clock=lambda: now[0])
    for _ in range(100):
        assert limiter.hit("10.0.0.1") is None
    retry = limiter.hit("10.0.0.1")
    assert retry is not None and 1 <= retry <= 3600
    # 別 IP は別カウント
    assert limiter.hit("10.0.0.2") is None
    # 窓が過ぎれば復活
    now[0] += 3600.1
    assert limiter.hit("10.0.0.1") is None
    limiter.reset()
    assert limiter.hit("10.0.0.2") is None
