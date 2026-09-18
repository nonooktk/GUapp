"""同時実行 IT（IT-014-02〜04）の同時性を作る・確かめるためのヘルパー（テスト設計書 1.4 #2・#7）。

- `post_pair_synchronized`: 2 本の POST を `asyncio.Barrier` で揃えて送る（送信直前まで同期）。
  リクエストは送信前に `build_request` で組み立て、JSON 化などの前処理を競合窓の外へ出す。
- `is_concurrent`: `/_test/metrics` の `inflight_max >= 2` か（1.4 #2 の「同時性の証明」）。
  満たさない試行は**無効試行**（防御の合否を判定できない）として数え、テスト側で再試行する。
  再試行は 1 反復あたり `MAX_ATTEMPTS` 回まで。全部不成立ならその反復は赤にする
  （同時性を作れない環境の問題を隠さない）。
- `invalid_attempts`: 無効試行のテスト別集計。conftest の `pytest_terminal_summary` で表示する。
- `reset_order_tables`: 注文系 6 表を空にする（反復・再試行の間の後始末。商品・在庫は触らない）。
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# 1 反復あたりの試行回数の上限（同時性が成立しなかったときの再試行を含む）
MAX_ATTEMPTS = 3

# 無効試行（inflight_max < 2）の集計: テスト名 → 回数
invalid_attempts: Counter[str] = Counter()

ORDER_TABLES = ("payments", "order_items", "orders", "cart_items", "carts", "audit_logs")


async def metrics(client: httpx.AsyncClient) -> dict[str, int]:
    res = await client.get("/_test/metrics")
    assert res.status_code == 200, res.text
    return res.json()


def is_concurrent(m: dict[str, int]) -> bool:
    """1.4 #2: 同時処理中カウンタの最大値が 2 以上なら競合が起きている。"""
    return m["inflight_max"] >= 2


async def post_pair_synchronized(
    client: httpx.AsyncClient,
    url: str,
    pair: list[tuple[dict[str, Any], dict[str, str]]],
) -> tuple[list[httpx.Response], float]:
    """`pair` の (json, headers) を Barrier で揃えて同時に POST する。(応答, 所要秒) を返す。"""
    requests = [
        client.build_request("POST", url, json=body, headers=headers) for body, headers in pair
    ]
    barrier = asyncio.Barrier(len(requests))

    async def _send(req: httpx.Request) -> httpx.Response:
        await barrier.wait()  # 全員が揃ってから送る
        return await client.send(req)

    started = time.perf_counter()
    responses = await asyncio.gather(*(_send(r) for r in requests))
    return list(responses), time.perf_counter() - started


def record_invalid_attempt(test_name: str, attempt: int, m: dict[str, int]) -> None:
    """無効試行を集計し、その場でも見えるように print する（`pytest -rA` / `-s` で表示）。"""
    invalid_attempts[test_name] += 1
    print(
        f"\n[無効試行] {test_name}: 試行 {attempt}/{MAX_ATTEMPTS} で"
        f" inflight_max={m['inflight_max']} (< 2) のため再試行"
    )


def concurrency_failure_message(test_name: str, history: list[dict[str, int]]) -> str:
    return (
        f"{test_name}: {MAX_ATTEMPTS} 回試行しても同時性が成立しませんでした"
        f"（inflight_max の履歴: {[m['inflight_max'] for m in history]}）。"
        " 1.4 #2 を満たせないため無効。live_server の負荷・TEST_RESERVE_DELAY_MS を確認してください"
    )


async def run_until_concurrent[T](
    test_name: str,
    attempt: Callable[[], Awaitable[T]],
    metrics_of: Callable[[T], dict[str, int]],
) -> T:
    """`attempt` を、同時性が成立する（inflight_max >= 2）まで最大 MAX_ATTEMPTS 回実行する。

    成立した試行の結果を返す（判定はその結果に対して行う）。不成立は無効試行として集計し、
    MAX_ATTEMPTS 回すべて不成立なら `pytest.fail`（環境の問題を隠さない）。
    `attempt` は毎回、状態を戻してから送るところまでを自分で行う。
    """
    history: list[dict[str, int]] = []
    for n in range(1, MAX_ATTEMPTS + 1):
        result = await attempt()
        m = metrics_of(result)
        history.append(m)
        if is_concurrent(m):
            return result
        record_invalid_attempt(test_name, n, m)
    pytest.fail(concurrency_failure_message(test_name, history))


async def reset_order_tables(engine: AsyncEngine) -> None:
    """注文系 6 表を TRUNCATE する（FK チェックを一時的に外す）。商品・在庫は変えない。"""
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        try:
            for name in ORDER_TABLES:
                await conn.execute(text(f"TRUNCATE TABLE `{name}`"))
        finally:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
