"""管理者の読み書き（DS-TBL-04 staff。設計仕様書 P2 追補c 5.2・DS-PRC-050・050b）。

担当レーン: C-1。使うのは C-1 の `services/admin_auth.py`・`core/admin_session.py` と seed。
C-2・C-3 は直接使わない（管理者の情報は `CurrentStaff` で受け取る）。

- 管理者は ORM 行ではなく値のコピー（`StaffAuthRow`）で返す。argon2 の計算中に DB の
  トランザクションを閉じても安全に使えるようにするため（会員の `MemberAuthRow` と同じ）
- `login_id` は `services/admin_auth.normalize_login_id` で正規化済みのものを渡す
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Staff


@dataclass(frozen=True, slots=True)
class StaffAuthRow:
    """認証に要る項目だけの値のコピー。`locked_until` は予約の列で P2-c も使わない。"""

    id: int
    login_id: str
    password_hash: str
    role: str


_COLUMNS = (Staff.id, Staff.login_id, Staff.password_hash, Staff.role)


def _row(row: object) -> StaffAuthRow:
    return StaffAuthRow(
        id=row.id,  # type: ignore[attr-defined]
        login_id=row.login_id,  # type: ignore[attr-defined]
        password_hash=row.password_hash,  # type: ignore[attr-defined]
        role=row.role,  # type: ignore[attr-defined]
    )


async def find_by_login_id(session: AsyncSession, login_id: str) -> StaffAuthRow | None:
    """正規化済みの login_id で 1 件。いなければ None。"""
    row = (await session.execute(select(*_COLUMNS).where(Staff.login_id == login_id))).first()
    return _row(row) if row is not None else None


async def find_by_id(session: AsyncSession, staff_id: int) -> StaffAuthRow | None:
    """主キーで 1 件（セッション検証。DS-PRC-050b 手順 4）。いなければ None。"""
    row = (await session.execute(select(*_COLUMNS).where(Staff.id == staff_id))).first()
    return _row(row) if row is not None else None


async def lock_for_login(session: AsyncSession, staff_id: int) -> None:
    """管理者の行を `SELECT … FOR UPDATE` で排他する（同じ管理者のログインを直列化する）。

    同時に走った同じ管理者のログインが、互いの COMMIT 前のセッションを見落として同時セッションの
    上限（3 件）を超えないようにする（IT-050-10）。`staff` を最初に取る順序は固定で、
    ほかの文の順序（`sessions` → `login_attempts` → `audit_logs`）と循環しない（5.6）。
    SQLite（単体テスト）では `FOR UPDATE` は無視される。
    """
    await session.execute(select(Staff.id).where(Staff.id == staff_id).with_for_update())


async def update_password_hash_if_unchanged(
    session: AsyncSession, staff_id: int, *, old_hash: str, new_hash: str
) -> int:
    """ログイン時の再ハッシュ。読んだ時点のハッシュのままのときだけ更新する（影響行数を返す）。

    同時に走った別のログインや seed の更新で新しいハッシュが入っていたら、上書きしない。
    """
    result = await session.execute(
        update(Staff)
        .where(Staff.id == staff_id, Staff.password_hash == old_hash)
        .values(password_hash=new_hash)
    )
    return int(result.rowcount)
