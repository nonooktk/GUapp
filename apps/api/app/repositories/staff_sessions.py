"""管理者のセッションの読み書き（DS-TBL-03 sessions の `subject_type=staff`）。

設計仕様書 P2 追補c 5.3・7.3・DS-PRC-050・050b・DS-DEC-108。

担当レーン: C-1（C-2・C-3 は使わない）。会員用の `repositories/sessions.py`（P2-b）は
`subject_type=member` 固定で、設計書 11.2 は「`subject_type` を引数に取らないなら C-1 が足す」と
していたが、P2-b のファイルを変えない方針のため、管理者用を別モジュールにした
（会員側の挙動は一切変わらない）。

- `sessions` に外部キーは無い。削除は範囲条件を避け、主キーまたは UNIQUE の `token_hash` で行う
  （ギャップロックを避ける。5.6）
- 管理者の期限は作成から 8 時間の固定。同時セッションは 3 件まで（古い順に削除）
- 文の順序は `staff` → `sessions` → `login_attempts` → `audit_logs`（5.6）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthSession, SubjectType
from app.repositories.sessions import ids_to_evict

# 管理者ごとの同時セッションの上限（DS-DEC-108）
MAX_SESSIONS_PER_STAFF = 3


@dataclass(frozen=True, slots=True)
class SessionRow:
    """有効なセッション 1 行の値のコピー。"""

    subject_type: SubjectType
    subject_id: int


async def find_active_by_token_hash(
    session: AsyncSession, token_hash: str, now: datetime
) -> SessionRow | None:
    """`subject_type` を問わず、`expires_at > now` の行を 1 件（DS-PRC-050b 手順 2）。"""
    row = (
        await session.execute(
            select(AuthSession.subject_type, AuthSession.subject_id).where(
                AuthSession.token_hash == token_hash, AuthSession.expires_at > now
            )
        )
    ).first()
    if row is None:
        return None
    return SessionRow(subject_type=row.subject_type, subject_id=int(row.subject_id))


async def find_staff_by_token_hash(session: AsyncSession, token_hash: str) -> SessionRow | None:
    """管理者のセッションの行（期限は問わない。ログアウトで消すために探す）。会員の行は返さない。"""
    row = (
        await session.execute(
            select(AuthSession.subject_type, AuthSession.subject_id).where(
                AuthSession.token_hash == token_hash,
                AuthSession.subject_type == SubjectType.staff,
            )
        )
    ).first()
    if row is None:
        return None
    return SessionRow(subject_type=row.subject_type, subject_id=int(row.subject_id))


async def delete_by_token_hash(session: AsyncSession, token_hash: str) -> int:
    """管理者のセッション 1 行を `token_hash` で削除する（影響行数を返す）。冪等。

    会員の行は消さない（`subject_type=staff` の行だけ。DS-API-050a）。
    """
    result = await session.execute(
        delete(AuthSession).where(
            AuthSession.token_hash == token_hash,
            AuthSession.subject_type == SubjectType.staff,
        )
    )
    return int(result.rowcount)


async def delete_expired_for_staff(session: AsyncSession, staff_id: int, now: datetime) -> None:
    """この管理者の期限切れの行を削除する（主キーで消す）。"""
    ids = (
        (
            await session.execute(
                select(AuthSession.id).where(
                    AuthSession.subject_type == SubjectType.staff,
                    AuthSession.subject_id == staff_id,
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
    staff_id: int,
    now: datetime,
    *,
    max_sessions: int = MAX_SESSIONS_PER_STAFF,
) -> int:
    """有効なセッションが上限に達していれば、古い順に消して `max_sessions - 1` 件にする。

    新しい 1 件を足したあとに上限に収まるようにするため。消した件数を返す。
    """
    active = (
        (
            await session.execute(
                select(AuthSession.id)
                .where(
                    AuthSession.subject_type == SubjectType.staff,
                    AuthSession.subject_id == staff_id,
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
    staff_id: int,
    token_hash: str,
    now: datetime,
    expires_at: datetime,
) -> None:
    """新しいセッションを INSERT する。`last_seen_at` は作成時刻のまま（更新しない。DS-DEC-108）"""
    session.add(
        AuthSession(
            token_hash=token_hash,
            subject_type=SubjectType.staff,
            subject_id=staff_id,
            expires_at=expires_at,
            last_seen_at=now,
        )
    )
    await session.flush()


async def count_active_for_staff(session: AsyncSession, staff_id: int, now: datetime) -> int:
    """有効なセッションの件数（テスト・検証用）。"""
    rows = (
        await session.execute(
            select(AuthSession.id).where(
                AuthSession.subject_type == SubjectType.staff,
                AuthSession.subject_id == staff_id,
                AuthSession.expires_at > now,
            )
        )
    ).all()
    return len(rows)
