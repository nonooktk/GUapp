"""IT-014-04 在庫 1 の variant に別カートから同時 2 注文（30 回反復。テスト設計書 1.4 #7）。

- live_server は `TEST_RESERVE_DELAY_MS=10` で起動（金額照合と引当の間に 10 ms の待ち）
- 反復ごとにフル seed はせず、V-STOCK1 の stock を 1 に戻し、注文系 6 表を空にする
- 1 件 201・1 件 409 `out_of_stock`（500・タイムアウトは不合格）、stock == 0、order_items 1 行
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app import seed_data
from app.adapters.mail import DEFAULT_OUTBOX_DIR
from app.seed import seed, truncate_p1_tables
from tests.integration import order_helpers as oh
from tests.integration.live_server import LiveServer

ITERATIONS = 30
RESET_TABLES = ("payments", "order_items", "orders", "cart_items", "carts", "audit_logs")

_durations: list[float] = []
_inflight_max: list[int] = []


async def _seed_once(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        result = await seed(engine, reset=True)
        assert not result.skipped
    finally:
        await engine.dispose()


async def _truncate_all(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await truncate_p1_tables(conn)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def seeded_once(migrated_schema: str) -> Iterator[None]:
    """モジュールで 1 回だけ seed（反復ごとのフル seed はしない）。終了時に TRUNCATE。

    同期フィクスチャ＋ `asyncio.run` にして、テストごとのイベントループと接続を混ぜない。
    """
    asyncio.run(_seed_once(migrated_schema))
    yield
    asyncio.run(_truncate_all(migrated_schema))


@pytest.fixture
async def race_engine(seeded_once: None, it_engine: AsyncEngine) -> AsyncEngine:
    return it_engine


async def _reset_iteration(engine: AsyncEngine, stock1_vid: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        try:
            for name in RESET_TABLES:
                await conn.execute(text(f"TRUNCATE TABLE `{name}`"))
        finally:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        await conn.execute(text("UPDATE variants SET stock = 1 WHERE id = :v"), {"v": stock1_vid})


@pytest.mark.parametrize("iteration", range(ITERATIONS))
async def test_it_014_04_two_carts_race_for_last_unit(
    iteration: int, live_server: LiveServer, race_engine: AsyncEngine
) -> None:
    stock1 = await oh.variant_id(race_engine, seed_data.TEST_SKU_STOCK1)
    await _reset_iteration(race_engine, stock1)

    async with httpx.AsyncClient(base_url=live_server.base_url, timeout=30.0) as client:
        await client.post("/_test/reset")
        token_a, token_b = await oh.new_token(client), await oh.new_token(client)
        await oh.add_item(client, token_a, stock1, 1)
        await oh.add_item(client, token_b, stock1, 1)
        prepared_a = await oh.prepare(client, token_a)
        prepared_b = await oh.prepare(client, token_b)

        started = time.perf_counter()
        ra, rb = await asyncio.gather(
            client.post("/api/v1/orders", json=oh.order_body(prepared_a), headers=oh.h(token_a)),
            client.post("/api/v1/orders", json=oh.order_body(prepared_b), headers=oh.h(token_b)),
        )
        elapsed = time.perf_counter() - started
        metrics = (await client.get("/_test/metrics")).json()

    detail = [(ra.status_code, ra.text), (rb.status_code, rb.text)]
    codes = sorted([ra.status_code, rb.status_code])
    assert codes == [201, 409], detail  # 500・タイムアウトは不合格
    winner, loser = (ra, rb) if ra.status_code == 201 else (rb, ra)
    assert loser.json() == {"code": "out_of_stock", "items": [stock1]}, loser.text
    assert winner.json()["status"] == "accepted"

    assert await oh.stock_of(race_engine, stock1) == 0
    assert await oh.count_rows(race_engine, "orders") == 1
    assert await oh.count_rows(race_engine, "orders", "status='accepted'") == 1
    assert await oh.count_rows(race_engine, "order_items") == 1
    assert await oh.count_rows(race_engine, "payments") == 1
    # 負けたカートは active のまま（買い直せる）、勝ったカートは ordered
    assert await oh.count_rows(race_engine, "carts", "status='ordered'") == 1
    assert await oh.count_rows(race_engine, "carts", "status='active'") == 1
    assert metrics["inflight_max"] >= 2, metrics

    (DEFAULT_OUTBOX_DIR / f"{winner.json()['order_number']}.txt").unlink(missing_ok=True)
    _durations.append(elapsed)
    _inflight_max.append(metrics["inflight_max"])
    if iteration == ITERATIONS - 1:
        print(
            f"\nIT-014-04: {ITERATIONS} 回 合計 {sum(_durations):.2f}s"
            f" 最大 {max(_durations):.3f}s inflight_max(min)={min(_inflight_max)}"
        )
