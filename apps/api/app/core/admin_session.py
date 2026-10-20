"""管理用セッションの検証と `require_staff`（DS-PRC-050b。設計仕様書 P2 追補c 4.0・4.6・7.3）。

担当レーン: C-1（C-2・C-3 はここを呼ぶだけで、変更せずコーディネーターに依頼する）。

BFF は Cookie `asid` の値を `X-Admin-Session-Token` ヘッダに移して渡す。FastAPI は値の SHA-256 で
`sessions` を **`subject_type` を問わず**引き、種別で分ける（会員の `core/session.py` の対）。

- 管理者のセッション（`subject_type=staff`）で、`staff` の行があり、ロールが許可集合に
  あれば `CurrentStaff` を返す
- 会員のセッション（`subject_type=member`）が提示されたら 403 `forbidden`（BFLA の試み。
  拒否ログを 1 行出す。会員の情報は出さない。DS-DEC-109）
- 無い・形が違う・不明・期限切れ・管理者の行が無い場合は 401 `unauthorized`
- ロールが `ALLOWED_ROLES` に無ければ 403 `forbidden`（DS-DEC-111）
- `last_seen_at` は更新しない（GET が DB に書かない方針。DS-DEC-108）

`require_staff` は管理 API のルーターに**ルーター単位で掛け済み**（`routers/admin/__init__.py`。
既定拒否）。ルート関数が管理者を使うときだけ、次のように受ける::

    async def handler(staff: CurrentStaff = Depends(require_staff)) -> ...:

依存関数は DB の読み取りだけ行い、読み取りのトランザクションは `rollback()` で終えてから返す
（そのあとのサービスが新しいスナップショットで始められるようにする。会員の
`get_optional_member` と同じ）。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.rate_limit import client_ip
from app.core.reject_log import log_rejection
from app.core.session import hash_token, is_valid_token_shape
from app.models import SubjectType
from app.repositories import staff as staff_repo
from app.repositories import staff_sessions as staff_sessions_repo

ADMIN_SESSION_TOKEN_HEADER = "X-Admin-Session-Token"

# 管理 API に入れるロールの集合（DS-DEC-111）。P2 は `staff` の 1 つ。DB の CHECK 制約
# `ck_staff_role_allowed` と揃える。ロールを増やすときは両方を 1 リビジョンで変える
ALLOWED_ROLES: frozenset[str] = frozenset({"staff"})


@dataclass(frozen=True, slots=True)
class CurrentStaff:
    """検証済みの管理者。ORM 行ではなく値のコピー（トランザクションを終えても安全に使える）。

    パスワードのハッシュは含めない。`id` は内部 ID なので応答に出さない（設計仕様書 4.0）。
    """

    id: int
    login_id: str
    role: str


class AdminSessionKind(enum.StrEnum):
    """セッションの分類（UT-ADM-02）。「管理者」「会員」「無効」の 3 つ。"""

    staff = "staff"
    member = "member"
    invalid = "invalid"


@dataclass(frozen=True, slots=True)
class AdminSessionLookup:
    """`lookup_admin_session` の結果。`staff` は種別が `staff` のときだけ入る。"""

    kind: AdminSessionKind
    staff: CurrentStaff | None = None


_INVALID = AdminSessionLookup(AdminSessionKind.invalid)
_MEMBER = AdminSessionLookup(AdminSessionKind.member)


def _utcnow() -> datetime:
    """DB は UTC の naive datetime（`TimestampMixin` と同じ）。"""
    return datetime.now(UTC).replace(tzinfo=None)


async def lookup_admin_session(
    session: AsyncSession, token: str | None, *, now: datetime | None = None
) -> AdminSessionLookup:
    """DS-PRC-050b の手順 1〜4。分類だけ行い、HTTP の状態コードは決めない。例外を投げない。

    `now` は UT で時計を渡すための引数（既定は現在の UTC）。`expires_at > now` のものだけ有効
    （ちょうど現在は無効）。形が違う値・None は DB を引かずに「無効」。
    ロールの検査はここでは行わない（`require_staff` が `ALLOWED_ROLES` で判定する）。
    """
    if not is_valid_token_shape(token):
        return _INVALID
    assert token is not None
    current = now if now is not None else _utcnow()
    row = await staff_sessions_repo.find_active_by_token_hash(session, hash_token(token), current)
    if row is None:
        return _INVALID
    if row.subject_type == SubjectType.member:
        return _MEMBER
    staff = await staff_repo.find_by_id(session, row.subject_id)
    if staff is None:
        # 管理者の行が削除された（セッションの行は残るが使えない。7.3 の「失効」）
        return _INVALID
    return AdminSessionLookup(
        AdminSessionKind.staff,
        CurrentStaff(id=staff.id, login_id=staff.login_id, role=staff.role),
    )


async def require_staff(
    request: Request,
    x_admin_session_token: str | None = Header(default=None, alias=ADMIN_SESSION_TOKEN_HEADER),
    session: AsyncSession = Depends(get_session),
) -> CurrentStaff:
    """有効な管理者のセッションが無ければ 401／403。管理 API のルーターに掛け済み。

    設計書: 4.6 DS-PRC-050b、4.7（401・403 の使い方）、DS-DEC-109・111。
    エラー: 401 `unauthorized`（無い・形不正・不明・期限切れ・管理者の行が無い）／
    403 `forbidden`（会員のセッションを提示した・ロールが許可外）。
    401・403 のどちらも拒否ログを 1 行出す（`request_rejected`。本編 7.7 S9。IT-ADM-05）。
    """
    try:
        lookup = await lookup_admin_session(session, x_admin_session_token)
    finally:
        # 読み取りだけなので、トランザクションを終えて接続を返す（手順 6）
        await session.rollback()
    ip = client_ip(request)
    if lookup.kind is AdminSessionKind.invalid:
        log_rejection(request, status=401, code="unauthorized", ip=ip)
        raise AppError(401, "unauthorized")
    if lookup.kind is AdminSessionKind.member:
        log_rejection(request, status=403, code="forbidden", ip=ip)
        raise AppError(403, "forbidden")
    staff = lookup.staff
    assert staff is not None
    if staff.role not in ALLOWED_ROLES:
        log_rejection(request, status=403, code="forbidden", ip=ip)
        raise AppError(403, "forbidden")
    return staff
