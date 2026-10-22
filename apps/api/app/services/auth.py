"""認証のサービス層（DS-PRC-030・031・032・034・035。設計仕様書 P2 追補b 4.8・5.6・7）。

- 会員登録（030）／メール確認（031）／ログインとセッション発行（032）／ログアウト／
  パスワード再設定の要求（034）と確定（035）
- ユーザー列挙の防止（DS-DEC-71）: ログインは会員の有無によらず同じ 401 と同じ処理
  （会員がいなければダミーのハッシュを検証）。登録は新規・既登録とも 202。再設定の要求は常に 200。
  メールは応答のあとの後処理（`BackgroundTasks` ＋ `safe_send`）で送る
- ログインは、パスワードの検証（argon2 で遅い）より前に自分の試行を「失敗」として先に記録して
  COMMIT し、そのあとで数える（G-16）。同時に来た試行が全部「失敗 0 件」を読んで検証まで進む
  すり抜けを防ぐ。上限を超えていれば検証せずに拒否して自分の行を取り消し、成功したら失敗行を
  消して成功を記録する
- ログインと再設定の確定は READ COMMITTED（MySQL のときだけ指定）で実行し、文の順序を
  `members` → `sessions` → `login_attempts` → `audit_logs` に揃える。ロック競合
  （MySQL の 1213・1205）は ROLLBACK して 1 回だけやり直す（5.6）
- ログ・監査ログ・拒否ログにメール・パスワード・トークンを入れない
"""

from __future__ import annotations

import ipaddress
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.mail import (
    KIND_ACCOUNT_EXISTS,
    KIND_ACCOUNT_LOCKED,
    KIND_EMAIL_VERIFICATION,
    KIND_PASSWORD_RESET,
    MailAdapter,
    build_public_url,
    safe_send,
)
from app.core import passwords
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import client_ip, enforce_rate_limit
from app.core.reject_log import log_rejection
from app.core.session import hash_token, is_valid_token_shape
from app.models import EmailTokenPurpose, SubjectType
from app.repositories import email_tokens as tokens_repo
from app.repositories import login_attempts as attempts_repo
from app.repositories import members as members_repo
from app.repositories import sessions as sessions_repo
from app.repositories.members import DuplicateEmail
from app.schemas.auth import (
    LoginIn,
    LoginMemberOut,
    LoginOut,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RegisterIn,
    VerifyEmailIn,
)
from app.services.email_normalize import is_email_domain_allowed, login_identifier
from app.services.password_policy import weak_password_reason

logger = logging.getLogger("app.services.auth")

# ── 数値（設計仕様書 DS-DEC-70・72・84、4.1・7.3）──────────────────────────────
SESSION_TTL = timedelta(hours=24)  # 作成から 24 時間の固定。延長しない
VERIFY_EMAIL_TTL = timedelta(hours=24)
RESET_PASSWORD_TTL = timedelta(hours=1)
LOGIN_WINDOW = timedelta(minutes=15)
EMAIL_LOCK_THRESHOLD = 5  # メール単位: 直近 15 分に失敗 5 件以上で 403 account_locked
IP_LIMIT_THRESHOLD = 30  # IP 単位: 直近 15 分に失敗 30 件以上で 429 rate_limited
LOGIN_RETRY_AFTER_SECONDS = 900
ATTEMPT_RETENTION = timedelta(hours=24)
ATTEMPT_CLEANUP_LIMIT = 1000

AUDIT_REGISTER = "member.register"
AUDIT_EMAIL_VERIFIED = "member.email_verified"
AUDIT_LOGIN = "member.login"
AUDIT_PASSWORD_RESET = "member.password_reset"  # pragma: allowlist secret（監査ログの action 名）

# MySQL: 1213 = Deadlock found、1205 = Lock wait timeout exceeded
_RETRYABLE_MYSQL_ERRORS = frozenset({1213, 1205})


def utcnow() -> datetime:
    """DB は UTC の naive datetime（`TimestampMixin` と同じ）。"""
    return datetime.now(UTC).replace(tzinfo=None)


def new_token() -> str:
    """32 バイト乱数の base64url（パディングなし）43 文字。DB には SHA-256 だけを保存する。"""
    return secrets.token_urlsafe(32)


def is_email_locked(failures: int) -> bool:
    return failures >= EMAIL_LOCK_THRESHOLD


