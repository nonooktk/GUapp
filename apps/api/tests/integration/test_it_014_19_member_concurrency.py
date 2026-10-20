"""IT-014-19 同じ会員の別カート 2 つから、冪等キーを替えて同時に注文する（10 回反復）。

テスト設計書 1.4 の条件を満たす: #1 live_server（プール 20＋10）、#2 `/_test/metrics` の
`inflight_max >= 2`（満たさない試行は無効試行として数え、やり直す。3 回とも不成立なら赤）、
#3 MySQL、#4 `alembic upgrade head`、#5 失敗側の code まで assert（ここでは 2 本とも 201）。

設計仕様書 5.6 の「注文確定（会員。別カートの 2 本）」: `INSERT orders` が外部キーで carts・
members・stores の行を共有ロックし、`UPDATE carts`・`UPDATE variants`（variant_id 昇順）が排他。
共有ロックどうしは両立するので待たない。デッドロック（1213）が出ても再試行で成功すればよい
（回数をログから数えて表示する）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration import concurrency_helpers as ch
from tests.integration import order_helpers as oh
from tests.integration import p2b_helpers as ph
from tests.integration.live_server import LiveServer

ITERATIONS = 10
TEST_NAME = "IT-014-19"
RETRY_LOG_MARK = "注文確定でロック競合"


@pytest.fixture
async def client(live_server: LiveServer, seed_db: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=live_server.base_url, timeout=30.0) as c:
        await c.post("/_test/reset")
        yield c


async def _attempt(
    client: httpx.AsyncClient, engine: AsyncEngine, session_token: str, vid: int
) -> tuple[list[httpx.Response], dict[str, int], int]:
    """1 試行: 注文系の表を空にし、同じ会員の別カート 2 つの注文（店舗受け取り）を同時に送る。"""
    await ch.reset_order_tables(engine)
    await client.post("/_test/reset")
    pair = []
    for _ in range(2):
        cart_token, prepared = await ph.cart_with(client, engine, (5, 1), receive_method="store")
        pair.append((ph.store_body(prepared), ph.sess(session_token, cart_token)))
    before = await oh.stock_of(engine, vid)
    responses, _elapsed = await ch.post_pair_synchronized(client, "/api/v1/orders", pair)
    return responses, await ch.metrics(client), before


async def test_it_014_19_same_member_two_carts_concurrent_orders_both_succeed(
    client: httpx.AsyncClient, seed_db: AsyncEngine, live_server: LiveServer
) -> None:
    member_id = await ph.member_id_of(seed_db)
    session_token = await ph.make_session(seed_db, member_id)
    vid = await oh.stocked_variant_id(seed_db, 5)
    retries_before = live_server.log_path.read_text(encoding="utf-8").count(RETRY_LOG_MARK)

    for i in range(ITERATIONS):
        (responses, metrics, before) = await ch.run_until_concurrent(
            f"{TEST_NAME}#{i}",
            lambda: _attempt(client, seed_db, session_token, vid),
            metrics_of=lambda r: r[1],
        )
        assert [r.status_code for r in responses] == [201, 201], [
            (r.status_code, r.text) for r in responses
        ]
        assert metrics["inflight_max"] >= 2, metrics  # 有効試行の再確認（1.4 #2）
        assert all(r.json()["is_member_order"] is True for r in responses)
        codes = {r.json()["pickup_code"] for r in responses}
        assert len(codes) == 2, "受け取りコードは注文ごとに別（UNIQUE）"

        assert await oh.count_rows(seed_db, "orders") == 2
        assert await oh.count_rows(seed_db, "orders", "member_id = :m", m=member_id) == 2
        assert await oh.count_rows(seed_db, "order_items") == 2
        assert await oh.stock_of(seed_db, vid) == before - 2

    retries = (
        live_server.log_path.read_text(encoding="utf-8").count(RETRY_LOG_MARK) - retries_before
    )
    print(
        f"\n{TEST_NAME}: {ITERATIONS} 反復すべて 201×2。ロック競合の再試行 {retries} 回"
        f" 無効試行 {ch.invalid_attempts[TEST_NAME]} 回"
    )
