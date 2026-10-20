"""会員の読み書き（DS-TBL-01 members。設計仕様書 P2 追補b 4.8・5.2・5.6）。

- 会員は ORM 行ではなく値のコピー（`MemberAuthRow`）で返す。argon2 の計算中に DB の
  トランザクションを閉じても安全に使えるようにするため
- `insert_member` は SAVEPOINT で囲み、メールの UNIQUE 違反を `DuplicateEmail` に変換する
  （外側のトランザクションは生きたまま。DS-PRC-030 手順 4）
- 監査ログ（`audit_logs`）には、メール・氏名・受け取りコード・トークンを入れない（F-05）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActorType, AuditLog, Member, MemberGender


class DuplicateEmail(Exception):
    """同じメールの会員が既にいる（呼び手は「既登録」の枝に入る）。"""


@dataclass(frozen=True, slots=True)
class MemberAuthRow:
    """認証に要る項目だけの値のコピー。"""

    id: int
    email: str
    name: str
    password_hash: str
    email_verified_at: datetime | None


def _row(row: Any) -> MemberAuthRow:
    return MemberAuthRow(
        id=row.id,
        email=row.email,
        name=row.name,
        password_hash=row.password_hash,
        email_verified_at=row.email_verified_at,
    )


_COLUMNS = (
    Member.id,
    Member.email,
    Member.name,
    Member.password_hash,
    Member.email_verified_at,
)


async def find_by_email(
    session: AsyncSession, email: str, *, include_anonymized: bool = False
) -> MemberAuthRow | None:
    """正規化済みのメールで 1 件。匿名化済みは既定で「いない」扱い（ログイン・再設定）。"""
    stmt = select(*_COLUMNS).where(Member.email == email)
    if not include_anonymized:
        stmt = stmt.where(Member.anonymized_at.is_(None))
    row = (await session.execute(stmt)).first()
    return _row(row) if row is not None else None


async def find_by_id(session: AsyncSession, member_id: int) -> MemberAuthRow | None:
    """匿名化済みは None。"""
    row = (
        await session.execute(
            select(*_COLUMNS).where(Member.id == member_id, Member.anonymized_at.is_(None))
        )
    ).first()
    return _row(row) if row is not None else None


async def insert_member(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    name: str,
    birth_date: date | None,
    gender: str | None,
    personalize_opt_in: bool,
) -> int:
    """`INSERT members`。メールの UNIQUE 違反は `DuplicateEmail`。新しい会員の ID を返す。

    `email_verified_at` は常に NULL（要求の値は受けない。mass assignment 対策）。
    """
    member = Member(
        email=email,
        password_hash=password_hash,
        name=name,
        birth_date=birth_date,
        gender=MemberGender(gender) if gender else None,
        personalize_opt_in=personalize_opt_in,
        email_verified_at=None,
    )
    try:
        async with session.begin_nested():
            session.add(member)
            await session.flush()
    except IntegrityError as exc:
        if "email" in str(exc.orig):
            raise DuplicateEmail() from exc
        raise
    return member.id


async def update_password_hash_if_unchanged(
    session: AsyncSession, member_id: int, *, old_hash: str, new_hash: str
) -> int:
    """ログイン時の再ハッシュ。読んだ時点のハッシュのままのときだけ更新する（影響行数を返す）。

    同時に走った再設定の確定で新しいハッシュが入っていたら、上書きしない。
    """
    result = await session.execute(
        update(Member)
        .where(Member.id == member_id, Member.password_hash == old_hash)
        .values(password_hash=new_hash)
    )
    return int(result.rowcount)


async def set_password_hash(session: AsyncSession, member_id: int, new_hash: str) -> None:
    """パスワード再設定の確定。"""
    await session.execute(
        update(Member).where(Member.id == member_id).values(password_hash=new_hash)
    )


async def mark_email_verified(session: AsyncSession, member_id: int, at: datetime) -> None:
    """`email_verified_at` を設定する。既に設定済みなら上書きしない（DS-PRC-031）。"""
    await session.execute(
        update(Member)
        .where(Member.id == member_id, Member.email_verified_at.is_(None))
        .values(email_verified_at=at)
    )


async def add_audit_log(
    session: AsyncSession,
    *,
    action: str,
    member_id: int,
    detail: dict[str, Any] | None = None,
) -> None:
    """会員の操作の監査ログ（`member.register`・`member.login` など）。

    `detail` にメール・氏名・トークンを入れない。
    """
    session.add(
        AuditLog(
            actor_type=ActorType.member,
            actor_id=member_id,
            action=action,
            target_type="member",
            target_id=str(member_id),
            detail=detail,
        )
    )
    await session.flush()
