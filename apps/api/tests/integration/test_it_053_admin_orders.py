"""IT-053・053a・053b: 管理：注文 API の結合テスト（MySQL 必須）。

テスト設計書 P2 追補c 4.4 / 設計仕様書 P2 追補c 4.4・4.6・5.6・DS-DEC-113・117・118・124・125。

- 注文は DB へ直接入れる（`p2b_helpers.insert_order`。状態・日時・件数を作るための近道）。
  氏名・メール・電話はテスト用のダミー値
- IT-053b-07（同じ注文の同時更新）は、本編 1.4 の条件（MySQL・プール 20 以上・
  同時処理中カウンタの最大値が 2 以上・失敗側の `code` まで assert）で 10 回の有効試行を通す
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import get_engine
from app.repositories import admin_orders as admin_orders_repo
from tests.integration import admin_helpers as ah
from tests.integration import p2b_helpers as ph

ORDERS = "/api/v1/admin/orders"
MEMBER_EMAIL = ph.DEMO_MEMBER_EMAIL

# 応答のどこにも出してはいけないキー（ST-SEC-88。内部 ID・秘密・受け取りコード・完全な個人情報）
FORBIDDEN_KEYS = {
    "id",
    "member_id",
    "order_id",
    "store_id",
    "staff_id",
    "cart_id",
    "password_hash",
    "token_hash",
    "pickup_code",
    "guest_email",
    "ship_name",
    "ship_phone",
    "ship_postal_code",
    "ship_address",
    "idempotency_key",
}
# 詳細で出してよい個人情報のキー（一覧に出してはいけない）
LIST_FORBIDDEN_KEYS = FORBIDDEN_KEYS | {
    "name",
    "phone_masked",
    "postal_code",
    "address",
    "customer",
}

FULL_PHONE = "09012345678"  # insert_order が入れるダミー値
FULL_EMAIL = "test@example.com"


# ── フィクスチャ・ヘルパー ─────────────────────────────────────────────────────


@pytest.fixture
def admin_app(
    make_app: Callable[..., FastAPI], test_database_url: str, migrated_schema: str
) -> FastAPI:
    return make_app(APP_ENV="test", DATABASE_URL=test_database_url)


@pytest.fixture
async def client(
    admin_app: FastAPI,
    seed_db: AsyncEngine,
    client_factory: Callable[[FastAPI], httpx.AsyncClient],
) -> httpx.AsyncClient:
    return client_factory(admin_app)


@pytest.fixture
def engine(seed_db: AsyncEngine) -> AsyncEngine:
    return seed_db


@pytest.fixture
async def token(engine: AsyncEngine) -> str:
    staff_id = await ah.create_staff(engine, "orders-staff")
    return await ah.make_admin_session(engine, staff_id)


async def sql(engine: AsyncEngine, statement: str, **params: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return list(result.all()) if result.returns_rows else []


async def scalar(engine: AsyncEngine, statement: str, **params: Any) -> Any:
    return (await sql(engine, statement, **params))[0][0]


async def get_list(client: httpx.AsyncClient, token: str, **params: Any) -> httpx.Response:
    return await client.get(ORDERS, params=params, headers=ah.admin_headers(token))


async def get_detail(client: httpx.AsyncClient, token: str, number: str) -> httpx.Response:
    return await client.get(f"{ORDERS}/{number}", headers=ah.admin_headers(token))


async def patch_status(
    client: httpx.AsyncClient, token: str, number: str, body: Any
) -> httpx.Response:
    return await client.patch(
        f"{ORDERS}/{number}/status", json=body, headers=ah.admin_headers(token)
    )


async def new_order(engine: AsyncEngine, **kwargs: Any) -> str:
    kwargs.setdefault("member_id", None)
    return await ph.insert_order(engine, **kwargs)


async def audit_rows(engine: AsyncEngine, action: str, target: str | None = None) -> list[Any]:
    if target is None:
        return await sql(
            engine,
            "SELECT target_type, target_id, actor_type, actor_id, detail FROM audit_logs"
            " WHERE action = :a ORDER BY id",
            a=action,
        )
    return await sql(
        engine,
        "SELECT target_type, target_id, actor_type, actor_id, detail FROM audit_logs"
        " WHERE action = :a AND target_id = :t ORDER BY id",
        a=action,
        t=target,
    )


def detail_of(row: Any) -> dict[str, Any]:
    value = row.detail
    return json.loads(value) if isinstance(value, str) else value


async def order_columns(engine: AsyncEngine, number: str) -> tuple[Any, ...]:
    rows = await sql(
        engine,
        "SELECT status, tracking_number, receive_method, total, member_id, pickup_code,"
        " subtotal, shipping_fee, discount FROM orders WHERE order_number = :n",
        n=number,
    )
    return tuple(rows[0])


async def add_payment(engine: AsyncEngine, number: str, result: str = "ok") -> None:
    await sql(
        engine,
        "INSERT INTO payments (order_id, provider, provider_ref, amount, result, refunded_amount)"
        " SELECT id, 'stub', 'ref-1', total, :r, 0 FROM orders WHERE order_number = :n",
        r=result,
        n=number,
    )


def all_keys(value: Any) -> set[str]:
    """入れ子の dict・list から全キーを集める。"""
    keys: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(k)
            keys |= all_keys(v)
    elif isinstance(value, list):
        for v in value:
            keys |= all_keys(v)
    return keys


def numbers(res: httpx.Response) -> list[str]:
    return [i["order_number"] for i in res.json()["items"]]


def utc(*args: int) -> datetime:
    return datetime(*args)


# ── IT-053: 注文の検索 ────────────────────────────────────────────────────────


async def test_it_053_01_list_is_newest_first_with_masked_contact_and_no_pii(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    member_id = await ph.member_id_of(engine)
    older = await new_order(
        engine, member_id=member_id, created_at=utc(2026, 10, 1, 1), items=(("A", 2), ("B", 3))
    )
    store = await new_order(
        engine,
        receive_method="store",
        store_code="demo-tokyo",
        pickup_code="ABCD2345",
        created_at=utc(2026, 10, 3, 1),
        guest_email="taro.store@example.com",
    )
    newest = await new_order(engine, created_at=utc(2026, 10, 5, 1))
    res = await get_list(client, token)
    assert res.status_code == 200, res.text
    body = res.json()
    assert numbers(res) == [newest, store, older]
    assert (body["page"], body["per_page"], body["total"], body["has_more"]) == (1, 20, 3, False)
    rows = {i["order_number"]: i for i in body["items"]}
    assert set(rows[older]) == {
        "order_number",
        "ordered_at",
        "status",
        "status_label",
        "receive_method",
        "total",
        "item_count",
        "customer_type",
        "email_masked",
    }
    assert rows[older]["item_count"] == 5  # 数量の合計
    assert rows[older]["customer_type"] == "member"
    assert rows[older]["email_masked"] == "t***@example.com"
    assert rows[older]["total"] == 1990 * 5
    assert rows[older]["status"] == "accepted" and rows[older]["status_label"] == "受付済"
    assert rows[older]["ordered_at"].startswith("2026-10-01T01:00:00")  # UTC の ISO 8601
    assert rows[store]["customer_type"] == "guest"
    assert rows[store]["receive_method"] == "store"
    assert rows[store]["email_masked"] == "t***@example.com"
    # 氏名・電話・住所・内部 ID・受け取りコードのキーも値も無い
    assert not (all_keys(body) & LIST_FORBIDDEN_KEYS)
    for secret in (FULL_PHONE, "テスト 太郎", "千代田", "ABCD2345", FULL_EMAIL):
        assert secret not in res.text


async def test_it_053_01b_same_timestamp_orders_are_sorted_by_id_desc(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    at = utc(2026, 10, 5, 1)
    first = await new_order(engine, created_at=at)
    second = await new_order(engine, created_at=at)
    third = await new_order(engine, created_at=at)
    assert numbers(await get_list(client, token)) == [third, second, first]


async def test_it_053_02_status_and_receive_method_filters(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    by_status: dict[str, str] = {}
    for i, status in enumerate(
        [
            "pending_payment",
            "accepted",
            "preparing",
            "shipped",
            "delivered",
            "pickup_expired",
            "cancelled",
            "payment_failed",
        ]
    ):
        by_status[status] = await new_order(engine, status=status, created_at=utc(2026, 10, 1, i))
    store = await new_order(
        engine,
        receive_method="store",
        store_code="demo-tokyo",
        pickup_code="ABCD2345",
        status="accepted",
        created_at=utc(2026, 10, 2),
    )
    for status, number in by_status.items():
        res = await get_list(client, token, status=status)
        assert res.status_code == 200, res.text
        got = numbers(res)
        assert number in got
        assert all(i["status"] == status for i in res.json()["items"]), status
    assert len(numbers(await get_list(client, token, status="all"))) == 9
    assert len(numbers(await get_list(client, token))) == 9  # 既定は all
    assert numbers(await get_list(client, token, receive_method="store")) == [store]
    delivery = await get_list(client, token, receive_method="delivery")
    assert len(numbers(delivery)) == 8 and store not in numbers(delivery)
    assert len(numbers(await get_list(client, token, receive_method="all"))) == 9
    for bad in ({"status": "foo"}, {"status": "SHIPPED"}, {"receive_method": "pickup"}):
        res = await get_list(client, token, **bad)
        assert res.status_code == 400, (bad, res.text)
        assert res.json()["code"] == "validation_error"


async def test_it_053_03_period_is_jst_calendar_days_and_inclusive(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    # UTC 14:59:59 は JST 10/27 23:59:59、UTC 15:00:00 は JST 10/28 00:00:00
    last_of_27 = await new_order(engine, created_at=utc(2026, 10, 27, 14, 59, 59))
    first_of_28 = await new_order(engine, created_at=utc(2026, 10, 27, 15, 0, 0))
    assert numbers(await get_list(client, token, **{"from": "2026-10-27", "to": "2026-10-27"})) == [
        last_of_27
    ]
    assert numbers(await get_list(client, token, **{"from": "2026-10-28", "to": "2026-10-28"})) == [
        first_of_28
    ]
    both = await get_list(client, token, **{"from": "2026-10-27", "to": "2026-10-28"})
    assert numbers(both) == [first_of_28, last_of_27]
    # 片方だけ
    assert numbers(await get_list(client, token, **{"from": "2026-10-28"})) == [first_of_28]
    assert numbers(await get_list(client, token, to="2026-10-27")) == [last_of_27]
    assert numbers(await get_list(client, token, to="2026-10-26")) == []
    assert len(numbers(await get_list(client, token, **{"from": "2026-10-27"}))) == 2


async def test_it_053_04_order_number_exact_match_only(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    target = await new_order(engine)
    await new_order(engine)
    res = await get_list(client, token, order_number=target)
    assert numbers(res) == [target]
    # 小文字・前後の空白は大文字化・除去して完全一致する
    assert numbers(await get_list(client, token, order_number=f"  {target.lower()}  ")) == [target]
    # 形は正しいが存在しない番号は 0 件（一部の一致はしない）
    other = target[:-1] + ("A" if target[-1] != "A" else "B")
    res = await get_list(client, token, order_number=other)
    assert res.status_code == 200 and res.json()["items"] == [] and res.json()["total"] == 0
    # 形が不正: 一部だけ・I と O と 0 と 1・全角数字
    for bad in (
        "GU-1",
        target[:-3],
        "GU-260101-IIIIIIII",
        "GU-260101-OOOOOOOO",
        "GU-260101-AAAAAA01",
        "GU-２６０１０１-AAAAAAAA",
    ):
        res = await get_list(client, token, order_number=bad)
        assert res.status_code == 400, (bad, res.text)
        assert res.json()["code"] == "validation_error"
        assert res.json()["fields"] == [{"name": "order_number", "reason": "format"}]


async def test_it_053_05_email_exact_match_after_normalization(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    target = await new_order(engine, guest_email="taro@example.com")
    await new_order(engine, guest_email="hanako@example.com")
    await new_order(engine, guest_email="t\u00e0ro@example.com")  # アクセント記号違いは別のアドレス
    assert numbers(await get_list(client, token, email="taro@example.com")) == [target]
    # 大文字・全角・前後の空白は正規化して一致する
    assert numbers(await get_list(client, token, email="  TARO@Example.COM ")) == [target]
    assert numbers(await get_list(client, token, email="ｔａｒｏ＠ｅｘａｍｐｌｅ．ｃｏｍ")) == [
        target
    ]
    # 一部だけ（形は正しいが別のアドレス）は 0 件。部分一致はしない
    res = await get_list(client, token, email="tar@example.com")
    assert res.status_code == 200 and res.json()["items"] == []
    res = await get_list(client, token, email="taro@example.co")
    assert res.status_code == 200 and res.json()["items"] == []
    # 255 文字・形式不正は 400
    too_long = "a" * 243 + "@example.com"  # 255 文字
    assert len(too_long) == 255
    for bad in (too_long, "taro", "taro@", "@example.com", "ta ro@example.com"):
        res = await get_list(client, token, email=bad)
        assert res.status_code == 400, (bad, res.text)
        assert res.json()["code"] == "validation_error"
        assert res.json()["fields"][0]["name"] == "email"


async def test_it_053_05b_contact_email_of_member_orders_is_searchable(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    """会員の注文でも連絡先メール（`orders.guest_email`）で見つかる。"""
    member_id = await ph.member_id_of(engine)
    mine = await new_order(engine, member_id=member_id, guest_email=MEMBER_EMAIL)
    await new_order(engine, guest_email="other@example.com")
    res = await get_list(client, token, email=MEMBER_EMAIL)
    assert numbers(res) == [mine]
    assert res.json()["items"][0]["customer_type"] == "member"


async def test_it_053_06_filters_are_combined_with_and(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    hit = await new_order(
        engine, status="shipped", guest_email="taro@example.com", created_at=utc(2026, 10, 10, 1)
    )
    await new_order(
        engine, status="accepted", guest_email="taro@example.com", created_at=utc(2026, 10, 10, 2)
    )  # 状態が違う
    await new_order(
        engine, status="shipped", guest_email="taro@example.com", created_at=utc(2026, 9, 1)
    )  # 期間外
    await new_order(
        engine, status="shipped", guest_email="hanako@example.com", created_at=utc(2026, 10, 10, 3)
    )  # メールが違う
    await new_order(
        engine,
        status="shipped",
        receive_method="store",
        store_code="demo-tokyo",
        pickup_code="ABCD2345",
        guest_email="taro@example.com",
        created_at=utc(2026, 10, 10, 4),
    )  # 受け取り方法が違う
    res = await get_list(
        client,
        token,
        status="shipped",
        receive_method="delivery",
        email="taro@example.com",
        **{"from": "2026-10-01", "to": "2026-10-31"},
    )
    assert numbers(res) == [hit]
    assert res.json()["total"] == 1


async def test_it_053_07_period_combinations_are_422_and_invalid_dates_400(
    client: httpx.AsyncClient, token: str
) -> None:
    # from が to より後
    res = await get_list(client, token, **{"from": "2026-10-02", "to": "2026-10-01"})
    assert res.status_code == 422
    assert res.json() == {"code": "unsupported_value", "field": "to"}
    # 366 日（両端を含む。閏年の丸 1 年）は成功、367 日は 422
    res = await get_list(client, token, **{"from": "2028-01-01", "to": "2028-12-31"})
    assert res.status_code == 200, res.text
    res = await get_list(client, token, **{"from": "2028-01-01", "to": "2029-01-01"})
    assert res.status_code == 422
    assert res.json() == {"code": "limit_exceeded", "field": "to", "limit": 366}
    # 実在しない日付・形が違う日付は 400
    for key, value in (
        ("from", "2026-02-30"),
        ("to", "2026-13-01"),
        ("from", "2026/10/01"),
        ("to", "２０２６-１０-０１"),
        ("from", "2026-1-1"),
        ("to", "0001-01-01"),
    ):
        res = await get_list(client, token, **{key: value})
        assert res.status_code == 400, (key, value, res.text)
        assert res.json()["fields"] == [{"name": key, "reason": "format"}]


async def test_it_053_07b_400_is_checked_before_422(client: httpx.AsyncClient, token: str) -> None:
    """形の違反（400）と期間の組み合わせの違反（422）が同時にあれば 400（DS-DEC-124）。"""
    res = await get_list(
        client, token, **{"from": "2026-10-02", "to": "2026-10-01", "status": "foo"}
    )
    assert res.status_code == 400


async def test_it_053_08_paging(client: httpx.AsyncClient, engine: AsyncEngine, token: str) -> None:
    created = [
        await new_order(engine, created_at=utc(2026, 10, 1, h)) for h in range(5)
    ]  # 古い順に作る
    newest_first = list(reversed(created))
    res = await get_list(client, token, per_page=2, page=1)
    assert numbers(res) == newest_first[:2]
    assert (res.json()["total"], res.json()["has_more"]) == (5, True)
    res = await get_list(client, token, per_page=2, page=3)
    assert numbers(res) == newest_first[4:]
    assert res.json()["has_more"] is False
    res = await get_list(client, token, per_page=2, page=4)  # 最終ページの次
    assert res.status_code == 200
    assert res.json()["items"] == [] and res.json()["total"] == 5
    assert len(numbers(await get_list(client, token, per_page=1))) == 1
    assert len(numbers(await get_list(client, token, per_page=100))) == 5
    for bad in ({"per_page": 101}, {"per_page": 0}, {"page": 0}, {"page": "x"}):
        res = await get_list(client, token, **bad)
        assert res.status_code == 400, (bad, res.text)


@contextmanager
def count_statements() -> Iterator[list[str]]:
    """アプリのエンジンに流れる SQL を数える（管理セッションの検証の 2 文を除く）。"""
    statements: list[str] = []
    sync_engine = get_engine().sync_engine

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        compact = " ".join(statement.split()).lower()
        if "from sessions" in compact or "from staff" in compact:
            return
        statements.append(compact)

    event.listen(sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(sync_engine, "before_cursor_execute", record)


async def test_it_053_09_list_runs_three_queries_regardless_of_the_number_of_orders(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    counts: dict[int, int] = {}
    created = 0
    for target in (50, 200):
        while created < target:
            await new_order(
                engine,
                created_at=utc(2026, 9, 1 + created // 24 % 28, created % 24),
                items=(("A", 1),),
            )
            created += 1
        with count_statements() as statements:
            res = await get_list(client, token, per_page=100)
        assert res.status_code == 200, res.text
        assert res.json()["total"] == target
        assert len(res.json()["items"]) == min(100, target)
        counts[target] = len(statements)
        # 本体・件数・点数の集計の 3 回だけ
        assert any("count(" in s and "order_items" not in s for s in statements), statements
        assert any("order_items" in s and "group by" in s for s in statements), statements
    assert counts == {50: 3, 200: 3}


async def test_it_053_10_no_match_is_200_with_empty_items(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    await new_order(engine)
    res = await get_list(client, token, status="cancelled")
    assert res.status_code == 200
    assert res.json() == {"items": [], "page": 1, "per_page": 20, "total": 0, "has_more": False}


# ── IT-053a: 注文詳細 ─────────────────────────────────────────────────────────


async def test_it_053a_01_delivery_order_detail(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    member_id = await ph.member_id_of(engine)
    number = await new_order(
        engine,
        member_id=member_id,
        guest_email=MEMBER_EMAIL,
        items=(("白いTシャツ", 2), ("黒いパンツ", 1)),
        created_at=utc(2026, 10, 27, 14, 59, 59),
    )
    await add_payment(engine, number)
    res = await get_detail(client, token, number)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {
        "order_number",
        "ordered_at",
        "status",
        "status_label",
        "receive_method",
        "store",
        "items",
        "subtotal",
        "shipping_fee",
        "discount",
        "total",
        "tax_included",
        "tax_rate",
        "payment",
        "customer",
        "tracking_number",
        "available_transitions",
    }
    assert body["order_number"] == number
    assert (body["status"], body["status_label"]) == ("accepted", "受付済")
    assert body["receive_method"] == "delivery" and body["store"] is None
    assert body["items"] == [
        {
            "product_name": "白いTシャツ",
            "color": "黒",
            "size": "M",
            "unit_price": 1990,
            "quantity": 2,
        },
        {
            "product_name": "黒いパンツ",
            "color": "黒",
            "size": "M",
            "unit_price": 1990,
            "quantity": 1,
        },
    ]
    total = 1990 * 3
    assert (body["subtotal"], body["shipping_fee"], body["discount"], body["total"]) == (
        total,
        0,
        0,
        total,
    )
    assert body["tax_rate"] == "0.10"
    assert body["tax_included"] == total * 10 // 110  # DS-PRC-021 の計算と一致
    assert body["payment"] == {"provider": "stub", "result": "ok"}
    assert body["tracking_number"] is None
    assert body["customer"] == {
        "type": "member",
        "name": "テスト 太郎",
        "email_masked": "d***@example.com",
        "phone_masked": "*******5678",
        "postal_code": "1000001",
        "address": "東京都千代田区千代田1-1 テストビル101",
    }
    assert body["available_transitions"] == [
        {"status": "preparing", "label": "出荷準備中", "accepts_tracking_number": False}
    ]
    assert not (all_keys(body) & FORBIDDEN_KEYS)
    assert FULL_PHONE not in res.text and MEMBER_EMAIL not in res.text


async def test_it_053a_01b_detail_without_payment_or_for_a_guest(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    number = await new_order(engine, status="shipped", tracking_number="TRACK-9")
    body = (await get_detail(client, token, number)).json()
    assert body["payment"] is None
    assert body["customer"]["type"] == "guest"
    assert body["tracking_number"] == "TRACK-9"
    assert body["available_transitions"] == [
        {"status": "delivered", "label": "配達完了", "accepts_tracking_number": False}
    ]


async def test_it_053a_02_store_order_detail_has_store_and_no_pickup_code(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    number = await new_order(
        engine,
        receive_method="store",
        store_code="demo-tokyo",
        pickup_code="ABCD2345",
        status="preparing",
    )
    res = await get_detail(client, token, number)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["receive_method"] == "store"
    store = await sql(
        engine, "SELECT name, prefecture, address FROM stores WHERE code = 'demo-tokyo'"
    )
    assert body["store"] == {
        "name": store[0].name,
        "prefecture": store[0].prefecture,
        "address": store[0].address,
    }
    assert set(body["customer"]) == {"type", "name", "email_masked", "phone_masked"}
    assert body["tracking_number"] is None
    assert (body["status"], body["status_label"]) == ("preparing", "店舗へ準備中")
    assert body["available_transitions"] == [
        {
            "status": "shipped",
            "label": "店舗に到着（受け取り可能）",
            "accepts_tracking_number": False,
        }
    ]
    assert "pickup_code" not in all_keys(body)
    assert "ABCD2345" not in res.text
    assert not (all_keys(body) & FORBIDDEN_KEYS)


async def test_it_053a_03_malformed_and_unknown_numbers_are_the_same_404(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    real = await new_order(engine)
    responses = []
    for number in (
        "GU-260101-ZZZZZZZZ",  # 形は正しいが存在しない
        "GU-1",
        real.lower(),  # 小文字
        "GU-260101-AAAAAAA",  # 短い
        "GU-260101-AAAAAAAAA",  # 長い
        "GU-260101-AAAAAAI1",  # 使わない文字
        "GU-２６０１０１-AAAAAAAA",  # 全角数字
        "..%2F..%2Fetc",
    ):
        res = await get_detail(client, token, number)
        assert res.status_code == 404, (number, res.text)
        responses.append(res.json())
    assert all(r == {"code": "not_found"} for r in responses)
    assert await audit_rows(engine, "admin.order.view") == []


async def test_it_053a_04_every_view_is_audited_and_failure_returns_no_data(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    number = await new_order(engine, receive_method="delivery")
    for _ in range(2):
        assert (await get_detail(client, token, number)).status_code == 200
    rows = await audit_rows(engine, "admin.order.view")
    assert len(rows) == 2
    for row in rows:
        assert (row.target_type, row.target_id, row.actor_type) == ("order", number, "staff")
        assert detail_of(row) == {"receive_method": "delivery"}  # 個人情報は入らない
    # 一覧は個人情報の閲覧ではないので記録しない
    assert (await get_list(client, token)).status_code == 200
    assert len(await audit_rows(engine, "admin.order.view")) == 2

    # 監査ログの INSERT を失敗させる（DB のトリガー）。個人情報を返さず 500
    async with failing_audit_insert(engine, "admin.order.view"):
        res = await get_detail(client, token, number)
    assert res.status_code == 500
    assert res.json()["code"] == "internal_error"
    for secret in (FULL_PHONE, "テスト 太郎", "千代田", number):
        assert secret not in res.text
    assert len(await audit_rows(engine, "admin.order.view")) == 2  # 増えていない


@asynccontextmanager
async def failing_audit_insert(engine: AsyncEngine, action: str) -> AsyncIterator[None]:
    """指定した action の `audit_logs` の INSERT が失敗するトリガーを一時的に置く。"""
    name = "tg_it053_fail_audit"
    await sql(engine, f"DROP TRIGGER IF EXISTS {name}")
    await sql(
        engine,
        f"CREATE TRIGGER {name} BEFORE INSERT ON audit_logs FOR EACH ROW"
        f" IF NEW.action = '{action}' THEN"
        " SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit insert failed'; END IF",
    )
    try:
        yield
    finally:
        await sql(engine, f"DROP TRIGGER IF EXISTS {name}")


async def test_it_053a_06_available_transitions_for_all_states_and_methods(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    expected = {
        "accepted": ("preparing", {"delivery": "出荷準備中", "store": "店舗へ準備中"}),
        "preparing": (
            "shipped",
            {"delivery": "出荷済（配送中）", "store": "店舗に到着（受け取り可能）"},
        ),
        "shipped": ("delivered", {"delivery": "配達完了", "store": "受け渡し済"}),
    }
    states = [
        "pending_payment",
        "accepted",
        "preparing",
        "shipped",
        "delivered",
        "pickup_expired",
        "cancelled",
        "payment_failed",
    ]
    pickup = iter(f"PK{n:06d}" for n in range(100))
    for status in states:
        for method in ("delivery", "store"):
            kwargs: dict[str, Any] = {"status": status, "receive_method": method}
            if method == "store":
                kwargs.update(store_code="demo-tokyo", pickup_code=next(pickup))
            number = await new_order(engine, **kwargs)
            body = (await get_detail(client, token, number)).json()
            if status not in expected:
                assert body["available_transitions"] == [], (status, method)
                continue
            target, labels = expected[status]
            assert body["available_transitions"] == [
                {
                    "status": target,
                    "label": labels[method],
                    "accepts_tracking_number": target == "shipped" and method == "delivery",
                }
            ], (status, method)


# ── IT-053b: 注文状態の更新 ───────────────────────────────────────────────────


async def test_it_053b_01_delivery_flow_updates_status_tracking_and_customer_view(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    member_id = await ph.member_id_of(engine)
    member_token = await ph.make_session(engine, member_id)
    number = await new_order(engine, member_id=member_id)

    def customer_view() -> Any:
        return client.get(f"/api/v1/me/orders/{number}", headers=ph.sess(member_token))

    res = await patch_status(client, token, number, {"status": "preparing"})
    assert res.status_code == 200, res.text
    assert res.json() == {
        "order_number": number,
        "status": "preparing",
        "status_label": "出荷準備中",
        "tracking_number": None,
        "available_transitions": [
            {"status": "shipped", "label": "出荷済（配送中）", "accepts_tracking_number": True}
        ],
    }
    assert (await customer_view()).json()["status_label"] == "出荷準備中"

    res = await patch_status(client, token, number, {"status": "shipped", "tracking_number": "T-1"})
    assert res.status_code == 200, res.text
    assert res.json()["status_label"] == "出荷済（配送中）"
    assert res.json()["tracking_number"] == "T-1"
    assert res.json()["available_transitions"] == [
        {"status": "delivered", "label": "配達完了", "accepts_tracking_number": False}
    ]
    mine = (await customer_view()).json()
    assert (mine["status_label"], mine["tracking_number"]) == ("出荷済（配送中）", "T-1")

    res = await patch_status(client, token, number, {"status": "delivered"})
    assert res.status_code == 200, res.text
    assert res.json()["status_label"] == "配達完了"
    assert res.json()["tracking_number"] == "T-1"
    assert res.json()["available_transitions"] == []
    mine = (await customer_view()).json()
    assert (mine["status_label"], mine["tracking_number"]) == ("配達完了", "T-1")

    rows = await audit_rows(engine, "admin.order.status", number)
    assert len(rows) == 3
    details = [detail_of(r) for r in rows]
    assert details == [
        {
            "from": "accepted",
            "to": "preparing",
            "receive_method": "delivery",
            "tracking_number_set": False,
        },
        {
            "from": "preparing",
            "to": "shipped",
            "receive_method": "delivery",
            "tracking_number_set": True,
        },
        {
            "from": "shipped",
            "to": "delivered",
            "receive_method": "delivery",
            "tracking_number_set": False,
        },
    ]
    assert all((r.target_type, r.actor_type) == ("order", "staff") for r in rows)
    staff_id = await scalar(engine, "SELECT id FROM staff WHERE login_id = 'orders-staff'")
    assert all(r.actor_id == staff_id for r in rows)
    # 追跡番号そのものは監査ログに入らない
    assert all("T-1" not in json.dumps(d) for d in details)


async def test_it_053b_02_store_flow_and_customer_pickup_code(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    member_id = await ph.member_id_of(engine)
    member_token = await ph.make_session(engine, member_id)
    number = await new_order(
        engine,
        member_id=member_id,
        receive_method="store",
        store_code="demo-tokyo",
        pickup_code="ABCD2345",
    )

    def customer_view() -> Any:
        return client.get(f"/api/v1/me/orders/{number}", headers=ph.sess(member_token))

    expected = [
        ("preparing", "店舗へ準備中", "ABCD2345"),
        ("shipped", "店舗に到着（受け取り可能）", "ABCD2345"),
        ("delivered", "受け渡し済", None),
    ]
    for status, label, code in expected:
        res = await patch_status(client, token, number, {"status": status})
        assert res.status_code == 200, res.text
        assert res.json()["status_label"] == label
        assert res.json()["tracking_number"] is None
        assert "pickup_code" not in res.text and "ABCD2345" not in res.text
        mine = (await customer_view()).json()
        assert (mine["status_label"], mine["pickup_code"]) == (label, code)
    rows = await audit_rows(engine, "admin.order.status", number)
    assert [detail_of(r)["receive_method"] for r in rows] == ["store"] * 3


INVALID_TRANSITIONS = [
    ("accepted", "shipped"),
    ("accepted", "delivered"),
    ("preparing", "delivered"),
    ("preparing", "preparing"),
    ("shipped", "preparing"),
    ("delivered", "shipped"),
    ("cancelled", "preparing"),
    ("pending_payment", "preparing"),
    ("payment_failed", "shipped"),
    ("pickup_expired", "delivered"),
]


async def test_it_053b_03_transitions_not_in_the_table_are_409_and_leave_no_trace(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    for current, target in INVALID_TRANSITIONS:
        number = await new_order(engine, status=current, tracking_number=None)
        before = await order_columns(engine, number)
        res = await patch_status(client, token, number, {"status": target})
        assert res.status_code == 409, (current, target, res.text)
        assert res.json() == {"code": "invalid_transition", "from": current, "to": target}
        assert await order_columns(engine, number) == before, (current, target)
        assert await audit_rows(engine, "admin.order.status", number) == []


@pytest.mark.parametrize("current", ["accepted", "shipped"])
async def test_it_053b_04_unsupported_targets_are_422_regardless_of_current_state(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str, current: str
) -> None:
    number = await new_order(engine, status=current)
    before = await order_columns(engine, number)
    for target in ("cancelled", "pickup_expired", "payment_failed", "accepted", "pending_payment"):
        res = await patch_status(client, token, number, {"status": target})
        assert res.status_code == 422, (current, target, res.text)
        assert res.json() == {"code": "unsupported_value", "field": "status"}
    assert await order_columns(engine, number) == before
    assert await audit_rows(engine, "admin.order.status", number) == []


async def test_it_053b_05_status_must_be_one_of_the_eight_values(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    number = await new_order(engine)
    before = await order_columns(engine, number)
    for bad in ("foo", "", "SHIPPED", None, 5, True, ["preparing"]):
        res = await patch_status(client, token, number, {"status": bad})
        assert res.status_code == 400, (bad, res.text)
        assert res.json() == {
            "code": "validation_error",
            "fields": [{"name": "status", "reason": "format"}],
        }
    res = await patch_status(client, token, number, {})  # 必須欠落
    assert res.status_code == 400
    assert res.json()["fields"] == [{"name": "status", "reason": "required"}]
    assert await order_columns(engine, number) == before


async def test_it_053b_06_tracking_number_shape_and_where_it_may_be_attached(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    # 形: 50 文字・ハイフン入り・追跡番号なしは成功。51 文字・全角・空白入り・空文字は 400
    for value, ok in (
        ("A" * 50, True),
        ("AB-12-cd", True),
        (None, True),
        ("A" * 51, False),
        ("ＡＢ１２", False),
        ("AB 12", False),
        ("AB12\n", False),
        ("", False),
    ):
        number = await new_order(engine, status="preparing")
        body: dict[str, Any] = {"status": "shipped"}
        if value is not None:
            body["tracking_number"] = value
        res = await patch_status(client, token, number, body)
        if ok:
            assert res.status_code == 200, (value, res.text)
            assert res.json()["tracking_number"] == value
        else:
            assert res.status_code == 400, (value, res.text)
            assert res.json()["fields"] == [{"name": "tracking_number", "reason": "format"}]
            assert (await order_columns(engine, number))[0] == "preparing"
    # 追跡番号なしで出荷にした注文は、顧客側にも追跡番号が出ない（None のまま）
    # 店舗の注文・出荷以外への更新に付けると 422
    store = await new_order(
        engine,
        status="preparing",
        receive_method="store",
        store_code="demo-tokyo",
        pickup_code="ABCD2345",
    )
    accepted = await new_order(engine, status="accepted")
    shipped = await new_order(engine, status="shipped")
    for number, target in ((store, "shipped"), (accepted, "preparing"), (shipped, "delivered")):
        before = await order_columns(engine, number)
        res = await patch_status(
            client, token, number, {"status": target, "tracking_number": "T-1"}
        )
        assert res.status_code == 422, (number, target, res.text)
        assert res.json() == {"code": "unsupported_value", "field": "tracking_number"}
        assert await order_columns(engine, number) == before
        assert await audit_rows(engine, "admin.order.status", number) == []


class Inflight:
    """同時に処理中の件数の最大値（テスト設計書 1.4 #2 の「同時性の証明」）。"""

    def __init__(self) -> None:
        self.now = 0
        self.max = 0