def is_ip_limited(failures: int) -> bool:
    return failures >= IP_LIMIT_THRESHOLD


def normalize_ip(raw: str) -> str:
    """`login_attempts.ip`（45 文字）に入れる値。解釈できない値は `unknown`（長さ超過を避ける）。"""
    try:
        return ipaddress.ip_address(raw.strip()).compressed
    except ValueError:
        return "unknown"


def _is_retryable_lock_error(exc: OperationalError) -> bool:
    args = getattr(exc.orig, "args", ())
    return bool(args) and args[0] in _RETRYABLE_MYSQL_ERRORS


async def _begin_read_committed(session: AsyncSession) -> None:
    """これから始めるトランザクションを READ COMMITTED にする（5.6）。

    最初の文の前（トランザクションを始める前）に呼ぶ。SQLite（単体テスト）は READ COMMITTED を
    指定できないため、MySQL のときだけ指定する。
    """
    if session.get_bind().dialect.name == "mysql":
        await session.connection(execution_options={"isolation_level": "READ COMMITTED"})


def _check_demo_domain(email: str) -> None:
    """`DEMO_EMAIL_DOMAINS` を設定した環境では許可外のドメインを 422 にする（DS-DEC-88）。"""
    if not is_email_domain_allowed(email, get_settings().demo_email_domains):
        raise AppError(422, "unsupported_value", field="email")


def check_demo_email_domain(email: str) -> None:
    """他レーン（再入荷の申込。DS-API-007）からも使える公開名。"""
    _check_demo_domain(email)


def _reject(
    request: Request, *, status: int, code: str, ip: str, headers: dict[str, str] | None = None
) -> AppError:
    """拒否ログ（S9。IP は丸めて出る）を 1 行出して、返すエラーを作る。"""
    log_rejection(request, status=status, code=code, ip=ip)
    return AppError(status, code, headers=headers)


@dataclass(frozen=True, slots=True)
class ClaimedAttempt:
    """先に記録した試行（G-16）。件数は**自分の行を含む**直近 15 分の失敗の数。"""

    attempt_id: int
    ip_failures: int
    identifier_failures: int

    @property
    def prior_ip_failures(self) -> int:
        """自分の行を除いた IP 単位の失敗数（従来の「検証の前に数える」件数と同じ意味）。"""
        return self.ip_failures - 1

    @property
    def prior_identifier_failures(self) -> int:
        """自分の行を除いた識別子単位の失敗数。"""
        return self.identifier_failures - 1


async def claim_login_attempt(
    session: AsyncSession, subject_type: SubjectType, identifier: str, ip: str
) -> ClaimedAttempt:
    """検証の前に、この試行を「失敗」として先に記録して COMMIT し、そのあとで数える（G-16）。

    会員・管理の両方のログインが使う。COMMIT のあとに数えるため、同時に来た試行のうち上限を
    超えない件数（COMMIT の順に数えて上限以下）だけが「超過ではない」と判定され、検証へ進める。
    ロック競合（1213・1205）は ROLLBACK して 1 回だけやり直す。
    """
    attempt_id = 0
    for attempt in range(2):
        try:
            await _begin_read_committed(session)
            attempt_id = await attempts_repo.record(
                session, subject_type, identifier, succeeded=False, ip=ip, at=utcnow()
            )
            await session.commit()
            break
        except OperationalError as exc:
            await session.rollback()
            if attempt == 0 and _is_retryable_lock_error(exc):
                logger.warning(
                    "ログイン試行の記録でロック競合（%s）。ROLLBACK して 1 回やり直します",
                    exc.orig.args[0],
                )
                continue
            raise
    await _begin_read_committed(session)
    since = utcnow() - LOGIN_WINDOW
    ip_failures = await attempts_repo.count_failures_by_ip(session, subject_type, ip, since)
    identifier_failures = await attempts_repo.count_failures_by_identifier(
        session, subject_type, identifier, since
    )
    await session.rollback()
    return ClaimedAttempt(attempt_id, ip_failures, identifier_failures)


