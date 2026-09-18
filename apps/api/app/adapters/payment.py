"""決済アダプタ（DS-PRC-014-1 手順 5・DS-DEC-26）。

P1 は `StubPaymentAdapter`。結果は環境変数 `PAYMENT_STUB_RESULT=ok|ng`（未設定は ok）。
ルーターは `Depends(get_payment_adapter)` で受け取るので、テストは
`app.dependency_overrides[get_payment_adapter]` で NG を注入できる（IT-014-06）。
"""

from __future__ import annotations

import logging
from typing import Literal, Protocol

from fastapi import Depends

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.adapters.payment")

PaymentResultCode = Literal["ok", "ng"]


class PaymentAdapter(Protocol):
    provider: str

    async def authorize(self, order_number: str, amount: int) -> PaymentResultCode: ...


class StubPaymentAdapter:
    """常に固定の結果を返すスタブ。カード情報は一切扱わない。"""

    provider = "stub"

    def __init__(self, result: PaymentResultCode | None) -> None:
        self._result: PaymentResultCode = result or "ok"

    async def authorize(self, order_number: str, amount: int) -> PaymentResultCode:
        logger.info(
            "決済スタブ authorize order=%s amount=%d result=%s", order_number, amount, self._result
        )
        return self._result


def get_payment_adapter(settings: Settings = Depends(get_settings)) -> PaymentAdapter:
    return StubPaymentAdapter(settings.PAYMENT_STUB_RESULT)
