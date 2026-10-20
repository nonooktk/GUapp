"""再入荷通知（DS-API-007 申込・DS-PRC-007a 送信。設計仕様書 P2 追補b 4.5・4.8・DS-DEC-80）。

- 申込 `register`: 在庫 0 の公開商品のバリエーションだけ。同じメールの未通知は 10 件まで
- 送信 `notify_restock`: 呼び出し元は P2-c の管理画面の在庫更新で、在庫が 0 から正の値に変わった
  更新を COMMIT した**あと**で呼ぶ。P2-b では IT と CLI（`python -m app.restock_notify`）で確かめる
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.mail import MailAdapter, build_public_url, mask_email
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.session import CurrentMember
from app.repositories import restock as restock_repo
from app.services.email_normalize import is_email_domain_allowed

logger = logging.getLogger("app.services.restock")

# 同じメールの未通知の申込の上限（今回の variant を除く。DS-PRC-007 手順 3）
PENDING_LIMIT = 10

AUDIT_RESTOCK_NOTIFIED = "restock.notified"
AUDIT_RESTOCK_MAIL_FAILED = "restock.mail_failed"


def is_over_limit(pending_other_than_this_variant: int) -> bool:
    """今回の variant を除いた未通知の件数が上限に達していれば真（新規は 10 件目まで）。"""
    return pending_other_than_this_variant >= PENDING_LIMIT


def check_email_domain(email: str) -> None:
    """`DEMO_EMAIL_DOMAINS` が設定されていれば、ドメインの完全一致だけ許す（DS-DEC-88）。

    未設定は制限なし。サブドメインは不一致。外れたら 422 `unsupported_value`（field `email`）。
    `email` は正規化済み（小文字）。
    """
    if not is_email_domain_allowed(email, get_settings().demo_email_domains):
        raise AppError(422, "unsupported_value", field="email")


async def register(
    session: AsyncSession, *, variant_id: int, email: str, member: CurrentMember | None
) -> None:
    """DS-PRC-007。入力検査（variant_id の範囲・メールの形）は Pydantic 済み。"""
    # 1. DEMO_EMAIL_DOMAINS
    check_email_domain(email)

    # 2. variant を公開商品の分だけ検索（無ければ 404）。在庫があれば 409
    variant = await restock_repo.get_published_variant(session, variant_id)
    if variant is None:
        raise AppError(404, "not_found")
    if variant.stock > 0:
        raise AppError(409, "in_stock")

    # 3. 同じメールの未通知が 10 件以上（今回の variant を除く）なら 422
    pending = await restock_repo.count_pending_for_email(
        session, email, exclude_variant_id=variant_id
    )
    if is_over_limit(pending):
        raise AppError(422, "limit_exceeded", field="email", limit=PENDING_LIMIT)

    # 4. 1 文で upsert（同時申込でも 1 行）
    await restock_repo.upsert_registration(
        session,
        variant_id=variant_id,
        email=email,
        member_id=member.id if member is not None else None,
    )
    await session.commit()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def notify_restock(session: AsyncSession, variant_id: int, *, mail: MailAdapter) -> int:
    """DS-PRC-007a。送信に成功した件数を返す。

    1. `variants.stock > 0` でなければ何もしない（0 を返す）
    2. 未通知の行を**先に確保**する（`notified_at` を入れて COMMIT）。そのあとで送る
       （至多 1 回。同じ variant への通知 2 本でも、送信の合計は申込の数に等しい）
    3. 行ごとに `send_restock_notice`。1 件の失敗は他の宛先に影響させず、`restock.mail_failed`
       （宛先は書かず件数のみ）を `audit_logs` に残す。例外は呼び出し元に伝えない
    4. 送信数を `audit_logs` に `restock.notified`（detail は件数）で記録する

    リンクのホストは `PUBLIC_WEB_BASE_URL`。未設定ならリンクを作れず `internal_error`（500）を
    投げる。確保の**前**に作るので、設定漏れで申込を使い切ることはない。
    """
    info = await restock_repo.get_variant_info(session, variant_id)
    if info is None or info.stock <= 0:
        await session.rollback()
        return 0
    url = build_public_url(f"/products/{info.product_id}")

    # 確保（排他ロック → notified_at 設定 → COMMIT）
    claimed = await restock_repo.claim_unnotified(session, variant_id, _utcnow())
    await session.commit()
    if not claimed:
        return 0

    sent = 0
    failed = 0
    for _id, email in claimed:
        try:
            await mail.send_restock_notice(email, info.product_name, info.color, info.size, url)
            sent += 1
        except Exception as exc:  # noqa: BLE001  1 件の失敗で他の宛先を止めない
            failed += 1
            logger.warning(
                "再入荷通知の送信に失敗 variant=%s to=%s (%s)",
                variant_id,
                mask_email(email),
                type(exc).__name__,
            )

    if failed:
        await restock_repo.insert_audit_log(
            session,
            action=AUDIT_RESTOCK_MAIL_FAILED,
            variant_id=variant_id,
            detail={"count": failed},
        )
    await restock_repo.insert_audit_log(
        session, action=AUDIT_RESTOCK_NOTIFIED, variant_id=variant_id, detail={"count": sent}
    )
    await session.commit()
    logger.info("再入荷通知 variant=%s 送信=%d 失敗=%d", variant_id, sent, failed)
    return sent
