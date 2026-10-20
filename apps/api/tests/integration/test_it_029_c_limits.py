"""IT-029-15〜17・19〜21: 同時実行・タイムアウト・失敗・日次上限・IP の回数制限。

MySQL（guapp_test）＋ seed 必須。LLM は台本つきのアダプタ（遅延・例外を台本に入れる）。
同時実行は本編 1.4 の条件に従う: MySQL、同時処理中カウンタ（`testing_hooks`）、
`alembic upgrade head` 済みの schema。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC

import pytest

from app.core import testing_hooks
from app.core.rate_limit import SlidingWindowRateLimiter
from app.services import chat_guard
from tests.integration.chat_helpers import ChatCtx, log_text, send
from tests.unit.scripted_llm import ScriptedLLMAdapter, Step, fail, out

OK = out("clarify", "条件を教えてください。")


async def test_it_029_15_two_concurrent_requests_at_the_last_turn(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(Step(output=OK, delay=0.2))
    # 予約の直前に 100 ms の待ちを入れ、2 件が同時に予約へ来る窓を広げる（テスト設計書 1.4 #7）
    _, client = chat_ctx.build(adapter, TEST_RESERVE_DELAY_MS="100")
    first = await send(client, "質問1")
    token = first.json()["chat_token"]
    await chat_ctx.execute("UPDATE chat_sessions SET turns=9")
    before = (await chat_ctx.counts())["user_messages"]
    testing_hooks.allocation_counter.reset()

    responses = await asyncio.gather(
        send(client, "質問A", token=token), send(client, "質問B", token=token)
    )

    # 同時性の証明: 予約に 2 件が同時に居た
    assert testing_hooks.allocation_counter.max_seen >= 2
    assert sorted(r.status_code for r in responses) == [200, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json() == {"code": "turn_limit", "limit": 10}
    assert await chat_ctx.scalar("SELECT turns FROM chat_sessions") == 10
    assert (await chat_ctx.counts())["user_messages"] == before + 1
    assert adapter.calls == 2  # 1 回目 ＋ 勝った 1 件。負けた側は LLM を呼ばない


async def test_it_029_16_slow_llm_is_504_turn_is_restored_and_no_lock_is_held(
    chat_ctx: ChatCtx,
) -> None:
    adapter = ScriptedLLMAdapter(Step(output=OK, delay=5.0))
    # タイムアウトは最小の 1 秒（＋ 2 秒の外側の打ち切り）
    _, client = chat_ctx.build(adapter, OPENAI_TIMEOUT_SECONDS="1")
    started = time.monotonic()
    res = await send(client, "遅い質問")
    elapsed = time.monotonic() - started
    assert res.status_code == 504, res.text
    assert res.json() == {"code": "llm_timeout"}
    assert 2.5 <= elapsed < 4.5, elapsed
    assert await chat_ctx.scalar("SELECT turns FROM chat_sessions") == 0  # 戻される
    roles = [r[0] for r in await chat_ctx.rows("SELECT role FROM chat_messages ORDER BY id")]
    assert roles == ["user"]  # user 行は残り、assistant 行は無い
    # 日次の数え上げには含まれる
    assert (await chat_ctx.counts())["user_messages"] == 1


async def test_it_029_16_llm_timeout_error_is_504(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(fail("timeout"))
    _, client = chat_ctx.build(adapter)
    res = await send(client, "質問")
    assert res.status_code == 504 and res.json() == {"code": "llm_timeout"}
    assert await chat_ctx.scalar("SELECT turns FROM chat_sessions") == 0


async def test_it_029_16_no_db_lock_or_connection_is_held_while_waiting_for_the_llm(
    chat_ctx: ChatCtx,
) -> None:
    adapter = ScriptedLLMAdapter(Step(output=OK, delay=1.5), Step(output=OK, delay=0.0))
    # 共用 MySQL のプール 5/5 を想定した小さなプールでも、待っている間に接続を占有しない
    _, client = chat_ctx.build(adapter, DB_POOL_SIZE="1", DB_MAX_OVERFLOW="0")
    slow = asyncio.create_task(send(client, "遅い質問"))
    await asyncio.sleep(0.6)  # 遅い側が LLM を待っている間
    assert adapter.inflight == 1

    # (1) 別のセッションの送信が待たされない（接続を占有していれば、プール 1 本で詰まる）
    started = time.monotonic()
    fast = await send(client, "速い質問")
    assert fast.status_code == 200
    assert time.monotonic() - started < 1.0
    assert not slow.done()

    # (2) 遅い側のセッションの行ロックを持っていない（ロックがあれば 1 秒で待ち切れる）
    sid = await chat_ctx.scalar("SELECT id FROM chat_sessions ORDER BY id LIMIT 1")
    async with chat_ctx.engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text("SET SESSION innodb_lock_wait_timeout=1"))
        await conn.execute(text("UPDATE chat_sessions SET turns=turns WHERE id=:i"), {"i": sid})
    assert (await slow).status_code == 200


@pytest.mark.parametrize("kind", ["upstream", "incomplete", "invalid_output"])
async def test_it_029_17_llm_failures_are_502_and_turn_is_restored(
    chat_ctx: ChatCtx, kind: str
) -> None:
    adapter = ScriptedLLMAdapter(fail(kind))
    _, client = chat_ctx.build(adapter)
    res = await send(client, "質問")
    assert res.status_code == 502
    assert res.json() == {"code": "llm_error"}  # 例外の種類・メッセージは本文に出さない
    assert kind not in res.text
    assert await chat_ctx.scalar("SELECT turns FROM chat_sessions") == 0
    roles = [r[0] for r in await chat_ctx.rows("SELECT role FROM chat_messages")]
    assert roles == ["user"]


async def test_it_029_17_unexpected_exception_restores_turn_and_is_500(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(RuntimeError("sk-" + "x" * 30))
    _, client = chat_ctx.build(adapter)
    res = await send(client, "質問")
    assert res.status_code == 500
    assert res.json()["code"] == "internal_error"
    assert "sk-" not in res.text
    assert await chat_ctx.scalar("SELECT turns FROM chat_sessions") == 0


async def test_it_029_17_failed_call_can_be_retried_with_the_same_token(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(OK, fail("upstream"), OK)
    _, client = chat_ctx.build(adapter)
    token = (await send(client, "質問1")).json()["chat_token"]
    assert (await send(client, "質問2", token=token)).status_code == 502
    res = await send(client, "質問2", token=token)  # 再送
    assert res.status_code == 200
    assert res.json()["turns_used"] == 2  # 失敗分は数えない


async def test_it_029_19_five_sessions_at_once_do_not_deadlock(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(Step(output=OK, delay=0.3))
    _, client = chat_ctx.build(adapter, TEST_RESERVE_DELAY_MS="30")
    testing_hooks.allocation_counter.reset()
    responses = await asyncio.gather(*(send(client, f"質問{i}") for i in range(5)))
    assert [r.status_code for r in responses] == [200] * 5, [r.text for r in responses]
    assert testing_hooks.allocation_counter.max_seen >= 2
    assert adapter.max_inflight >= 2
    turns = [r[0] for r in await chat_ctx.rows("SELECT turns FROM chat_sessions")]
    assert turns == [1] * 5
    assert (await chat_ctx.counts())["messages"] == 10


async def test_it_029_20_daily_limit_exact_and_yesterday_not_counted(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(OK)
    _, client = chat_ctx.build(adapter, CHAT_DAILY_LIMIT="3")
    # 昨日（JST）の利用者メッセージ 5 行。今日の数え上げには入らない
    yesterday = chat_guard.jst_day_start_utc().replace(tzinfo=UTC)
    await chat_ctx.execute(
        "INSERT INTO chat_sessions (token_hash, turns) VALUES (:h, 0)", h="1" * 64
    )
    sid = await chat_ctx.scalar("SELECT id FROM chat_sessions")
    for _ in range(5):
        await chat_ctx.execute(
            "INSERT INTO chat_messages (chat_session_id, role, body_masked, created_at) "
            "VALUES (:s, 'user', '昨日の質問', DATE_SUB(:t, INTERVAL 1 HOUR))",
            s=sid,
            t=yesterday.replace(tzinfo=None),
        )

    for n in range(3):
        res = await send(client, f"質問{n}")
        assert res.status_code == 200, f"{n + 1} 回目: {res.text}"
    before = await chat_ctx.counts()
    res = await send(client, "4 回目")
    assert res.status_code == 503
    assert res.json() == {"code": "chat_daily_limit"}
    assert adapter.calls == 3  # LLM を呼ばない
    assert await chat_ctx.counts() == before  # DB に書かない


async def test_it_029_20_failed_call_counts_toward_the_daily_limit(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(fail("timeout"), OK)
    _, client = chat_ctx.build(adapter, CHAT_DAILY_LIMIT="2")
    assert (await send(client, "質問1")).status_code == 504  # 失敗しても数える
    assert (await send(client, "質問2")).status_code == 200
    res = await send(client, "質問3")
    assert res.status_code == 503 and res.json() == {"code": "chat_daily_limit"}


async def test_it_029_21_ip_rate_limit_per_ip(
    chat_ctx: ChatCtx, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    adapter = ScriptedLLMAdapter(OK)
    app, client = chat_ctx.build(adapter)
    app.state.chat_rate_limiter = SlidingWindowRateLimiter(limit=3, window_seconds=3600)

    for n in range(3):
        res = await send(client, f"質問{n}", ip="203.0.113.9")
        assert res.status_code == 200, res.text
    before = await chat_ctx.counts()

    res = await send(client, "4 回目", ip="203.0.113.9")
    assert res.status_code == 429
    assert res.json() == {"code": "rate_limited"}
    retry_after = res.headers["Retry-After"]
    assert retry_after.isdigit() and 1 <= int(retry_after) <= 3600
    assert await chat_ctx.counts() == before  # DB に書かない
    assert adapter.calls == 3
    logs = log_text(caplog)
    assert "request_rejected" in logs and "rate_limited" in logs
    assert "203.0.113.0" in logs and "203.0.113.9" not in logs  # IP は丸めた値

    other = await send(client, "別の IP", ip="203.0.113.10")
    assert other.status_code == 200


async def test_it_029_21_ip_limit_comes_before_validation_and_uses_settings(
    chat_ctx: ChatCtx,
) -> None:
    adapter = ScriptedLLMAdapter(OK)
    _, client = chat_ctx.build(adapter, CHAT_IP_LIMIT_PER_HOUR="1")
    assert (await send(client, "質問1", ip="198.51.100.7")).status_code == 200
    # 形の不正な本文でも、先に 429（判定順序 4.5: 429 → 400）
    res = await send(client, body={"message": ""}, ip="198.51.100.7")
    assert res.status_code == 429
    # 内部トークンが無ければ、回数制限より先に 401
    res = await send(client, "質問", ip="198.51.100.7", headers={})
    assert res.status_code == 401
