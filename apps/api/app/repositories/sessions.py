"""セッションの読み書き（DS-TBL-03 sessions。設計仕様書 P2 追補b 4.8 DS-PRC-032・5.6・7.3）。

`sessions` に外部キーは無い（`subject_id` は members／staff の両方を指すため）。
文の順序は `members` → `sessions` → `login_attempts`（ログインと再設定の確定で揃える。5.6）。
削除は範囲条件を避け、主キーまたは UNIQUE の `token_hash` で行う（ギャップロックを避ける）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthSession, SubjectType

# 会員ごとの同時セッションの上限（DS-DEC-72）
MAX_SESSIONS_PER_MEMBER = 10


def ids_to_evict(active_ids_oldest_first: Sequence[int], max_sessions: int) -> list[int]:
    """新しいセッションを 1 件足したあと `max_sessions` 件に収めるために消す ID（古い順）。

    9 件なら 0 件、10 件なら最古の 1 件、12 件なら最古の 3 件。
    """
    keep = max_sessions - 1
    excess = len(active_ids_oldest_first) - keep
    return list(active_ids_oldest_first[:excess]) if excess > 0 else []


async def delete_by_token_hash(session: AsyncSession, token_hash: str) -> int:
    """会員のセッション 1 行を `token_hash` で削除する（影響行数を返す）。冪等。"""
    result = await session.execute(
        delete(AuthSession).where(
            AuthSession.token_hash == token_hash,
            AuthSession.subject_type == SubjectType.member,
        )
    )
    return int(result.rowcount)


async def delete_expired_for_member(session: AsyncSession, member_id: int, now: datetime) -> None:
    """この会員の期限切れの行を削除する（主キーで消す）。"""
    ids = (
        (
            await session.execute(
                select(AuthSession.id).where(
                    AuthSession.subject_type == SubjectType.member,
                    AuthSession.subject_id == member_id,
                    AuthSession.expires_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    if ids:
        await session.execute(delete(AuthSession).where(AuthSession.id.in_(ids)))


async def evict_oldest_for_new_session(
    session: AsyncSession,
    member_id: int,
    now: datetime,
    *,
    max_sessions: int = MAX_SESSIONS_PER_MEMBER,
) -> int:
    """有効なセッションが上限に達していれば、古い順に消して 9 件にする。消した件数を返す。"""
    active = (
        (
            await session.execute(
                select(AuthSession.id)
                .where(
                    AuthSession.subject_type == SubjectType.member,
                    AuthSession.subject_id == member_id,
                    AuthSession.expires_at > now,
                )
                .order_by(AuthSession.expires_at, AuthSession.id)
            )
        )
        .scalars()
        .all()
    )
    evict = ids_to_evict(active, max_sessions)
    if evict:
        await session.execute(delete(AuthSession).where(AuthSession.id.in_(evict)))
    return len(evict)


async def insert_session(
    session: AsyncSession,
    *,
    member_id: int,
    token_hash: str,
    now: datetime,
    expires_at: datetime,
) -> None:
    """新しいセッションを INSERT する。`last_seen_at` は作成時刻のまま（更新しない）。"""
    session.add(
        AuthSession(
            token_hash=token_hash,
            subject_type=SubjectType.member,
            subject_id=member_id,
            expires_at=expires_at,
            last_seen_at=now,
        )
    )
    await session.flush()


async def delete_all_for_member(session: AsyncSession, member_id: int) -> int:
    """この会員のセッションをすべて削除する（パスワード再設定の確定。DS-DEC-75）。"""
    ids = (
        (
            await session.execute(
                select(AuthSession.id).where(
                    AuthSession.subject_type == SubjectType.member,
                    AuthSession.subject_id == member_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if ids:
        await session.execute(delete(AuthSession).where(AuthSession.id.in_(ids)))
    return len(ids)


async def count_active_for_member(session: AsyncSession, member_id: int, now: datetime) -> int:
    """有効なセッションの件数（テスト・検証用）。"""
    rows = (
        await session.execute(
            select(AuthSession.id).where(
                AuthSession.subject_type == SubjectType.member,
                AuthSession.subject_id == member_id,
                AuthSession.expires_at > now,
            )
        )
    ).all()
    return len(rows)
