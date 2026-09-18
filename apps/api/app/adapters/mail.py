"""メールアダプタ（DS-PRC-014-1 手順 7）。

P1 は `OutboxMailAdapter`: 送信せず `apps/api/.mail-outbox/<order_number>.txt` に本文を書く
（ディレクトリは gitignore 済み。無ければ作る）。ログには注文番号とマスク済みメールだけを出す
（規定 §7「ログに個人情報を記録しない」）。例外は呼び手（注文サービス）が握って注文を成立させる。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from app.schemas.order import OrderOut

logger = logging.getLogger("app.adapters.mail")

# apps/api/.mail-outbox
DEFAULT_OUTBOX_DIR = Path(__file__).resolve().parents[2] / ".mail-outbox"


def mask_email(email: str) -> str:
    """`test@example.com` → `t***@example.com`。形が崩れていれば全部隠す。"""
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"


class MailAdapter(Protocol):
    async def send_order_confirmation(self, order: OrderOut) -> None: ...


def render_order_confirmation(order: OrderOut) -> str:
    lines = [
        f"件名: 【GU】ご注文ありがとうございます（注文番号 {order.order_number}）",
        f"宛先: {order.guest_email}",
        "",
        f"{order.ship_name} 様",
        "",
        "ご注文を受け付けました。",
        f"注文番号: {order.order_number}",
        f"注文日時: {order.ordered_at}",
        "",
        "■ ご注文内容",
    ]
    for item in order.items:
        lines.append(
            f"- {item.product_name} / {item.color} / {item.size}"
            f" × {item.quantity} = ¥{item.line_total:,}（単価 ¥{item.unit_price:,}）"
        )
    lines += [
        "",
        f"小計: ¥{order.subtotal:,}",
        f"送料: ¥{order.shipping_fee:,}",
        f"合計: ¥{order.total:,}（うち消費税 ¥{order.tax_included:,}）",
        "",
        "■ お届け先",
        f"{order.ship_name}",
        f"〒{order.ship_postal_code}",
        f"{order.ship_address}",
        f"TEL {order.ship_phone}",
        "",
        "受け取り方法: 配送",
        "支払い方法: クレジットカード",
        "",
    ]
    return "\n".join(lines)


class OutboxMailAdapter:
    """ファイル出力のメールアダプタ。"""

    def __init__(self, outbox_dir: Path = DEFAULT_OUTBOX_DIR) -> None:
        self._dir = outbox_dir

    async def send_order_confirmation(self, order: OrderOut) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{order.order_number}.txt"
        path.write_text(render_order_confirmation(order), encoding="utf-8")
        logger.info(
            "注文確認メールを outbox に書きました order=%s to=%s",
            order.order_number,
            mask_email(order.guest_email),
        )


def get_mail_adapter() -> MailAdapter:
    return OutboxMailAdapter()
