"""ログイン試行の読み書き（DS-TBL-26 login_attempts。P2 追補b 4.8 DS-PRC-032・DS-DEC-70）。

ロック（メール単位）と IP 単位の制限の判定元。会員の有無に関係なく記録する（DS-DEC-71）。
`identifier` は正規化したメールの SHA-256（平文のメールを保存しない）。
数えるのは「失敗」かつ同じ `subject_type` かつ同じ識別子（または同じ IP）で、
`at > since`（直近 15 分）の行だけ。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginAttempt, SubjectType


async def count_failures_by_identifier(
    session: AsyncSession, subject_type: SubjectType, identifier: str, since: datetime
) -> int:
    """同じ識別子の失敗の件数（`at > since`）。"""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(
                    LoginAttempt.subject_type == subject_type,
                    LoginAttempt.identifier == identifier,
                    LoginAttempt.succeeded.is_(False),
                    LoginAttempt.at > since,
                )
            )
        ).scalar_one()
    )


async def count_failures_by_ip(
    session: AsyncSession, subject_type: SubjectType, ip: str, since: datetime
) -> int:
    """同じ IP の失敗の件数（`at > since`）。"""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(
                    LoginAttempt.subject_type == subject_type,
                    LoginAttempt.ip == ip,
                    LoginAttempt.succeeded.is_(False),
                    LoginAttempt.at > since,
                )
            )
        ).scalar_one()
    )


async def record(
    session: AsyncSession,
    subject_type: SubjectType,
    identifier: str,
    *,
    succeeded: bool,
    ip: str,
    at: datetime,
) -> None:
    """試行を 1 件記録する。"""
    session.add(
        LoginAttempt(
            subject_type=subject_type,
            identifier=identifier,
            succeeded=succeeded,
            ip=ip,
            at=at,
        )
    )
    await session.flush()


async def delete_failures_by_identifier(
    session: AsyncSession, subject_type: SubjectType, identifier: str
) -> None:
    """そのメールの失敗行を削除する（ログイン成功・パスワード再設定の確定。主キーで消す）。"""
    ids = (
        (
            await session.execute(
                select(LoginAttempt.id).where(
                    LoginAttempt.subject_type == subject_type,
                    LoginAttempt.identifier == identifier,
                    LoginAttempt.succeeded.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    if ids:
        await session.execute(delete(LoginAttempt).where(LoginAttempt.id.in_(ids)))


async def delete_older_than(session: AsyncSession, cutoff: datetime, *, limit: int) -> int:
    """`at < cutoff` の古い行を最大 `limit` 件削除する（DS-PRC-032 手順 8）。削除した件数を返す。

    MySQL は `IN (SELECT … LIMIT)` を直接は許さないので、導出テーブルを挟んで ID を拾う。
    """
    ids = (
        select(LoginAttempt.id)
        .where(LoginAttempt.at < cutoff)
        .order_by(LoginAttempt.id)
        .limit(limit)
    ).subquery()
    result = await session.execute(
        delete(LoginAttempt).where(LoginAttempt.id.in_(select(ids.c.id)))
    )
    return int(result.rowcount)
