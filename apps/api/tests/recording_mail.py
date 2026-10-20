"""記録用メールアダプタ（テスト設計書 P2 追補b 1 章 #3・設計仕様書 4.10）。

結合テストでは `get_mail_adapter` を `dependency_overrides` でこれに差し替え、送信した種別・
宛先・引数（リンクなど）をメモリで読む。実ファイルは書かない。

    def test_xxx(recording_mail, it_app):
        recording_mail.install(it_app)
        ...
        sent = recording_mail.of_kind("email_verification")
        assert sent[0].to == "a@example.com" and sent[0].args["link"].startswith("http")

担当レーン: A（部品）。B・C のテストが使う。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI

from app.adapters.mail import (
    KIND_ACCOUNT_EXISTS,
    KIND_ACCOUNT_LOCKED,
    KIND_EMAIL_VERIFICATION,
    KIND_ORDER_CONFIRMATION,
    KIND_PASSWORD_RESET,
    KIND_RESTOCK_NOTICE,
    get_mail_adapter,
)
from app.schemas.order import OrderOut


@dataclass(frozen=True)
class SentMail:
    kind: str
    to: str
    args: dict[str, Any] = field(default_factory=dict)


class RecordingMailAdapter:
    """`MailAdapter`（Protocol）の全メソッドを備え、呼び出しを `sent` に積む。"""

    def __init__(self) -> None:
        self.sent: list[SentMail] = []
        # 送信を失敗させたいテスト用。真なら全メソッドが RuntimeError を投げる（記録はしない）
        self.fail = False

    def install(self, app: FastAPI) -> RecordingMailAdapter:
        """`app` の `get_mail_adapter` をこのアダプタに差し替える。"""
        app.dependency_overrides[get_mail_adapter] = lambda: self
        return self

    def of_kind(self, kind: str) -> list[SentMail]:
        return [m for m in self.sent if m.kind == kind]

    def clear(self) -> None:
        self.sent.clear()

    def _record(self, kind: str, to: str, **args: Any) -> None:
        if self.fail:
            raise RuntimeError("recording mail adapter: 送信失敗を再現")
        self.sent.append(SentMail(kind=kind, to=to, args=args))

    async def send_order_confirmation(self, order: OrderOut) -> None:
        self._record(KIND_ORDER_CONFIRMATION, order.guest_email, order=order)

    async def send_email_verification(self, to: str, name: str, link: str) -> None:
        self._record(KIND_EMAIL_VERIFICATION, to, name=name, link=link)

    async def send_password_reset(self, to: str, name: str, link: str) -> None:
        self._record(KIND_PASSWORD_RESET, to, name=name, link=link)

    async def send_account_locked(self, to: str, name: str) -> None:
        self._record(KIND_ACCOUNT_LOCKED, to, name=name)

    async def send_account_exists(self, to: str) -> None:
        self._record(KIND_ACCOUNT_EXISTS, to)

    async def send_restock_notice(
        self, to: str, product_name: str, color: str, size: str, url: str
    ) -> None:
        self._record(
            KIND_RESTOCK_NOTICE, to, product_name=product_name, color=color, size=size, url=url
        )
