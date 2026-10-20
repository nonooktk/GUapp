"""メールアダプタ（IF-02。DS-PRC-014-1 手順 7、設計仕様書 P2 追補b 4.10・DS-DEC-89）。

P1 は `OutboxMailAdapter`: 送信せず `apps/api/.mail-outbox/` に本文を書く
（ディレクトリは gitignore 済み。無ければ作る）。ログには種別とマスク済みメールだけを出す
（規定 §7「ログに個人情報を記録しない」）。例外は呼び手（注文サービス）が握って注文を成立させる。

本番（`APP_ENV=production`）は `LogOnlyMailAdapter`: 宛先・氏名・住所・リンクを含む本文を
ファイルに残さず、ログに種別（注文確認は注文番号）だけを 1 行出す（セキュリティ強化 S10）。
実送信は P2-c（ADR-0006 の削る順番の①）。

P2-b でメール種別を 5 つ足した（担当レーン: A が部品を用意し、呼び出しは B・C）。

| メソッド                  | 呼び出し元                              | 担当 |
| ------------------------- | --------------------------------------- | ---- |
| `send_order_confirmation` | DS-PRC-014-1 手順 7（店舗受け取りは本文を分ける） | C |
| `send_email_verification` | DS-PRC-030（後処理）                    | B    |
| `send_password_reset`     | DS-PRC-034（後処理）                    | B    |
| `send_account_locked`     | DS-PRC-032 手順 5（後処理）             | B    |
| `send_account_exists`     | DS-PRC-030（後処理）                    | B    |
| `send_restock_notice`     | DS-PRC-007a `notify_restock`            | C    |

「後処理」は FastAPI の `BackgroundTasks` で、応答を返したあとに実行する。例外は握り、
種別とマスク済みのメールだけをログに出す（`safe_send`）。応答や DB の結果には影響させない。

共通の取り決め（設計仕様書 4.10）:
- リンクのホストは環境変数 `PUBLIC_WEB_BASE_URL`（リクエストの `Host` は使わない）。
  リンクは呼び出し側が `build_public_url` で作って引数に渡す。
- 開発環境の outbox のファイル名は `<種別>-<yyyymmddHHMMSS>-<乱数 6 文字>.txt`。宛先やトークンを
  ファイル名に入れない（Windows のファイル名の制約と個人情報の露出の両方を避ける）。
  注文確認だけは従来どおり `<注文番号>.txt`。
- テストは `get_mail_adapter` を `dependency_overrides` で記録用アダプタに差し替える
  （`tests/recording_mail.py`）。
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.errors import internal_error
from app.schemas.order import OrderOut

logger = logging.getLogger("app.adapters.mail")

# apps/api/.mail-outbox
DEFAULT_OUTBOX_DIR = Path(__file__).resolve().parents[2] / ".mail-outbox"

# メール種別（outbox のファイル名・ログ・記録用アダプタの `kind` に使う）
KIND_ORDER_CONFIRMATION = "order_confirmation"
KIND_EMAIL_VERIFICATION = "email_verification"
KIND_PASSWORD_RESET = "password_reset"
KIND_ACCOUNT_LOCKED = "account_locked"
KIND_ACCOUNT_EXISTS = "account_exists"
KIND_RESTOCK_NOTICE = "restock_notice"


def mask_email(email: str) -> str:
    """`test@example.com` → `t***@example.com`。形が崩れていれば全部隠す。"""
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"


def build_public_url(path: str) -> str:
    """メールのリンクを作る（`{PUBLIC_WEB_BASE_URL}{path}`）。

    リクエストの `Host` ヘッダは使わない（DS-DEC-75。reset poisoning の防止）。
    `PUBLIC_WEB_BASE_URL` が未設定ならリンクを含むメールを送る処理を 500 にする
    （設定漏れを黙って許さない。設計仕様書 8.1）。`path` は `/` で始め、クエリを含んでよい。

    担当レーン: A（部品）。使うのは B（確認 `/verify-email?token=…`・再設定
    `/password-reset/confirm?token=…`）と C（再入荷 `/products/<id>`）。
    """
    base = get_settings().PUBLIC_WEB_BASE_URL.strip().rstrip("/")
    if not base:
        logger.error("PUBLIC_WEB_BASE_URL が未設定です（リンクを含むメールを作れません）")
        raise internal_error()
    if not path.startswith("/"):
        raise ValueError("path は '/' で始めてください")
    return f"{base}{path}"


class MailAdapter(Protocol):
    async def send_order_confirmation(self, order: OrderOut) -> None: ...

    async def send_email_verification(self, to: str, name: str, link: str) -> None:
        """確認リンク（24 時間有効）。心当たりがなければ無視してよい。"""
        ...

    async def send_password_reset(self, to: str, name: str, link: str) -> None:
        """再設定リンク（1 時間有効）。心当たりがなければ無視してよい。"""
        ...

    async def send_account_locked(self, to: str, name: str) -> None:
        """ログインの失敗が続いたため 15 分間ログインを止めた。再設定を勧める。"""
        ...

    async def send_account_exists(self, to: str) -> None:
        """すでに登録されている。パスワードを忘れた場合は再設定できる。"""
        ...

    async def send_restock_notice(
        self, to: str, product_name: str, color: str, size: str, url: str
    ) -> None:
        """再入荷した商品の名前・色・サイズと商品ページのリンク。"""
        ...


async def safe_send(
    kind: str, to: str, send: Callable[..., Awaitable[None]], *args: Any, **kwargs: Any
) -> None:
    """「後処理」用の送信ラッパー。例外を握り、種別とマスク済みのメールだけをログに出す。

    使い方（B・C）::

        background.add_task(
            safe_send, KIND_EMAIL_VERIFICATION, email,
            mail.send_email_verification, email, name, link,
        )

    応答や DB の結果には影響させない（設計仕様書 4.10）。リンク・トークン・本文は
    ログに出さない（例外のメッセージも出さず、型名だけを出す）。
    担当レーン: A（部品）。
    """
    try:
        await send(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001  後処理の失敗は応答に影響させない
        logger.warning(
            "メール送信に失敗しました kind=%s to=%s error=%s",
            kind,
            mask_email(to),
            type(exc).__name__,
        )


# ── 本文の組み立て ─────────────────────────────────────────────────────────────


def render_order_confirmation(order: OrderOut) -> str:
    is_store = order.receive_method == "store"
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
    ]
    if is_store:
        # 店舗受け取り（DS-PRC-014-3 手順 7）。受け取り方法として店舗名・住所と受け取りコードを書く
        store_name = order.store.name if order.store else ""
        store_address = order.store.address if order.store else order.ship_address
        lines += ["■ 受け取り店舗", store_name, store_address, ""]
        if order.pickup_code:
            lines += [
                "■ 受け取りコード",
                f"{order.pickup_code}",
                "店舗でこのコードをお伝えください。",
                "",
            ]
        lines += [
            "■ 受け取る方",
            f"{order.ship_name}",
            f"TEL {order.ship_phone}",
            "",
            "受け取り方法: 店舗受け取り",
        ]
    else:
        lines += [
            "■ お届け先",
            f"{order.ship_name}",
            f"〒{order.ship_postal_code}",
            f"{order.ship_address}",
            f"TEL {order.ship_phone}",
            "",
            "受け取り方法: 配送",
        ]
    lines += ["支払い方法: クレジットカード", ""]
    return "\n".join(lines)


def render_email_verification(to: str, name: str, link: str) -> str:
    return "\n".join(
        [
            "件名: 【GU】メールアドレスの確認",
            f"宛先: {to}",
            "",
            f"{name} 様",
            "",
            "会員登録ありがとうございます。次のリンクを開き、画面のボタンを押して",
            "メールアドレスの確認を完了してください（24 時間有効）。",
            link,
            "",
            "心当たりがない場合は、このメールを無視してください。",
            "",
        ]
    )


def render_password_reset(to: str, name: str, link: str) -> str:
    return "\n".join(
        [
            "件名: 【GU】パスワード再設定のご案内",
            f"宛先: {to}",
            "",
            f"{name} 様",
            "",
            "パスワードの再設定を受け付けました。次のリンクから新しいパスワードを",
            "設定してください（1 時間有効、1 回限り）。",
            link,
            "",
            "心当たりがない場合は、このメールを無視してください。",
            "",
        ]
    )


def render_account_locked(to: str, name: str) -> str:
    return "\n".join(
        [
            "件名: 【GU】ログインを一時的に止めました",
            f"宛先: {to}",
            "",
            f"{name} 様",
            "",
            "ログインの失敗が続いたため、15 分間ログインを止めています。",
            "心当たりがない場合は、パスワードの再設定をおすすめします。",
            "",
        ]
    )


def render_account_exists(to: str) -> str:
    return "\n".join(
        [
            "件名: 【GU】すでにご登録されています",
            f"宛先: {to}",
            "",
            "このメールアドレスは、すでに会員登録されています。",
            "パスワードを忘れた場合は、ログイン画面からパスワードを再設定できます。",
            "心当たりがない場合は、このメールを無視してください。",
            "",
        ]
    )


def render_restock_notice(to: str, product_name: str, color: str, size: str, url: str) -> str:
    return "\n".join(
        [
            f"件名: 【GU】再入荷のお知らせ（{product_name}）",
            f"宛先: {to}",
            "",
            "お申し込みいただいた商品が再入荷しました。",
            f"商品: {product_name} / {color} / {size}",
            url,
            "",
        ]
    )


# ── アダプタ ───────────────────────────────────────────────────────────────────


class OutboxMailAdapter:
    """ファイル出力のメールアダプタ（開発・テスト）。"""

    def __init__(self, outbox_dir: Path = DEFAULT_OUTBOX_DIR) -> None:
        self._dir = outbox_dir

    def _write(self, kind: str, body: str) -> Path:
        """`<種別>-<yyyymmddHHMMSS>-<乱数 6 文字>.txt` に書く（宛先・トークンは入れない）。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        path = self._dir / f"{kind}-{stamp}-{secrets.token_hex(3)}.txt"
        path.write_text(body, encoding="utf-8")
        return path

    def _log(self, kind: str, to: str) -> None:
        logger.info("メールを outbox に書きました kind=%s to=%s", kind, mask_email(to))

    async def send_order_confirmation(self, order: OrderOut) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{order.order_number}.txt"
        path.write_text(render_order_confirmation(order), encoding="utf-8")
        logger.info(
            "注文確認メールを outbox に書きました order=%s to=%s",
            order.order_number,
            mask_email(order.guest_email),
        )

    async def send_email_verification(self, to: str, name: str, link: str) -> None:
        self._write(KIND_EMAIL_VERIFICATION, render_email_verification(to, name, link))
        self._log(KIND_EMAIL_VERIFICATION, to)

    async def send_password_reset(self, to: str, name: str, link: str) -> None:
        self._write(KIND_PASSWORD_RESET, render_password_reset(to, name, link))
        self._log(KIND_PASSWORD_RESET, to)

    async def send_account_locked(self, to: str, name: str) -> None:
        self._write(KIND_ACCOUNT_LOCKED, render_account_locked(to, name))
        self._log(KIND_ACCOUNT_LOCKED, to)

    async def send_account_exists(self, to: str) -> None:
        self._write(KIND_ACCOUNT_EXISTS, render_account_exists(to))
        self._log(KIND_ACCOUNT_EXISTS, to)

    async def send_restock_notice(
        self, to: str, product_name: str, color: str, size: str, url: str
    ) -> None:
        self._write(KIND_RESTOCK_NOTICE, render_restock_notice(to, product_name, color, size, url))
        self._log(KIND_RESTOCK_NOTICE, to)