def track_inflight(monkeypatch: pytest.MonkeyPatch, name: str, hold: float) -> Inflight:
    """`admin_orders_repo.<name>` を包んで同時処理中の件数を数え、`hold` 秒だけ窓を広げる。"""
    original = getattr(admin_orders_repo, name)
    counter = Inflight()

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        counter.now += 1
        counter.max = max(counter.max, counter.now)
        try:
            result = await original(*args, **kwargs)
            await asyncio.sleep(hold)  # 行ロックを持ったまま少し待つ（競合の窓を広げる）
            return result
        finally:
            counter.now -= 1

    monkeypatch.setattr(admin_orders_repo, name, wrapped)
    return counter


async def test_it_053b_07_ten_parallel_updates_of_the_same_order_succeed_exactly_once(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5.6・本編 1.4: 同じ `accepted` の注文に `preparing` を 10 並列。10 回の有効試行。"""
    number = await new_order(engine, status="accepted")
    inflight = track_inflight(monkeypatch, "get_for_update", hold=0.03)
    for round_no in range(10):
        await sql(engine, "UPDATE orders SET status = 'accepted' WHERE order_number = :n", n=number)
        await sql(engine, "DELETE FROM audit_logs WHERE action = 'admin.order.status'")
        inflight.max = 0
        results = await asyncio.gather(
            *(patch_status(client, token, number, {"status": "preparing"}) for _ in range(10))
        )
        assert inflight.max >= 2, f"round {round_no}: 同時性が成立していない（無効試行）"
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [409] * 9, (round_no, [(r.status_code, r.text) for r in results])
        losers = [r.json() for r in results if r.status_code == 409]
        assert all(
            b == {"code": "invalid_transition", "from": "preparing", "to": "preparing"}
            for b in losers
        ), losers
        assert (await order_columns(engine, number))[0] == "preparing"
        assert len(await audit_rows(engine, "admin.order.status", number)) == 1
    print(f"\nIT-053b-07: 10 回の有効試行 inflight_max={inflight.max}")


async def test_it_053b_08_existence_is_checked_before_target_and_auth_first(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    # 存在しない番号に未対応の更新先: 404（存在確認が先。422 ではない）
    res = await patch_status(client, token, "GU-260101-ZZZZZZZZ", {"status": "cancelled"})
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    # 形が違う番号も同じ 404
    res = await patch_status(client, token, "GU-1", {"status": "preparing"})
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    # 管理用セッションなしは 401（認証が最初）
    number = await new_order(engine)
    res = await client.patch(
        f"{ORDERS}/{number}/status", json={"status": "preparing"}, headers=ah.admin_headers()
    )
    assert res.status_code == 401 and res.json() == {"code": "unauthorized"}
    assert (await order_columns(engine, number))[0] == "accepted"
    # 400（本文の形）は 404 より先
    res = await patch_status(client, token, "GU-260101-ZZZZZZZZ", {"status": "foo"})
    assert res.status_code == 400
    # 会員のセッションは 403
    member_token = await ph.make_session(engine, await ph.member_id_of(engine))
    res = await patch_status(client, member_token, number, {"status": "preparing"})
    assert res.status_code == 403 and res.json() == {"code": "forbidden"}
    res = await get_detail(client, member_token, number)
    assert res.status_code == 403
    assert (await order_columns(engine, number))[0] == "accepted"


async def test_it_053b_09_second_shipped_update_keeps_the_first_tracking_number(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    number = await new_order(engine, status="preparing")
    res = await patch_status(client, token, number, {"status": "shipped", "tracking_number": "T-1"})
    assert res.status_code == 200
    res = await patch_status(client, token, number, {"status": "shipped", "tracking_number": "T-2"})
    assert res.status_code == 409
    assert res.json() == {"code": "invalid_transition", "from": "shipped", "to": "shipped"}
    assert (await order_columns(engine, number))[1] == "T-1"
    assert len(await audit_rows(engine, "admin.order.status", number)) == 1


async def test_it_053b_10_unknown_body_fields_are_ignored(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    member_id = await ph.member_id_of(engine)
    number = await new_order(engine, member_id=member_id)
    before = await order_columns(engine, number)
    res = await patch_status(
        client,
        token,
        number,
        {
            "status": "preparing",
            "receive_method": "store",
            "total": 1,
            "subtotal": 1,
            "member_id": 999,
            "pickup_code": "ZZZZ2222",
            "guest_email": "x@example.com",
            "ship_name": "x",
        },
    )
    assert res.status_code == 200, res.text
    after = await order_columns(engine, number)
    # 状態以外の列（受け取り方法・金額・会員・受け取りコード・追跡番号）は変わらない
    assert after[0] == "preparing"
    assert (after[1:]) == before[1:]
    assert await scalar(
        engine, "SELECT guest_email FROM orders WHERE order_number = :n", n=number
    ) == ("test@example.com")
    assert await scalar(
        engine, "SELECT ship_name FROM orders WHERE order_number = :n", n=number
    ) == ("テスト 太郎")


async def test_it_053b_11_audit_failure_rolls_back_the_status_update(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    """監査ログの INSERT が失敗したら更新ごと戻す（記録のない更新を残さない。ST-SEC-89）。"""
    number = await new_order(engine, status="preparing")
    async with failing_audit_insert(engine, "admin.order.status"):
        res = await patch_status(
            client, token, number, {"status": "shipped", "tracking_number": "T-1"}
        )
    assert res.status_code == 500
    assert res.json()["code"] == "internal_error"
    assert await order_columns(engine, number) == (
        "preparing",
        None,
        "delivery",
        1990,
        None,
        None,
        1990,
        0,
        0,
    )
    assert await audit_rows(engine, "admin.order.status", number) == []


async def test_it_053b_12_status_update_does_not_send_any_mail_or_touch_stock(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    """顧客へのメールは送らない・在庫は触らない（DS-DEC-117）。他の表が変わらないことで確かめる。"""
    number = await new_order(engine)
    stock_before = await sql(engine, "SELECT id, stock FROM variants ORDER BY id")
    restock_before = await scalar(engine, "SELECT COUNT(*) FROM restock_notifications")
    assert (await patch_status(client, token, number, {"status": "preparing"})).status_code == 200
    assert await sql(engine, "SELECT id, stock FROM variants ORDER BY id") == stock_before
    assert await scalar(engine, "SELECT COUNT(*) FROM restock_notifications") == restock_before
    assert (
        await scalar(engine, "SELECT COUNT(*) FROM audit_logs WHERE action <> 'admin.order.status'")
        == 0
    )


# ── 全応答の共通（ST-SEC-88）─────────────────────────────────────────────────


async def test_it_053_sec_no_response_leaks_internal_ids_or_full_personal_data(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    member_id = await ph.member_id_of(engine)
    delivery = await new_order(engine, member_id=member_id)
    store = await new_order(
        engine,
        receive_method="store",
        store_code="demo-tokyo",
        pickup_code="ABCD2345",
    )
    responses = [
        await get_list(client, token),
        await get_detail(client, token, delivery),
        await get_detail(client, token, store),
        await patch_status(client, token, delivery, {"status": "preparing"}),
        await patch_status(client, token, store, {"status": "preparing"}),
        await patch_status(client, token, store, {"status": "delivered"}),  # 409
        await patch_status(client, token, store, {"status": "cancelled"}),  # 422
    ]
    for res in responses:
        assert not (all_keys(res.json()) & FORBIDDEN_KEYS), res.text
        for secret in (FULL_PHONE, "ABCD2345", FULL_EMAIL):
            assert secret not in res.text
        assert res.headers["cache-control"] == "no-store"