async def withdraw_login_attempt(session: AsyncSession, attempt_id: int) -> None:
    """上限超過で拒否した試行の、先に記録した行を取り消す（ロック期間を延ばさないため）。

    取り消せなくても拒否の応答は変えない（行が残るだけで、より厳しい側に倒れる）。
    """
    try:
        await _begin_read_committed(session)
        await attempts_repo.delete_by_id(session, attempt_id)
        await session.commit()
    except Exception as exc:  # noqa: BLE001  取り消しの失敗で拒否の応答を変えない
        await session.rollback()
        logger.warning("login_attempts の取り消しに失敗しました error=%s", type(exc).__name__)


# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-030 会員登録
# ══════════════════════════════════════════════════════════════════════════


async def register(
    session: AsyncSession,
    body: RegisterIn,
    *,
    background: BackgroundTasks,
    mail: MailAdapter,
) -> None:
    """新規でも既登録でも呼び手は 202 を返す（DS-DEC-71）。セッションは発行しない（DS-DEC-76）。"""
    email = body.email  # 検査・正規化済み（スキーマ）
    # 2. DB を見ない検査（メールが登録済みかどうかに依存させない）
    if weak_password_reason(body.password, email) is not None:
        raise AppError(422, "weak_password", field="password")
    _check_demo_domain(email)
    # PUBLIC_WEB_BASE_URL の設定漏れは、新規・既登録の区別なく同じ 500 にする（応答差を作らない）
    build_public_url("/verify-email")

    # 3. 既登録のメールでも同じ処理をして結果を捨てる（応答時間を揃える）
    password_hash = await passwords.hash_password_async(body.password)

    # 4. INSERT members。UNIQUE 違反なら「既登録」の枝
    try:
        member_id = await members_repo.insert_member(
            session,
            email=email,
            password_hash=password_hash,
            name=body.name,
            birth_date=body.birth_date,
            gender=body.gender,
            personalize_opt_in=body.personalize_opt_in,
        )
    except DuplicateEmail:
        await session.rollback()
        background.add_task(safe_send, KIND_ACCOUNT_EXISTS, email, mail.send_account_exists, email)
        return

    token = new_token()
    await tokens_repo.insert_token(
        session,
        member_id=member_id,
        purpose=EmailTokenPurpose.verify_email,
        token_hash=hash_token(token),
        expires_at=utcnow() + VERIFY_EMAIL_TTL,
    )
    await members_repo.add_audit_log(session, action=AUDIT_REGISTER, member_id=member_id)
    await session.commit()

    # 5. 確認メールは応答のあとに送る
    link = build_public_url(f"/verify-email?token={token}")
    background.add_task(
        safe_send,
        KIND_EMAIL_VERIFICATION,
        email,
        mail.send_email_verification,
        email,
        body.name,
        link,
    )


# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-031 メール確認
# ══════════════════════════════════════════════════════════════════════════


async def verify_email(session: AsyncSession, body: VerifyEmailIn) -> None:
    """トークンが有効なら `email_verified_at` を設定する。無効・期限切れ・使用済みは 404。"""
    await _begin_read_committed(session)
    now = utcnow()
    row = await tokens_repo.find_valid(
        session,
        token_hash=hash_token(body.token),
        purpose=EmailTokenPurpose.verify_email,
        now=now,
        for_update=True,
    )
    if row is None:
        await session.rollback()
        raise AppError(404, "not_found")
    if await tokens_repo.mark_used(session, row.id, now) == 0:
        await session.rollback()
        raise AppError(404, "not_found")
    await members_repo.mark_email_verified(session, row.member_id, now)
    await members_repo.add_audit_log(session, action=AUDIT_EMAIL_VERIFIED, member_id=row.member_id)
    await session.commit()


# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-032 ログインとセッション発行
# ══════════════════════════════════════════════════════════════════════════