class LogOnlyMailAdapter:
    """本番用。送信内容を保存せず、ログに種別（注文確認は注文番号）だけを出す。

    宛先・リンク・トークンは出さない（DS-DEC-66・89）。
    """

    async def send_order_confirmation(self, order: OrderOut) -> None:
        logger.info("注文確認メールの送信対象 order=%s", order.order_number)

    async def send_email_verification(self, to: str, name: str, link: str) -> None:
        logger.info("メールの送信対象 kind=%s", KIND_EMAIL_VERIFICATION)

    async def send_password_reset(self, to: str, name: str, link: str) -> None:
        logger.info("メールの送信対象 kind=%s", KIND_PASSWORD_RESET)

    async def send_account_locked(self, to: str, name: str) -> None:
        logger.info("メールの送信対象 kind=%s", KIND_ACCOUNT_LOCKED)

    async def send_account_exists(self, to: str) -> None:
        logger.info("メールの送信対象 kind=%s", KIND_ACCOUNT_EXISTS)

    async def send_restock_notice(
        self, to: str, product_name: str, color: str, size: str, url: str
    ) -> None:
        logger.info("メールの送信対象 kind=%s", KIND_RESTOCK_NOTICE)


def get_mail_adapter() -> MailAdapter:
    """本番は `LogOnlyMailAdapter`、それ以外（開発・テスト）は従来の Outbox。"""
    if get_settings().is_production:
        return LogOnlyMailAdapter()
    return OutboxMailAdapter()
