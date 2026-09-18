"""IT-014-04 在庫 1 の variant に別カートから同時 2 注文（有効試行 30 回。テスト設計書 1.4 #7）。

- live_server は `TEST_RESERVE_DELAY_MS=30` で起動（金額照合と引当の間に 30 ms の待ち）
- モジュール開始時に 1 回だけ seed し、ダミー注文 1 件で注文経路をウォームアップする
- 反復ごとにフル seed はせず、V-STOCK1 の stock を 1 に戻し、注文系 6 表を空にする
- 2 リクエストは `asyncio.Barrier` で送信を揃える（`concurrency_helpers.post_pair_synchronized`）
- **有効試行**（`inflight_max >= 2`。1.4 #2）だけを判定対象にする。同時性が成立しなかった試行は
  無効試行として数え、同じ反復をやり直す（1 反復あたり 3 回まで。3 回とも不成立なら赤）
- 判定条件は緩めない: 1 件 201・1 件 409 `out_of_stock`（500・タイムアウトは不合格）、stock == 0、
  order_items 1 行
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app import seed_data
from app.adapters.mail import DEFAULT_OUTBOX_DIR
from app.seed import seed, truncate_p1_tables
from tests.integration import concurrency_helpers as ch
from tests.integration import order_helpers as oh
from tests.integration.live_server import LiveServer

ITERATIONS = 30
TEST_NAME = "IT-014-04"

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


async def _warm_up_order_path(url: str, base_url: str) -> None:
    """注文確定の経路（カート→prepare→orders→決済スタブ→メール outbox）を 1 回通して温める。

    初回リクエストは import・プール接続・スキーマ構築で数百 ms 遅れ、2 本目と重ならないことがある。
    在庫の多い variant（V-STOCK1 ではない）で 1 件注文し、注文系の表はその場で空に戻す。
    """
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        vid = await oh.stocked_variant_id(engine, 1)
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            token = await oh.new_token(client)
            await oh.add_item(client, token, vid, 1)
            prepared = await oh.prepare(client, token)
            res = await client.post(
                "/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token)
            )
            assert res.status_code == 201, res.text
            (DEFAULT_OUTBOX_DIR / f"{res.json()['order_number']}.txt").unlink(missing_ok=True)
        await ch.reset_order_tables(engine)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def seeded_once(migrated_schema: str, live_server: LiveServer) -> Iterator[None]:
    """モジュールで 1 回だけ seed → ウォームアップ注文 1 件。終了時に TRUNCATE。

    同期フィクスチャ＋ `asyncio.run` にして、テストごとのイベントループと接続を混ぜない。
    """
    asyncio.run(_seed_once(migrated_schema))
    asyncio.run(_warm_up_order_path(migrated_schema, live_server.base_url))
    yield
    asyncio.run(_truncate_all(migrated_schema))


@pytest.fixture
async def race_engine(seeded_once: None, it_engine: AsyncEngine) -> AsyncEngine:
    return it_engine


async def _reset_iteration(engine: AsyncEngine, stock1_vid: int) -> None:
    await ch.reset_order_tables(engine)
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE variants SET stock = 1 WHERE id = :v"), {"v": stock1_vid})


async def _race_once(
    client: httpx.AsyncClient, engine: AsyncEngine, stock1: int
) -> tuple[list[httpx.Response], float, dict[str, int]]:
    """1 試行: 状態を戻し、別カート 2 つを作って同時に注文する。(応答 2 件, 所要秒, metrics)。"""
    await _reset_iteration(engine, stock1)
    await client.post("/_test/reset")
    token_a, token_b = await oh.new_token(client), await oh.new_token(client)
    await oh.add_item(client, token_a, stock1, 1)
    await oh.add_item(client, token_b, stock1, 1)
    prepared_a = await oh.prepare(client, token_a)
    prepared_b = await oh.prepare(client, token_b)

    responses, elapsed = await ch.post_pair_synchronized(
        client,
        "/api/v1/orders",
        [
            (oh.order_body(prepared_a), oh.h(token_a)),
            (oh.order_body(prepared_b), oh.h(token_b)),
        ],
    )
    return responses, elapsed, await ch.metrics(client)


@pytest.mark.parametrize("iteration", range(ITERATIONS))
async def test_it_014_04_two_carts_race_for_last_unit(
    iteration: int, live_server: LiveServer, race_engine: AsyncEngine
) -> None:
    stock1 = await oh.variant_id(race_engine, seed_data.TEST_SKU_STOCK1)

    async with httpx.AsyncClient(base_url=live_server.base_url, timeout=30.0) as client:
        # 同時性が成立した試行（有効試行）だけを判定対象にする。不成立は再試行（3 回まで）
        (ra, rb), elapsed, metrics = await ch.run_until_concurrent(
            TEST_NAME,
            lambda: _race_once(client, race_engine, stock1),
            metrics_of=lambda r: r[2],
        )

    # ここから判定（有効試行 1 回分。条件は 1.4 #5・#6 のまま緩めない）
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
    assert metrics["inflight_max"] >= 2, metrics  # 1.4 #2（有効試行の再確認）

    (DEFAULT_OUTBOX_DIR / f"{winner.json()['order_number']}.txt").unlink(missing_ok=True)
    _durations.append(elapsed)
    _inflight_max.append(metrics["inflight_max"])
    if iteration == ITERATIONS - 1:
        print(
            f"\n{TEST_NAME}: 有効試行 {ITERATIONS} 回 合計 {sum(_durations):.2f}s"
            f" 最大 {max(_durations):.3f}s inflight_max(min)={min(_inflight_max)}"
            f" 無効試行 {ch.invalid_attempts[TEST_NAME]} 回"
        )