async def login(
    session: AsyncSession,
    body: LoginIn,
    *,
    request: Request,
    old_session_token: str | None,
    background: BackgroundTasks,
    mail: MailAdapter,
) -> LoginOut:
    ip = normalize_ip(client_ip(request))
    identifier = login_identifier(body.email)

    # 3. 先に「失敗」として記録して COMMIT し、数え直す（G-16）。パスワードの検証より前。
    #    判定は従来と同じ（自分の行を除いて、IP が先・メールが後）
    claimed = await claim_login_attempt(session, SubjectType.member, identifier, ip)
    if is_ip_limited(claimed.prior_ip_failures):
        await withdraw_login_attempt(session, claimed.attempt_id)
        raise _reject(
            request,
            status=429,
            code="rate_limited",
            ip=ip,
            headers={"Retry-After": str(LOGIN_RETRY_AFTER_SECONDS)},
        )
    if is_email_locked(claimed.prior_identifier_failures):
        await withdraw_login_attempt(session, claimed.attempt_id)
        raise _reject(request, status=403, code="account_locked", ip=ip)

    # 4. 会員を検索する（匿名化済みは「いない」扱い）。読み取りを終えてから argon2 を計算する
    await _begin_read_committed(session)
    member = await members_repo.find_by_email(session, body.email)
    await session.rollback()

    # 会員がいないときも固定のダミーハッシュに対して検証し、処理時間を揃える（DS-DEC-71）
    stored_hash = member.password_hash if member is not None else passwords.dummy_hash()
    verified = await passwords.verify_password_async(stored_hash, body.password)

    # 5. 失敗: 試行は 3 で記録済み。401（会員の有無・パスワード違いを区別しない）。
    #    メール単位の失敗がちょうど 5 件目で、会員がいるときはロック通知を 1 回送る。
    #    5 件目の失敗の応答自体は 401 で、ロックは次の試行から有効になる（DS-PRC-032 手順 5）
    if member is None or not verified:
        if member is not None and claimed.identifier_failures == EMAIL_LOCK_THRESHOLD:
            background.add_task(
                safe_send,
                KIND_ACCOUNT_LOCKED,
                member.email,
                mail.send_account_locked,
                member.email,
                member.name,
            )
        raise _reject(request, status=401, code="invalid_credentials", ip=ip)

    # 6. 成功: パラメータが古ければ再ハッシュ（更新は 7 の最初の文）
    new_hash: str | None = None
    if passwords.needs_rehash(member.password_hash):
        new_hash = await passwords.hash_password_async(body.password)

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
            # ① 再ハッシュ（members）
            if new_hash is not None:
                await members_repo.update_password_hash_if_unchanged(
                    session, member.id, old_hash=member.password_hash, new_hash=new_hash
                )
            # ②〜⑤ sessions
            if old_token_hash is not None:
                await sessions_repo.delete_by_token_hash(session, old_token_hash)
            await sessions_repo.delete_expired_for_member(session, member.id, now)
            await sessions_repo.evict_oldest_for_new_session(session, member.id, now)
            await sessions_repo.insert_session(
                session,
                member_id=member.id,
                token_hash=hash_token(token),
                now=now,
                expires_at=now + SESSION_TTL,
            )
            # ⑥ login_attempts（失敗行を消して成功を記録）
            await attempts_repo.delete_failures_by_identifier(
                session, SubjectType.member, identifier
            )
            await attempts_repo.record(
                session, SubjectType.member, identifier, succeeded=True, ip=ip, at=now
            )
            # ⑦ audit_logs
            await members_repo.add_audit_log(session, action=AUDIT_LOGIN, member_id=member.id)
            await session.commit()
            break
        except OperationalError as exc:
            await session.rollback()
            if attempt == 0 and _is_retryable_lock_error(exc):
                logger.warning(
                    "ログインでロック競合（%s）。ROLLBACK して 1 回やり直します", exc.orig.args[0]
                )
                continue
            raise

    # 8. 24 時間より古い login_attempts を最大 1000 件、ついでに削除する（失敗しても影響させない）
    await _cleanup_old_attempts(session)

    return LoginOut(
        session_token=token,
        member=LoginMemberOut(
            name=member.name, email_verified=member.email_verified_at is not None
        ),
    )


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
# ログアウト（DS-API-033）
# ══════════════════════════════════════════════════════════════════════════


async def logout(session: AsyncSession, session_token: str | None) -> None:
    """該当する `sessions` の行を削除する。無効・不明・形が違う値でも何もせず成功（冪等）。"""
    if not is_valid_token_shape(session_token):
        return
    assert session_token is not None
    await sessions_repo.delete_by_token_hash(session, hash_token(session_token))
    await session.commit()


# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-034 パスワード再設定の要求
# ══════════════════════════════════════════════════════════════════════════


