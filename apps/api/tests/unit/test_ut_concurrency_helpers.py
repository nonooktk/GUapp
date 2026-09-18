"""tests/integration/concurrency_helpers の単体テスト（MySQL 不要。httpx.MockTransport で確認）。

- `post_pair_synchronized` が 2 本を Barrier で揃えて送り、サーバー側で重なる（同時処理中 2）こと
- `is_concurrent` の境界（1 は無効、2 は有効）
- `record_invalid_attempt` が集計を増やし、`concurrency_failure_message` が履歴を含むこと
- `run_until_concurrent`: 不成立 2 回→成立で 3 回目の結果を返す／3 回とも不成立なら pytest.fail
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tests.integration import concurrency_helpers as ch


@pytest.fixture(autouse=True)
def _clear_tally() -> None:
    ch.invalid_attempts.clear()
    yield
    ch.invalid_attempts.clear()


async def test_post_pair_synchronized_sends_both_and_they_overlap() -> None:
    inflight = 0
    inflight_max = 0
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal inflight, inflight_max
        inflight += 1
        inflight_max = max(inflight_max, inflight)
        seen.append((request.headers["X-Cart-Token"], request.url.path))
        await asyncio.sleep(0.02)  # 処理中に相手が届く窓
        inflight -= 1
        return httpx.Response(201, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://t"
    ) as client:
        responses, elapsed = await ch.post_pair_synchronized(
            client,
            "/api/v1/orders",
            [({"k": 1}, {"X-Cart-Token": "a"}), ({"k": 2}, {"X-Cart-Token": "b"})],
        )

    assert [r.status_code for r in responses] == [201, 201]
    assert sorted(t for t, _ in seen) == ["a", "b"]
    assert all(path == "/api/v1/orders" for _, path in seen)
    assert inflight_max == 2  # Barrier で揃えたので重なる
    assert 0 < elapsed < 5


def test_is_concurrent_boundary() -> None:
    assert not ch.is_concurrent({"inflight_now": 0, "inflight_max": 1})
    assert ch.is_concurrent({"inflight_now": 0, "inflight_max": 2})


def test_record_invalid_attempt_counts_and_failure_message_has_history(capsys) -> None:
    m1 = {"inflight_now": 0, "inflight_max": 1}
    ch.record_invalid_attempt("IT-014-04", 1, m1)
    ch.record_invalid_attempt("IT-014-04", 2, m1)
    ch.record_invalid_attempt("IT-014-03", 1, m1)
    assert ch.invalid_attempts["IT-014-04"] == 2
    assert ch.invalid_attempts["IT-014-03"] == 1
    assert "[無効試行] IT-014-04: 試行 1/3" in capsys.readouterr().out

    msg = ch.concurrency_failure_message("IT-014-04", [m1, m1, m1])
    assert "IT-014-04" in msg
    assert "[1, 1, 1]" in msg
    assert str(ch.MAX_ATTEMPTS) in msg


async def test_run_until_concurrent_retries_then_returns_valid_result() -> None:
    calls = 0

    async def attempt() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"inflight_max": 1 if calls < 3 else 2, "n": calls}

    result = await ch.run_until_concurrent("X", attempt, metrics_of=lambda r: r)
    assert result == {"inflight_max": 2, "n": 3}  # 3 回目（有効試行）の結果が返る
    assert calls == 3
    assert ch.invalid_attempts["X"] == 2


async def test_run_until_concurrent_fails_after_max_attempts() -> None:
    calls = 0

    async def attempt() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"inflight_max": 1}

    with pytest.raises(pytest.fail.Exception, match="3 回試行しても同時性が成立しません"):
        await ch.run_until_concurrent("Y", attempt, metrics_of=lambda r: r)
    assert calls == ch.MAX_ATTEMPTS
    assert ch.invalid_attempts["Y"] == ch.MAX_ATTEMPTS


async def test_run_until_concurrent_returns_first_valid_without_retry() -> None:
    async def attempt() -> dict[str, int]:
        return {"inflight_max": 2}

    result = await ch.run_until_concurrent("Z", attempt, metrics_of=lambda r: r)
    assert result == {"inflight_max": 2}
    assert ch.invalid_attempts["Z"] == 0
