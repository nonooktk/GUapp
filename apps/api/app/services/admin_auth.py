"""管理認証のサービス層（DS-PRC-050・DS-API-050・050a。設計仕様書 P2 追補c 3.1・4.1・4.6・5.6）。

担当レーン: C-1（C-2・C-3 は使わない）。会員のログイン（`services/auth.py`・DS-PRC-032）と
同じ構造で、違いは次のとおり。

- 回数制限: `login_attempts` を **`subject_type=staff` だけ**で集計する（会員の行は数えない。
  DS-DEC-110）。ID 単位で直近 15 分に失敗 5 件以上なら 403 `account_locked`、IP 単位で
  失敗 **10 件**以上なら 429 `rate_limited`（`Retry-After: 900`）。どちらもパスワードの検証より前
- 管理者がいないときも、固定のダミーハッシュに対して検証する（処理時間を揃える）
- ロック通知のメールは送らない（`staff` にメールの列が無い）
- セッションは作成から **8 時間**の固定（延長しない）、同時に **3 件**まで（古い順に削除）
- ログインと同じトランザクションで `audit_logs` に `admin.login`（`detail` は丸めた IP だけ）
- 文の順序は `staff` → `sessions` → `login_attempts` → `audit_logs`（READ COMMITTED。
  ロック競合 1213・1205 は ROLLBACK して 1 回だけやり直す。5.6）。`staff` の行は最初に
  `FOR UPDATE` で取り、同じ管理者のログインを直列化する（同時 3 件の上限を超えないため。
  設計書 5.6 は再ハッシュ時だけ `staff` を触ると書くが、IT-050-10 の「3 件以内」に要る）
- 失敗の記録は、パスワードの検証より前に「失敗」として先に記録して COMMIT し、そのあとで数える
  （G-16。同時に来た試行が全部「失敗 0 件」を読んで検証まで進むすり抜けを防ぐ。会員と共通の
  `claim_login_attempt`）。上限を超えていれば検証せずに拒否して自分の行を取り消し、成功したら
  失敗行を消して成功を記録する
- ログ・監査ログ・拒否ログに login_id・パスワード・トークンを入れない（`identifier` は SHA-256）

`login_id` の正規化（`normalize_login_id`）もここに置く（スキーマとシードが使う）。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from fastapi import Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import passwords
from app.core.admin_session import CurrentStaff
from app.core.errors import AppError
from app.core.rate_limit import client_ip
from app.core.reject_log import log_rejection, mask_ip
from app.core.session import hash_token, is_valid_token_shape
from app.models import SubjectType
from app.repositories import login_attempts as attempts_repo
from app.repositories import staff as staff_repo
from app.repositories import staff_sessions as sessions_repo
from app.services import admin_audit
from app.services.auth import (
    ATTEMPT_CLEANUP_LIMIT,
    ATTEMPT_RETENTION,
    LOGIN_RETRY_AFTER_SECONDS,
    claim_login_attempt,
    new_token,
    normalize_ip,
    utcnow,
    withdraw_login_attempt,
)

logger = logging.getLogger("app.services.admin_auth")

# ── 数値（設計仕様書 DS-DEC-108・110、4.6 DS-PRC-050）────────────────────────────
SESSION_TTL = timedelta(hours=8)  # 作成から 8 時間の固定。延長しない
ID_LOCK_THRESHOLD = 5  # ID 単位: 直近 15 分に失敗 5 件以上で 403 account_locked
IP_LIMIT_THRESHOLD = 10  # IP 単位: 直近 15 分に失敗 10 件以上で 429 rate_limited（会員は 30）

# login_id: NFKC → 前後空白除去 → 小文字化のあと `^[a-z0-9][a-z0-9._-]{2,49}$`（`\d` を使わない）
LOGIN_ID_MIN_LENGTH = 3
LOGIN_ID_MAX_LENGTH = 50
_LOGIN_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,49}")

# MySQL: 1213 = Deadlock found、1205 = Lock wait timeout exceeded
_RETRYABLE_MYSQL_ERRORS = frozenset({1213, 1205})

LoginIdReason = Literal["required", "too_long", "too_short", "format"]


class InvalidLoginId(ValueError):
    """login_id として受け付けない値。`reason` は 4.5 の reason 固定語に対応する。"""

    def __init__(self, reason: LoginIdReason) -> None:
        super().__init__(reason)
        self.reason: LoginIdReason = reason


def normalize_login_id(raw: str) -> str:
    """NFKC・前後空白除去・小文字化のうえ形式を検査して返す。不正なら `InvalidLoginId`。

    全角・大文字・前後空白は半角の小文字に整う。ゼロ幅・制御文字・記号入り・先頭が記号・
    2 文字以下・51 文字以上は拒否（3 文字と 50 文字は可。UT-ADM-04）。
    """
    text = unicodedata.normalize("NFKC", raw).strip().lower()
    if not text:
        raise InvalidLoginId("required")
    if len(text) > LOGIN_ID_MAX_LENGTH:
        raise InvalidLoginId("too_long")
    if _LOGIN_ID_RE.fullmatch(text) is None:
        # 短すぎる値でも、文字種の違反が先にあれば `format`
        if len(text) < LOGIN_ID_MIN_LENGTH and re.fullmatch(r"[a-z0-9._-]+", text):
            raise InvalidLoginId("too_short")
        raise InvalidLoginId("format")
    return text


def is_valid_login_id(raw: str) -> bool:
    """seed の `SEED_STAFF_LOGIN_ID` などの形式検査用（例外を投げない版）。"""
    try:
        normalize_login_id(raw)
    except InvalidLoginId:
        return False
    return True


def admin_login_identifier(login_id: str) -> str:
    """`login_attempts.identifier`。正規化した login_id の SHA-256（16 進 64 文字）。

    全角・半角・大文字違いは正規化で同じ値になる。`login_id` は `normalize_login_id` 済みを渡す。
    管理者の有無に関係なく記録する。平文の login_id を DB に保存しない。
    """
    return hash_token(login_id)


def is_id_locked(failures: int) -> bool:
    return failures >= ID_LOCK_THRESHOLD


def is_ip_limited(failures: int) -> bool:
    return failures >= IP_LIMIT_THRESHOLD


def _is_retryable_lock_error(exc: OperationalError) -> bool:
    args = getattr(exc.orig, "args", ())
    return bool(args) and args[0] in _RETRYABLE_MYSQL_ERRORS


async def _begin_read_committed(session: AsyncSession) -> None:
    """これから始めるトランザクションを READ COMMITTED にする（5.6）。

    最初の文の前に呼ぶ。SQLite（単体テスト）は指定できないため、MySQL のときだけ指定する。
    """
    if session.get_bind().dialect.name == "mysql":
        await session.connection(execution_options={"isolation_level": "READ COMMITTED"})


def _reject(
    request: Request, *, status: int, code: str, ip: str, headers: dict[str, str] | None = None
) -> AppError:
    """拒否ログ（S9。IP は丸められる）を 1 行出して、返すエラーを作る。"""
    log_rejection(request, status=status, code=code, ip=ip)
    return AppError(status, code, headers=headers)


@dataclass(frozen=True, slots=True)
class AdminLoginResult:
    """ログインの結果。ルーターが `AdminLoginOut` にする。内部 ID は含めない。"""

    session_token: str
    login_id: str
    role: str


# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-050 管理ログインとセッション発行
# ══════════════════════════════════════════════════════════════════════════


async def login(
    session: AsyncSession,
    *,
    login_id: str,
    password: str,
    request: Request,
    old_session_token: str | None,
) -> AdminLoginResult:
    """DS-PRC-050 の手順 2〜9。`login_id` は `normalize_login_id` 済み、`password` は NFKC 済み。

    エラー: 401 `invalid_credentials`（管理者がいない・パスワード違いを区別しない）／
    403 `account_locked`／429 `rate_limited`（`Retry-After: 900`）。
    """
    # 2. ip と identifier
    ip = normalize_ip(client_ip(request))
    identifier = admin_login_identifier(login_id)

    # 3. 先に「失敗」として記録して COMMIT し、数え直す（G-16）。パスワードの検証より前。
    #    `subject_type=staff` だけを数える。判定は従来と同じ（自分の行を除いて、IP が先・ID が後）
    claimed = await claim_login_attempt(session, SubjectType.staff, identifier, ip)
    if is_ip_limited(claimed.prior_ip_failures):
        await withdraw_login_attempt(session, claimed.attempt_id)
        raise _reject(
            request,
            status=429,
            code="rate_limited",
            ip=ip,
            headers={"Retry-After": str(LOGIN_RETRY_AFTER_SECONDS)},
        )
    if is_id_locked(claimed.prior_identifier_failures):
        await withdraw_login_attempt(session, claimed.attempt_id)
        raise _reject(request, status=403, code="account_locked", ip=ip)

    # 4. 管理者を検索する。読み取りを終えてから argon2 を計算する
    await _begin_read_committed(session)
    staff = await staff_repo.find_by_login_id(session, login_id)
    await session.rollback()

    # 管理者がいないときも固定のダミーハッシュに対して検証し、処理時間を揃える（DS-DEC-110）
    stored_hash = staff.password_hash if staff is not None else passwords.dummy_hash()
    verified = await passwords.verify_password_async(stored_hash, password)

    # 5. 失敗: 試行は 3 で記録済み。401（管理者の有無・パスワード違いを区別しない）。
    #    ロック通知メールは送らない
    if staff is None or not verified:
        raise _reject(request, status=401, code="invalid_credentials", ip=ip)

    # 6. 成功: パラメータが古ければ再ハッシュ（更新は 7 の最初の文）
    new_hash: str | None = None
    if passwords.needs_rehash(staff.password_hash):
        new_hash = await passwords.hash_password_async(password)

    # 9. 新しいセッショントークン（DB には SHA-256 だけを保存）
    token = new_token()
    old_token_hash = (
        hash_token(old_session_token) if is_valid_token_shape(old_session_token) else None
    )

    # 7. 1 トランザクション（READ COMMITTED）。ロック競合は ROLLBACK して 1 回だけやり直す
    for attempt in range(2):
        try:
            await _begin_read_committed(session)
            now = utcnow()
            # ① staff（同じ管理者のログインを直列化する行ロック。再ハッシュ時はその UPDATE）
            await staff_repo.lock_for_login(session, staff.id)
            if new_hash is not None:
                await staff_repo.update_password_hash_if_unchanged(
                    session, staff.id, old_hash=staff.password_hash, new_hash=new_hash
                )
            # ②〜⑤ sessions（提示された古い行・期限切れ・上限超過を消してから新しい行）
            if old_token_hash is not None:
                await sessions_repo.delete_by_token_hash(session, old_token_hash)
            await sessions_repo.delete_expired_for_staff(session, staff.id, now)
            await sessions_repo.evict_oldest_for_new_session(session, staff.id, now)
            await sessions_repo.insert_session(
                session,
                staff_id=staff.id,
                token_hash=hash_token(token),
                now=now,
                expires_at=now + SESSION_TTL,
            )
            # ⑥ login_attempts（失敗行を消して成功を記録）
            await attempts_repo.delete_failures_by_identifier(
                session, SubjectType.staff, identifier
            )
            await attempts_repo.record(
                session, SubjectType.staff, identifier, succeeded=True, ip=ip, at=now
            )
            # ⑦ audit_logs（detail は丸めた IP だけ）
            await admin_audit.write_admin_audit(
                session,
                CurrentStaff(id=staff.id, login_id=staff.login_id, role=staff.role),
                action=admin_audit.ACTION_LOGIN,
                target_type="staff",
                target_id=str(staff.id),
                detail={"ip": mask_ip(ip)},
            )
            await session.commit()
            break
        except OperationalError as exc:
            await session.rollback()
            if attempt == 0 and _is_retryable_lock_error(exc):
                logger.warning(
                    "管理ログインでロック競合（%s）。ROLLBACK して 1 回やり直します",
                    exc.orig.args[0],
                )
                continue
            raise

    # 8. 24 時間より古い login_attempts を最大 1000 件、ついでに削除する（失敗しても影響させない）
    await _cleanup_old_attempts(session)

    return AdminLoginResult(session_token=token, login_id=staff.login_id, role=staff.role)


async def _cleanup_old_attempts(session: AsyncSession) -> None:
    try:
        await _begin_read_committed(session)
        await attempts_repo.delete_older_than(
            session, utcnow() - ATTEMPT_RETENTION, limit=ATTEMPT_CLEANUP_LIMIT
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001  掃除の失敗でログインを失敗させない
        await session.rollback()
        logger.warning("login_attempts の掃除に失敗しました error=%s", type(exc).__name__)


# ══════════════════════════════════════════════════════════════════════════
# DS-API-050a 管理ログアウト
# ══════════════════════════════════════════════════════════════════════════


class _ActorId:
    """監査ログの `actor_id` だけを持つ管理者（`staff` の行が既に消えていても記録できる）。"""

    __slots__ = ("id",)

    def __init__(self, staff_id: int) -> None:
        self.id = staff_id


async def logout(session: AsyncSession, session_token: str | None) -> None:
    """`subject_type=staff` の該当行を削除する。無効・不明・形が違う値・会員の値でも成功（冪等）。

    行を削除したときだけ `audit_logs` に `admin.logout`（同じトランザクション）。会員の行は
    削除しない。`require_staff` は通さない（期限切れ・管理者の行が無いセッションも消せる）。
    """
    if not is_valid_token_shape(session_token):
        return
    assert session_token is not None
    token_hash = hash_token(session_token)
    row = await sessions_repo.find_staff_by_token_hash(session, token_hash)
    if row is None:
        await session.rollback()
        return
    if await sessions_repo.delete_by_token_hash(session, token_hash) == 1:
        await admin_audit.write_admin_audit(
            session,
            _ActorId(row.subject_id),
            action=admin_audit.ACTION_LOGOUT,
            target_type="staff",
            target_id=str(row.subject_id),
        )
    await session.commit()
