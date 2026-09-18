"""IT-023-01／02 ゲスト注文照会（番号＋メール一致・100 回/時/IP）。MySQL・seed 必須。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.mail import DEFAULT_OUTBOX_DIR
from tests.integration import order_helpers as oh


@pytest.fixture
async def client(it_app: FastAPI, seed_db: AsyncEngine, client_factory):
    return client_factory(it_app)


async def _place_order(client, engine: AsyncEngine) -> dict:
    token = await oh.new_token(client)
    vid = await oh.stocked_variant_id(engine, 5)
    await oh.add_item(client, token, vid, 1)
    prepared = await oh.prepare(client, token)
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(token))
    assert res.status_code == 201, res.text
    (DEFAULT_OUTBOX_DIR / f"{res.json()['order_number']}.txt").unlink(missing_ok=True)
    return res.json()


async def test_it_023_01_number_and_email_match_200_otherwise_404(client, seed_db) -> None:
    order = await _place_order(client, seed_db)
    number = order["order_number"]

    res = await client.post(
        f"/api/v1/orders/{number}/lookup", json={"guest_email": "test@example.com"}, headers=oh.h()
    )
    assert res.status_code == 200, res.text
    assert res.json() == order

    # メール不一致・番号不存在は区別せず 404
    res = await client.post(
        f"/api/v1/orders/{number}/lookup", json={"guest_email": "other@example.com"}, headers=oh.h()
    )
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    res = await client.post(
        "/api/v1/orders/GU-260918-ZZZZZZZZ/lookup",
        json={"guest_email": "test@example.com"},
        headers=oh.h(),
    )
    assert res.status_code == 404 and res.json() == {"code": "not_found"}

    # メール形式不正は 400（形の検証が先）
    res = await client.post(
        f"/api/v1/orders/{number}/lookup", json={"guest_email": "no-at"}, headers=oh.h()
    )
    assert res.status_code == 400
    assert res.json()["fields"] == [{"name": "guest_email", "reason": "format"}]

    # 内部トークン無しは 401
    res = await client.post(
        f"/api/v1/orders/{number}/lookup", json={"guest_email": "test@example.com"}
    )
    assert res.status_code == 401


async def test_it_023_02_100_requests_ok_101st_is_429_with_retry_after(client, seed_db) -> None:
    order = await _place_order(client, seed_db)
    url = f"/api/v1/orders/{order['order_number']}/lookup"
    payload = {"guest_email": "test@example.com"}

    for i in range(100):
        res = await client.post(url, json=payload, headers=oh.h())
        assert res.status_code == 200, f"{i + 1} 回目: {res.status_code} {res.text}"

    res = await client.post(url, json=payload, headers=oh.h())
    assert res.status_code == 429, res.text
    assert res.json() == {"code": "rate_limited"}
    retry_after = int(res.headers["Retry-After"])
    assert 1 <= retry_after <= 3600

    # 404 になる要求も回数に数える（列挙の総当たりを止めるため）
    res = await client.post(url, json={"guest_email": "x@example.com"}, headers=oh.h())
    assert res.status_code == 429

    # X-Forwarded-For で別 IP → 別カウント
    headers = {**oh.h(), "X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
    res = await client.post(url, json=payload, headers=headers)
    assert res.status_code == 200, res.text
