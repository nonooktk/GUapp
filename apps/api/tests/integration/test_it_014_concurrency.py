"""IT-014-02／03 同時実行（起動済み uvicorn へ httpx.AsyncClient で送る。テスト設計書 1.4）。

- #1 live_server（プール 20＋10）へ HTTP で送る
- #2 `/_test/metrics` の `inflight_max >= 2` を assert（同時性の証明）
- #3 MySQL であることは conftest が保証（`_validate_test_url`）、#4 schema は alembic upgrade head
- #5 成功側は全応答コードと注文番号、失敗側は `code` の値まで assert
- #6 在庫は「減少量 = 数量 × 1 回」で assert
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.mail import DEFAULT_OUTBOX_DIR
from tests.integration import order_helpers as oh
from tests.integration.live_server import LiveServer

CONCURRENCY = 20


@pytest.fixture
async def client(live_server: LiveServer, seed_db: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=live_server.base_url, timeout=30.0) as c:
        await c.post("/_test/reset")
        yield c


async def _metrics(client: httpx.AsyncClient) -> dict[str, int]:
    res = await client.get("/_test/metrics")
    assert res.status_code == 200, res.text
    return res.json()


async def test_it_014_02_same_key_20_concurrent_requests_yield_one_order(
    client: httpx.AsyncClient, seed_db: AsyncEngine, live_server: LiveServer
) -> None:
    token = await oh.new_token(client)
    vid = await oh.stocked_variant_id(seed_db, 5)
    await oh.add_item(client, token, vid, 2)
    prepared = await oh.prepare(client, token)
    before = await oh.stock_of(seed_db, vid)
    body = oh.order_body(prepared)

    started = time.perf_counter()
    responses = await asyncio.gather(
        *(client.post("/api/v1/orders", json=body, headers=oh.h(token)) for _ in range(CONCURRENCY))
    )
    elapsed = time.perf_counter() - started

    codes = sorted(r.status_code for r in responses)
    assert all(c in (200, 201) for c in codes), [(r.status_code, r.text) for r in responses]
    assert codes.count(201) == 1, codes  # 新規は 1 回だけ、残りは既存注文
    numbers = {r.json()["order_number"] for r in responses}
    assert len(numbers) == 1, numbers
    number = numbers.pop()
    assert all(r.json()["status"] == "accepted" for r in responses)

    assert await oh.count_rows(seed_db, "orders") == 1
    assert await oh.count_rows(seed_db, "order_items") == 1
    assert await oh.count_rows(seed_db, "payments") == 1
    assert await oh.stock_of(seed_db, vid) == before - 2  # 数量 × 1 回
    metrics = await _metrics(client)
    assert metrics["inflight_max"] >= 2, metrics
    assert metrics["inflight_now"] == 0
    (DEFAULT_OUTBOX_DIR / f"{number}.txt").unlink(missing_ok=True)
    print(f"\nIT-014-02: {CONCURRENCY} 同時 {elapsed:.2f}s inflight_max={metrics['inflight_max']}")


async def test_it_014_03_same_cart_two_keys_concurrent_one_201_one_already_ordered(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    token = await oh.new_token(client)
    vid = await oh.stocked_variant_id(seed_db, 5)
    await oh.add_item(client, token, vid, 1)
    prepared_a = await oh.prepare(client, token)
    prepared_b = await oh.prepare(client, token)
    assert prepared_a["idempotency_key"] != prepared_b["idempotency_key"]
    before = await oh.stock_of(seed_db, vid)

    started = time.perf_counter()
    ra, rb = await asyncio.gather(
        client.post("/api/v1/orders", json=oh.order_body(prepared_a), headers=oh.h(token)),
        client.post("/api/v1/orders", json=oh.order_body(prepared_b), headers=oh.h(token)),
    )
    elapsed = time.perf_counter() - started

    codes = sorted([ra.status_code, rb.status_code])
    assert codes == [201, 409], [(ra.status_code, ra.text), (rb.status_code, rb.text)]
    winner, loser = (ra, rb) if ra.status_code == 201 else (rb, ra)
    assert loser.json()["code"] == "already_ordered", loser.text  # out_of_stock ではない
    assert loser.json()["order_number"] == winner.json()["order_number"]

    assert await oh.count_rows(seed_db, "orders") == 1
    assert await oh.count_rows(seed_db, "order_items") == 1
    assert await oh.stock_of(seed_db, vid) == before - 1
    assert await oh.scalar(seed_db, "SELECT status FROM carts") == "ordered"
    metrics = await _metrics(client)
    assert metrics["inflight_max"] >= 2, metrics
    (DEFAULT_OUTBOX_DIR / f"{winner.json()['order_number']}.txt").unlink(missing_ok=True)
    print(f"\nIT-014-03: 2 同時 {elapsed:.2f}s inflight_max={metrics['inflight_max']}")
