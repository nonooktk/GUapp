"""DS-API-040・041 AI アシスタント。ルーターは入出力のみ（判断は `app.services.chat`）。

- IP の回数制限（30 回/時）は依存関数で最初に判定する（DS-DEC-104）。制限器は
  `app.state.chat_rate_limiter`（app ごとに 1 つ）。超過は 429 `rate_limited` ＋ `Retry-After`
- セッションはヘッダ `X-Chat-Token` で特定する。形式違反・未登録は「無し」と同じ扱いで 404 にしない
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMAdapter, get_llm_adapter
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.rate_limit import SlidingWindowRateLimiter, client_ip
from app.core.reject_log import log_rejection
from app.schemas.chat import ChatMessageIn, ChatMessageOut, ChatStatusOut
from app.services import chat as chat_service

router = APIRouter(prefix="/chat", tags=["chat"])

ChatToken = Annotated[str | None, Header(alias="X-Chat-Token")]


def chat_rate_limit(request: Request) -> None:
    """DS-PRC-029-4: IP ごとの回数制限。拒否は 1 行ログ（IP は丸めた値）。"""
    limiter: SlidingWindowRateLimiter = request.app.state.chat_rate_limiter
    ip = client_ip(request)
    retry_after = limiter.hit(ip)
    if retry_after is not None:
        log_rejection(request, status=429, code="rate_limited", ip=ip)
        raise AppError(429, "rate_limited", headers={"Retry-After": str(retry_after)})


@router.get("/status", response_model=ChatStatusOut, summary="DS-API-040 チャットの状態")
async def chat_status(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    adapter: LLMAdapter = Depends(get_llm_adapter),
) -> ChatStatusOut:
    return await chat_service.get_status(session, settings, adapter)


@router.post(
    "/messages",
    response_model=ChatMessageOut,
    dependencies=[Depends(chat_rate_limit)],
    summary="DS-API-041 質問の送信と回答（DS-PRC-029-1）",
)
async def post_chat_message(
    body: ChatMessageIn,
    x_chat_token: ChatToken = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    adapter: LLMAdapter = Depends(get_llm_adapter),
) -> ChatMessageOut:
    return await chat_service.post_message(session, settings, adapter, body, x_chat_token)
