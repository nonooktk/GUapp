"""再入荷通知の申込・通知対象の読み書き（DS-TBL-20 restock_notifications。DS-PRC-007・007a）。

- 申込は `INSERT … ON DUPLICATE KEY UPDATE` の 1 文（UNIQUE `(variant_id, email)`）。
  同時申込でも 1 行
- 通知対象は `SELECT … FOR UPDATE` で行を確保してから `notified_at` を入れる
  （至多 1 回。DS-DEC-80）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActorType, AuditLog, Product, RestockNotification, Variant
from app.repositories.products import published_filter


@dataclass(frozen=True)
class VariantStock:
    variant_id: int
    stock: int


async def get_published_variant(session: AsyncSession, variant_id: int) -> VariantStock | None:
    """公開商品のバリエーションだけ（非公開商品・存在しない variant は None → 404）。"""
    row = (
        await session.execute(
            select(Variant.id, Variant.stock)
            .join(Product, Product.id == Variant.product_id)
            .where(Variant.id == variant_id, published_filter())
        )
    ).first()
    return VariantStock(variant_id=row.id, stock=int(row.stock)) if row is not None else None


async def count_pending_for_email(
    session: AsyncSession, email: str, *, exclude_variant_id: int | None = None
) -> int:
    """同じメールの未通知（`notified_at` が NULL）の申込件数。`exclude_variant_id` は数えない。"""
    stmt = (
        select(func.count())
        .select_from(RestockNotification)
        .where(RestockNotification.email == email, RestockNotification.notified_at.is_(None))
    )
    if exclude_variant_id is not None:
        stmt = stmt.where(RestockNotification.variant_id != exclude_variant_id)
    return int((await session.execute(stmt)).scalar_one())


async def upsert_registration(
    session: AsyncSession, *, variant_id: int, email: str, member_id: int | None
) -> None:
    """申込を 1 文で登録する。再申込は `notified_at` を NULL に戻し、通知済みを再び有効にする。

    `member_id` は、今回の値があれば上書きし、無ければ既存の値を残す
    （`COALESCE(VALUES(member_id), member_id)`）。MySQL 専用の構文。
    """
    stmt = mysql_insert(RestockNotification).values(
        variant_id=variant_id, email=email, member_id=member_id
    )
    stmt = stmt.on_duplicate_key_update(
        notified_at=None,
        member_id=func.coalesce(stmt.inserted.member_id, RestockNotification.member_id),
    )
    await session.execute(stmt)


# ── 通知の送信（DS-PRC-007a）──────────────────────────────────────────────────


@dataclass(frozen=True)
class VariantInfo:
    variant_id: int
    stock: int
    product_id: int
    product_name: str
    color: str
    size: str


async def get_variant_info(session: AsyncSession, variant_id: int) -> VariantInfo | None:
    row = (
        await session.execute(
            select(Variant.id, Variant.stock, Variant.color, Variant.size, Product.id, Product.name)
            .join(Product, Product.id == Variant.product_id)
            .where(Variant.id == variant_id)
        )
    ).first()
    if row is None:
        return None
    return VariantInfo(
        variant_id=row[0],
        stock=int(row[1]),
        color=row[2],
        size=row[3],
        product_id=row[4],
        product_name=row[5],
    )


async def claim_unnotified(
    session: AsyncSession, variant_id: int, now: datetime
) -> list[tuple[int, str]]:
    """未通知の行を先に確保し（`notified_at` を入れ）、(id, email) を返す。

    `SELECT … FOR UPDATE` で行を排他ロックしてから `notified_at` を設定する。同じ variant への
    通知 2 本は直列化され、後続は COMMIT 済みの `notified_at` を見て 0 行になる（二重送信なし）。
    呼び手は戻ったあとすぐ COMMIT し、そのあとでメールを送る（至多 1 回。重複送信より
    取りこぼしを選ぶ。取りこぼしは再申込できる）。
    """
    rows = (
        await session.execute(
            select(RestockNotification.id, RestockNotification.email)
            .where(
                and_(
                    RestockNotification.variant_id == variant_id,
                    RestockNotification.notified_at.is_(None),
                )
            )
            .order_by(RestockNotification.id)
            .with_for_update()
        )
    ).all()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    await session.execute(
        update(RestockNotification)
        .where(RestockNotification.id.in_(ids), RestockNotification.notified_at.is_(None))
        .values(notified_at=now)
    )
    return [(r[0], r[1]) for r in rows]


async def insert_audit_log(
    session: AsyncSession, *, action: str, variant_id: int, detail: dict | None = None
) -> None:
    """`restock.notified`・`restock.mail_failed`。detail にメール・氏名を入れない。"""
    session.add(
        AuditLog(
            actor_type=ActorType.system,
            actor_id=None,
            action=action,
            target_type="variant",
            target_id=str(variant_id),
            detail=detail,
        )
    )
    await session.flush()
