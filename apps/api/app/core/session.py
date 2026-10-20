"""会員セッションの検証（DS-PRC-035。設計仕様書 P2 追補b 4.0・4.8・7.3・DS-DEC-72）。

担当レーン: A（B・C はここを呼ぶだけで、変更せずコーディネーターに依頼する）。

BFF は Cookie `sid` の値をそのまま `X-Session-Token` ヘッダに移して渡す。FastAPI は
値の SHA-256 で `sessions` を引き、会員を返す。生の値は DB に保存しない。

- `get_current_member`: 有効な会員セッションが無ければ 401 `unauthorized`
  （`/me` 系 API。DS-API-036・024・024a）
- `get_optional_member`: 無効でも例外にせず `None`（ゲストでも使える API。
  DS-API-022 注文確定・DS-API-007 再入荷の申込）
- スタッフのセッション（`subject_type=staff`）は会員の依存関数では常に無効（DS-DEC-72）
- `last_seen_at` は更新しない（GET が DB に書かない方針。DS-DEC-59）

依存関数は DB の読み取りだけ行い、読み取りのトランザクションは終えてから返す
（呼び出し元のサービスが READ COMMITTED など別の分離レベルで始め直せるようにするため）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.models import AuthSession, Member, SubjectType

SESSION_TOKEN_HEADER = "X-Session-Token"
# 32 バイト乱数の base64url（パディングなし）= 43 文字（DS-DEC-72）
SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True, slots=True)
class CurrentMember:
    """検証済みの会員。ORM 行ではなく値のコピー（トランザクションを終えても安全に使える）。

    パスワードのハッシュ・生年月日・性別は含めない（DS-API-036 の応答に出さない項目）。
    `id` は内部 ID なので応答に出さない（設計仕様書 4.0）。
    """

    id: int
    email: str
    name: str
    email_verified_at: datetime | None
    personalize_opt_in: bool

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


def hash_token(token: str) -> str:
    """トークン（セッション・メール確認・再設定）の保存用の値。SHA-256 の 16 進（64 文字）。

    担当レーン: A。B はセッション発行（DS-PRC-032）・メールのトークン（DS-PRC-030・034）で、
    C は使わない。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_valid_token_shape(token: str | None) -> bool:
    """`^[A-Za-z0-9_-]{43}$` か。None・空文字・42/44 文字・`=` や空白入りは False（例外なし）。"""
    return token is not None and SESSION_TOKEN_RE.fullmatch(token) is not None


def _utcnow() -> datetime:
    """DB は UTC の naive datetime（`TimestampMixin` と同じ）。"""
    return datetime.now(UTC).replace(tzinfo=None)


async def find_member_by_session_token(
    session: AsyncSession, token: str | None, *, now: datetime | None = None
) -> CurrentMember | None:
    """DS-PRC-035 の手順 1〜3。無効なら None（例外を投げない）。

    `now` は UT で時計を渡すための引数（既定は現在の UTC）。`expires_at > now` のものだけ有効。
    """
    if not is_valid_token_shape(token):
        return None
    assert token is not None
    current = now if now is not None else _utcnow()
    row = (
        await session.execute(
            select(
                Member.id,
                Member.email,
                Member.name,
                Member.email_verified_at,
                Member.personalize_opt_in,
            )
            .join(AuthSession, AuthSession.subject_id == Member.id)
            .where(
                AuthSession.token_hash == hash_token(token),
                AuthSession.subject_type == SubjectType.member,
                AuthSession.expires_at > current,
                Member.anonymized_at.is_(None),
            )
        )
    ).first()
    if row is None:
        return None
    return CurrentMember(
        id=row.id,
        email=row.email,
        name=row.name,
        email_verified_at=row.email_verified_at,
        personalize_opt_in=bool(row.personalize_opt_in),
    )


async def get_optional_member(
    x_session_token: str | None = Header(default=None, alias=SESSION_TOKEN_HEADER),
    session: AsyncSession = Depends(get_session),
) -> CurrentMember | None:
    """有効な会員セッションがあれば会員、無ければ（無効・期限切れ・staff・匿名化済みも）None。

    担当レーン: A。使うのは C（DS-API-022 注文確定、DS-API-007 再入荷の申込）。
    """
    if not is_valid_token_shape(x_session_token):
        return None
    try:
        return await find_member_by_session_token(session, x_session_token)
    finally:
        # 読み取りだけなので、トランザクションを終えて接続を返す
        await session.rollback()


async def get_current_member(
    member: CurrentMember | None = Depends(get_optional_member),
) -> CurrentMember:
    """有効な会員セッションが無ければ 401 `unauthorized`。

    担当レーン: A。使うのは B（DS-API-036 `GET /me`）と C（DS-API-024・024a `/me/orders`）。
    """
    if member is None:
        raise AppError(401, "unauthorized")
    return member
