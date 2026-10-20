"""AI アシスタント（DS-API-040・041、DS-PRC-029-1・029-4。設計仕様書 P2 追補d 4.6）。

質問の受付から応答までの全体。ルーターは入出力だけで、判断はここに置く。

- DB のトランザクションを 2 つに分ける（DS-DEC-98）。①往復数の予約（条件付き UPDATE）と質問の保存、
  ②応答の保存。LLM を呼んでいる間（最大 10 秒）は、トランザクションもロックも DB 接続も持たない
  （資料を読んだあとに `rollback()` で接続をプールへ返す）
- LLM が失敗したら往復数を 1 戻す（日次の数え上げは利用者メッセージの行で行うため、
  失敗した呼び出しも日次に数えられる）
- 質問はマスクしてから保存し、LLM へ送る。元の文字列は DB・ログ・LLM のどこにも残さない
- ログに質問・応答の本文、`chat_token`、IP の全桁を出さない（8.6）
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import (
    OUTER_TIMEOUT_MARGIN_SECONDS,
    LLMAdapter,
    LLMError,
    LLMResult,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.models import ChatRole
from app.repositories import chat as chat_repo
from app.repositories import contents as contents_repo
from app.schemas.chat import (
    CHAT_MESSAGE_MAX_CHARS,
    ChatLLMOutput,
    ChatMessageIn,
    ChatMessageOut,
    ChatStatusOut,
)
from app.services import chat_guard, chat_prompt
from app.services.content import is_within_publish_window

logger = logging.getLogger("app.chat")

# 画面と API の約束（4.2）
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
# FAQ と特商法の slug（P2-a の contents）
FAQ_SLUG = "faq"
TOKUSHOHO_SLUG = "tokushoho"


# ── トークン（DS-DEC-97）──


def issue_chat_token() -> str:
    """新しいセッションのトークン（43 文字の base64url）。DB には `hash_token` の値だけ保存する。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 の 16 進（64 文字）。"""
    return hashlib.sha256(token.encode()).hexdigest()


def is_valid_token_format(token: str | None) -> bool:
    return bool(token) and TOKEN_PATTERN.fullmatch(token or "") is not None


# ── ログ（8.6）──


def _log(event: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, "%s", json.dumps({"event": event, **fields}, ensure_ascii=False))


# ── DS-API-040 チャットの状態 ──


async def get_status(
    session: AsyncSession, settings: Settings, adapter: LLMAdapter
) -> ChatStatusOut:
    """利用可否と上限値。DB には書かない（日次の数え上げのために読むだけ）。"""
    base = {
        "turns_limit": settings.CHAT_TURN_LIMIT,
        "message_max_chars": CHAT_MESSAGE_MAX_CHARS,
    }
    if not adapter.available:
        # キーが無いことは利用者に見せず disabled に丸める
        return ChatStatusOut(available=False, reason="disabled", provider="none", **base)
    used = await chat_repo.count_user_messages_since(session, chat_guard.jst_day_start_utc())
    if used >= settings.CHAT_DAILY_LIMIT:
        return ChatStatusOut(available=False, reason="daily_limit", provider=adapter.name, **base)
    return ChatStatusOut(available=True, reason=None, provider=adapter.name, **base)


# ── DS-API-041 質問の送信と回答 ──


async def _reserve_turn(session: AsyncSession, settings: Settings, chat_session_id: int) -> bool:
    if settings.is_test:
        # テストモード限定: 同時の 2 件が予約の直前に揃ったことを確かめる（テスト設計書 1.4 #2）
        from app.core import testing_hooks

        async with testing_hooks.allocation_counter.track():
            await testing_hooks.maybe_delay()
            return await chat_repo.reserve_turn(session, chat_session_id, settings.CHAT_TURN_LIMIT)
    return await chat_repo.reserve_turn(session, chat_session_id, settings.CHAT_TURN_LIMIT)


async def _release_turn(session: AsyncSession, chat_session_id: int) -> None:
    """往復数を戻す。戻せなくても、呼び出し元の元のエラーを優先する。"""
    try:
        await session.rollback()
        async with session.begin():
            await chat_repo.release_turn(session, chat_session_id)
    except Exception:  # noqa: BLE001
        logger.exception("往復数を戻せませんでした")


async def _load_documents(session: AsyncSession) -> tuple[str, str]:
    """FAQ と特商法の本文（掲載期間内のもの。無ければ空文字）。"""
    now = datetime.now(UTC).replace(tzinfo=None)
    bodies: list[str] = []
    for slug in (FAQ_SLUG, TOKUSHOHO_SLUG):
        row = await contents_repo.get_by_slug(session, slug)
        if row is not None and is_within_publish_window(now, row.publish_from, row.publish_to):
            bodies.append(row.body)
        else:
            bodies.append("")
    return bodies[0], bodies[1]


async def post_message(
    session: AsyncSession,
    settings: Settings,
    adapter: LLMAdapter,
    body: ChatMessageIn,
    token: str | None,
) -> ChatMessageOut:
    """DS-PRC-029-1 手順 3〜11。手順 1・2（IP の回数制限・形の検証）は依存関数と Pydantic。"""
    started = time.monotonic()

    # 手順 3: アダプタの解決。無効なら LLM も DB も使わない
    if not adapter.available:
        raise AppError(503, "chat_unavailable")

    # 手順 4: 日次上限（今日（JST）の利用者メッセージ数）
    used_today = await chat_repo.count_user_messages_since(session, chat_guard.jst_day_start_utc())
    await session.rollback()  # 読み取りのトランザクションを終える
    if used_today >= settings.CHAT_DAILY_LIMIT:
        _log("chat_daily_limit", logging.WARNING, provider=adapter.name)
        raise AppError(503, "chat_daily_limit")

    # 質問をマスクする（保存も LLM への送信も、マスク後の文字列だけを使う。DS-PRC-029-2）
    masked = chat_guard.mask_pii(body.message)

    # 手順 5: トランザクション①（短い）。セッション解決 → 往復数の予約 → 質問の保存
    new_token: str | None = None
    async with session.begin():
        chat = (
            await chat_repo.get_session_by_hash(session, hash_token(token))
            if is_valid_token_format(token)
            else None
        )
        if chat is None:
            new_token = issue_chat_token()
            chat = await chat_repo.create_session(session, hash_token(new_token))
        chat_id = chat.id
        token_hash = chat.token_hash
        if not await _reserve_turn(session, settings, chat_id):
            raise AppError(409, "turn_limit", limit=settings.CHAT_TURN_LIMIT)
        turns_used = await chat_repo.get_turns(session, chat_id)
        user_message = await chat_repo.add_message(session, chat_id, ChatRole.user, masked.text)
        user_message_id = user_message.id

    result: LLMResult
    try:
        # 手順 6: 資料を読む（読み取りだけ）。読み終えたら接続をプールへ返す
        faq_body, tokushoho_body = await _load_documents(session)
        pool = await chat_prompt.build_candidate_pool(session, context_product_id=body.product_id)
        history = await chat_repo.list_history(
            session, chat_id, before_message_id=user_message_id, limit=chat_prompt.HISTORY_LIMIT
        )
        await session.rollback()

        # 手順 7: LLM を呼ぶ（再試行 0 回。全体も SDK の外側で打ち切る）
        request = chat_prompt.build_llm_request(
            faq_body=faq_body,
            tokushoho_body=tokushoho_body,
            pool=pool,
            history=history,
            question=masked.text,
            safety_identifier=token_hash[:32],
        )
        try:
            result = await asyncio.wait_for(
                adapter.generate(request),
                timeout=settings.OPENAI_TIMEOUT_SECONDS + OUTER_TIMEOUT_MARGIN_SECONDS,
            )
        except TimeoutError as exc:
            raise LLMError("timeout") from exc
    except LLMError as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        if exc.kind == "refusal":
            # 手順 8: 安全上の拒否はエラーにせず、範囲外として続行する
            result = LLMResult(
                output=ChatLLMOutput(intent="out_of_scope", message="", items=[]),
                model=adapter.model,
            )
            _log("chat_llm_error", provider=adapter.name, outcome="refusal", latency_ms=latency_ms)
        else:
            await _release_turn(session, chat_id)
            _log(
                "chat_llm_error",
                logging.WARNING,
                provider=adapter.name,
                model=adapter.model,
                outcome=exc.kind,
                latency_ms=latency_ms,
            )
            if exc.kind == "timeout":
                raise AppError(504, "llm_timeout") from exc
            raise AppError(502, "llm_error") from exc
    except Exception:
        await _release_turn(session, chat_id)
        raise

    try:
        # 手順 9: 出力の検査と商品カードの組み立て（DS-PRC-029-3）
        output = result.output
        wanted = (
            [i.product_id for i in chat_guard.validate_items(output.items, pool.ids)]
            if output.intent == "recommend"
            else []
        )
        cards = await chat_repo.get_product_cards(session, wanted)
        await session.rollback()
        final = chat_guard.finalize_reply(
            output,
            question=masked.text,
            # LLM に渡した資料（各 4,000 文字で切ったもの）と同じ範囲で数値を照合する
            sources=[
                faq_body[: chat_prompt.DOCUMENT_MAX_CHARS],
                tokushoho_body[: chat_prompt.DOCUMENT_MAX_CHARS],
            ],
            canary=chat_prompt.PROMPT_CANARY,
            pool_ids=pool.ids,
            cards=cards,
        )
        reply = final.reply
        if final.canary_leak:
            _log("chat_canary_leak", logging.WARNING, provider=adapter.name, model=result.model)

        # 手順 10: トランザクション②。ロックの順序は chat_sessions → chat_messages
        async with session.begin():
            if reply.intent == "out_of_scope":
                await chat_repo.mark_handoff(
                    session, chat_id, datetime.now(UTC).replace(tzinfo=None)
                )
            await chat_repo.add_message(
                session,
                chat_id,
                ChatRole.assistant,
                reply.message,
                product_ids=[p.id for p in reply.products],
                intent=reply.intent,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
    except Exception:
        await _release_turn(session, chat_id)
        raise

    # 手順 11: 応答を返す。ログは 1 行（本文は出さない）
    _log(
        "chat_reply",
        provider=adapter.name,
        model=result.model,
        intent=reply.intent,
        outcome="ok",
        latency_ms=int((time.monotonic() - started) * 1000),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        dropped_ids=final.dropped_ids,
    )
    return ChatMessageOut(
        chat_token=new_token,
        reply=reply,
        turns_used=turns_used,
        turns_limit=settings.CHAT_TURN_LIMIT,
        notice="masked" if masked.masked else None,
    )