async def password_reset_request(
    session: AsyncSession,
    body: PasswordResetRequestIn,
    *,
    request: Request,
    background: BackgroundTasks,
    mail: MailAdapter,
) -> None:
    """会員がいてもいなくても呼び手は同じ 200 を返す（DS-DEC-71）。"""
    email = body.email
    _check_demo_domain(email)
    # メールごとの制限（3 回/時）。キーは平文のメールを避けた SHA-256。会員の有無に関係なく数える
    enforce_rate_limit(request, "password_reset_request_email", key=login_identifier(email))
    # 設定漏れは会員の有無に関係なく同じ 500 にする
    build_public_url("/password-reset/confirm")

    # 同じ会員の未使用トークンの無効化と INSERT は、ギャップロックを避けるため READ COMMITTED
    for attempt in range(2):
        try:
            await _begin_read_committed(session)
            member = await members_repo.find_by_email(session, email)
            if member is None:
                await session.rollback()
                return
            now = utcnow()
            token = new_token()
            await tokens_repo.invalidate_unused(
                session, member.id, EmailTokenPurpose.reset_password, now
            )
            await tokens_repo.insert_token(
                session,
                member_id=member.id,
                purpose=EmailTokenPurpose.reset_password,
                token_hash=hash_token(token),
                expires_at=now + RESET_PASSWORD_TTL,
            )
            await session.commit()
            break
        except OperationalError as exc:
            await session.rollback()
            if attempt == 0 and _is_retryable_lock_error(exc):
                continue
            raise

    # リンクは PUBLIC_WEB_BASE_URL から作る（リクエストの Host は使わない。DS-DEC-75）
    link = build_public_url(f"/password-reset/confirm?token={token}")
    background.add_task(
        safe_send,
        KIND_PASSWORD_RESET,
        member.email,
        mail.send_password_reset,
        member.email,
        member.name,
        link,
    )


# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-035 相当: パスワード再設定の確定（DS-API-035）
# ══════════════════════════════════════════════════════════════════════════


async def password_reset_confirm(session: AsyncSession, body: PasswordResetConfirmIn) -> None:
    """トークンが有効なら新しいパスワードに更新し、当該会員の全セッションを削除する。

    弱いパスワード（422）ではトークンを消費しない。自動ログインはしない（DS-DEC-75）。
    """
    token_hash = hash_token(body.token)

    # 1. トークンの確認（ロックなし）。無効・期限切れ・使用済み・目的違いは 404
    await _begin_read_committed(session)
    row = await tokens_repo.find_valid(
        session,
        token_hash=token_hash,
        purpose=EmailTokenPurpose.reset_password,
        now=utcnow(),
    )
    member = await members_repo.find_by_id(session, row.member_id) if row is not None else None
    await session.rollback()
    if row is None or member is None:
        raise AppError(404, "not_found")

    # 2. パスワードのポリシー（会員のメールと同一の拒否を含む）。ここで落ちてもトークンは消費しない
    if weak_password_reason(body.password, member.email) is not None:
        raise AppError(422, "weak_password", field="password")

    new_hash = await passwords.hash_password_async(body.password)
    identifier = login_identifier(member.email)

    # 3. 1 トランザクション（READ COMMITTED）。順序: email_tokens(FOR UPDATE) → members →
    #    email_tokens(UPDATE) → sessions → login_attempts → audit_logs（5.6）
    for attempt in range(2):
        try:
            await _begin_read_committed(session)
            now = utcnow()
            locked = await tokens_repo.find_valid(
                session,
                token_hash=token_hash,
                purpose=EmailTokenPurpose.reset_password,
                now=now,
                for_update=True,
            )
            if locked is None:
                # 同じトークンの別の確定が先に終わった
                await session.rollback()
                raise AppError(404, "not_found")
            await members_repo.set_password_hash(session, locked.member_id, new_hash)
            await tokens_repo.mark_used(session, locked.id, now)
            await sessions_repo.delete_all_for_member(session, locked.member_id)
            await attempts_repo.delete_failures_by_identifier(
                session, SubjectType.member, identifier
            )
            await members_repo.add_audit_log(
                session, action=AUDIT_PASSWORD_RESET, member_id=locked.member_id
            )
            await session.commit()
            return
        except OperationalError as exc:
            await session.rollback()
            if attempt == 0 and _is_retryable_lock_error(exc):
                logger.warning(
                    "パスワード再設定でロック競合（%s）。ROLLBACK して 1 回やり直します",
                    exc.orig.args[0],
                )
                continue
            raise
