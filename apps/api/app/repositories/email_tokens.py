"""メール確認・パスワード再設定のトークン（DS-TBL-27 email_tokens。設計仕様書 P2 追補b 4.8・5.2）。

DB には SHA-256 の 16 進（64 文字）だけを保存する。有効とは「`used_at` が NULL かつ
`expires_at > now`」。無効・期限切れ・使用済み・目的違いは区別しない（呼び手は 404）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailToken, EmailTokenPurpose


@dataclass(frozen=True, slots=True)
class EmailTokenRow:
    id: int
    member_id: int


async def insert_token(
    session: AsyncSession,
    *,
    member_id: int,
    purpose: EmailTokenPurpose,
    token_hash: str,
    expires_at: datetime,
) -> None:
    session.add(
        EmailToken(
            member_id=member_id,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=expires_at,
            used_at=None,
        )
    )
    await session.flush()


async def find_valid(
    session: AsyncSession,
    *,
    token_hash: str,
    purpose: EmailTokenPurpose,
    now: datetime,
    for_update: bool = False,
) -> EmailTokenRow | None:
    """有効なトークン 1 件。`for_update` で行を排他ロックする（同じトークンの同時確定を直列化）。"""
    stmt = select(EmailToken.id, EmailToken.member_id).where(
        EmailToken.token_hash == token_hash,
        EmailToken.purpose == purpose,
        EmailToken.used_at.is_(None),
        EmailToken.expires_at > now,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).first()
    return EmailTokenRow(id=row.id, member_id=row.member_id) if row is not None else None


async def mark_used(session: AsyncSession, token_id: int, at: datetime) -> int:
    """使用済みにする。未使用のときだけ更新し、影響行数（0 か 1）を返す。"""
    result = await session.execute(
        update(EmailToken)
        .where(EmailToken.id == token_id, EmailToken.used_at.is_(None))
        .values(used_at=at)
    )
    return int(result.rowcount)


async def invalidate_unused(
    session: AsyncSession, member_id: int, purpose: EmailTokenPurpose, at: datetime
) -> None:
    """同じ会員の未使用の同じ目的のトークンを使用済みにする（新しい要求で古いリンクを無効にする）。"""
    ids = (
        (
            await session.execute(
                select(EmailToken.id).where(
                    EmailToken.member_id == member_id,
                    EmailToken.purpose == purpose,
                    EmailToken.used_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if ids:
        await session.execute(update(EmailToken).where(EmailToken.id.in_(ids)).values(used_at=at))
