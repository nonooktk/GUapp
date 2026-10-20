"""IT-051・051a・051b・051c: 管理：商品・在庫 API（DS-API-051 系）の結合テスト。MySQL・seed 必須。

テスト設計書 P2 追補c 4.2 / 設計仕様書 P2 追補c 4.2・4.6・5.6。担当レーン: C-2。

- 管理者は `admin_helpers.create_staff`、セッションは `make_admin_session` で作る
- 再入荷の申込は `example.com` のダミーのメールを DB へ直接入れる
- メールは記録用アダプタ（`tests/recording_mail.py`）で読む。応答のあとの後処理（BackgroundTasks）は
  `httpx` の ASGI 経由では応答を返す前に終わる
- 同時実行（IT-051b-09・051c-07・051c-08）は MySQL・`alembic upgrade head`・プール 20 以上で
  行い、同時に処理中の件数の最大値が 2 以上であることを assert する（本編 1.4 #1〜#5）。
  10 回の有効試行を通す
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import seed_data
from app.core.db import get_engine
from app.repositories import admin_products as products_repo
from app.services import admin_products as products_service
from app.services.restock import notify_restock
from tests.integration import admin_helpers as ah
from tests.integration import order_helpers as oh
from tests.integration import p2b_helpers as ph
from tests.recording_mail import RecordingMailAdapter

WEB_BASE = "http://localhost:3000"
PREFIX = "/api/v1/admin"
PRODUCT_COUNT = seed_data.EXPECTED_PRODUCT_COUNT


# ── フィクスチャ・ヘルパー ───────────────────────────────────────────────────


@pytest.fixture
def admin_app(
    make_app: Callable[..., FastAPI],
    test_database_url: str,
    migrated_schema: str,
    recording_mail: RecordingMailAdapter,
) -> FastAPI:
    app = make_app(APP_ENV="test", DATABASE_URL=test_database_url, PUBLIC_WEB_BASE_URL=WEB_BASE)
    recording_mail.install(app)
    return app


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
    staff_id = await ah.create_staff(engine, "staff-c2")
    return await ah.make_admin_session(engine, staff_id)


async def sql(engine: AsyncEngine, statement: str, **params: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return list(result.all()) if result.returns_rows else []


async def scalar(engine: AsyncEngine, statement: str, **params: Any) -> Any:
    return (await sql(engine, statement, **params))[0][0]


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def audit_rows(engine: AsyncEngine, action: str) -> list[dict[str, Any]]:
    rows = await sql(
        engine,
        "SELECT actor_type, actor_id, action, target_type, target_id, detail FROM audit_logs"
        " WHERE action = :a ORDER BY id",
        a=action,
    )
    return [
        {
            "actor_type": r[0],
            "actor_id": r[1],
            "action": r[2],
            "target_type": r[3],
            "target_id": r[4],
            "detail": _json(r[5]),
        }
        for r in rows
    ]


async def get(client: httpx.AsyncClient, token: str | None, path: str, **params: Any):
    return await client.get(f"{PREFIX}{path}", params=params, headers=ah.admin_headers(token))


async def patch(client: httpx.AsyncClient, token: str | None, path: str, body: Any):
    return await client.patch(f"{PREFIX}{path}", json=body, headers=ah.admin_headers(token))


async def stock0_variant(engine: AsyncEngine) -> int:
    return await oh.variant_id(engine, seed_data.TEST_SKU_STOCK0)


async def register_rows(engine: AsyncEngine, vid: int, *emails: str, notified: bool = False):
    """再入荷の申込を直接入れる（`notified=True` は通知済み）。"""
    async with engine.begin() as conn:
        for email in emails:
            await conn.execute(
                text(
                    "INSERT INTO restock_notifications (variant_id, email, notified_at)"
                    " VALUES (:v, :e, " + ("NOW()" if notified else "NULL") + ")"
                ),
                {"v": vid, "e": email},
            )


class Inflight:
    """同時に処理中の件数の最大値（テスト設計書 1.4 #2 の「同時性の証明」）。"""

    def __init__(self) -> None:
        self.now = 0
        self.max = 0


def track_inflight(
    monkeypatch: pytest.MonkeyPatch, module: Any, name: str, hold: float = 0.0
) -> Inflight:
    """`module.name`（async 関数）を包んで同時処理中の件数を数え、`hold` 秒だけ窓を広げる。

    行ロックの取得（`FOR UPDATE`）を待っている件数も数える。`hold` は取得後にトランザクションを
    開いたまま待つ（競合の窓を広げる）。
    """
    original = getattr(module, name)
    counter = Inflight()

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        counter.now += 1
        counter.max = max(counter.max, counter.now)
        try:
            result = await original(*args, **kwargs)
            if hold:
                await asyncio.sleep(hold)
            return result
        finally:
            counter.now -= 1

    monkeypatch.setattr(module, name, wrapped)
    return counter


# ══════════════════════════════════════════════════════════════════════════
# IT-051 商品一覧
# ══════════════════════════════════════════════════════════════════════════


async def test_it_051_01_list_first_page_with_aggregates(
    client: httpx.AsyncClient, token: str
) -> None:
    res = await get(client, token, "/products")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == PRODUCT_COUNT
    assert (body["page"], body["per_page"], body["has_more"]) == (1, 20, True)
    ids = [i["product_id"] for i in body["items"]]
    assert len(ids) == 20 and ids == sorted(ids)
    first = body["items"][0]
    assert set(first) == {
        "product_id",
        "name",
        "price_incl_tax",
        "published",
        "variant_count",
        "total_stock",
        "out_of_stock_variants",
    }
    assert first["name"] == seed_data.PRODUCTS[0].name
    assert first["price_incl_tax"] == seed_data.PRODUCTS[0].price_incl_tax
    assert first["variant_count"] == 6 and first["total_stock"] > 0
    assert first["out_of_stock_variants"] == 0
    assert res.headers["cache-control"] == "no-store"
    # 商品 29（V-STOCK0 あり）と商品 28（全 SKU 在庫 0）の集計
    page2 = (await get(client, token, "/products", page=2)).json()
    by_id = {i["product_id"]: i for i in body["items"] + page2["items"]}
    assert by_id[29]["out_of_stock_variants"] >= 1
    assert by_id[28]["out_of_stock_variants"] == 6 and by_id[28]["total_stock"] == 0
    assert by_id[30]["published"] is False  # 非公開も管理者には出る
    assert len(page2["items"]) == PRODUCT_COUNT - 20 and page2["has_more"] is False


async def test_it_051_02_q_matches_name_part_and_sku_prefix(
    client: httpx.AsyncClient, token: str
) -> None:
    name = seed_data.PRODUCTS[0].name
    res = await get(client, token, "/products", q=name[:4])
    assert res.status_code == 200
    assert 1 in [i["product_id"] for i in res.json()["items"]]
    # SKU の前方一致（小文字でも一致する）
    for q in ("GU-029", "gu-029", "gu-029-bk-m"):
        ids = [
            i["product_id"] for i in (await get(client, token, "/products", q=q)).json()["items"]
        ]
        assert ids == [29], (q, ids)
    # 全角・前後空白は NFKC・strip のあとで照合
    ids = [
        i["product_id"]
        for i in (await get(client, token, "/products", q="　ＧＵ-029 ")).json()["items"]
    ]
    assert ids == [29]
    none = (await get(client, token, "/products", q="no-such-product-zzz")).json()
    assert none["items"] == [] and none["total"] == 0
    everything = (await get(client, token, "/products", q="")).json()
    assert everything["total"] == PRODUCT_COUNT
    # 51 文字は 400、50 文字は 200
    assert (await get(client, token, "/products", q="a" * 50)).status_code == 200
    too_long = await get(client, token, "/products", q="a" * 51)
    assert too_long.status_code == 400
    assert too_long.json() == {
        "code": "validation_error",
        "fields": [{"name": "q", "reason": "too_long"}],
    }


async def test_it_051_03_like_wildcards_are_literal(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    async with engine.begin() as conn:
        for i, name in enumerate(["100%綿 シャツ", "under_score シャツ", "back\\slash シャツ"]):
            await conn.execute(
                text(
                    "INSERT INTO products (name, description, material, price_incl_tax,"
                    " published, sort_order) VALUES (:n, '', '', 1000, 1, :s)"
                ),
                {"n": name, "s": 900 + i},
            )
    expect = {
        "%": ["100%綿 シャツ"],
        "_": ["under_score シャツ"],
        "\\": ["back\\slash シャツ"],
        "%%": [],
        "a%b": [],
    }
    for q, names in expect.items():
        res = await get(client, token, "/products", q=q)
        assert res.status_code == 200, (q, res.text)
        assert sorted(i["name"] for i in res.json()["items"]) == sorted(names), q


async def test_it_051_04_filters_and_enum_validation(client: httpx.AsyncClient, token: str) -> None:
    await patch(client, token, "/products/1", {"published": False, "expected_published": True})
    public = (await get(client, token, "/products", visibility="public", per_page=100)).json()
    private = (await get(client, token, "/products", visibility="private", per_page=100)).json()
    allv = (await get(client, token, "/products", visibility="all", per_page=100)).json()
    assert 1 not in [i["product_id"] for i in public["items"]]
    assert sorted(i["product_id"] for i in private["items"]) == [1, 30]
    assert public["total"] + private["total"] == allv["total"] == PRODUCT_COUNT
    out = (await get(client, token, "/products", stock="out", per_page=100)).json()
    out_ids = [i["product_id"] for i in out["items"]]
    assert (
        28 in out_ids
        and 29 in out_ids
        and all(i["out_of_stock_variants"] >= 1 for i in out["items"])
    )
    both = (await get(client, token, "/products", stock="out", visibility="private")).json()
    assert all(i["out_of_stock_variants"] >= 1 and not i["published"] for i in both["items"])
    for params in ({"visibility": "foo"}, {"stock": "bar"}, {"stock": "OUT"}):
        res = await get(client, token, "/products", **params)
        assert res.status_code == 400, params
        assert res.json()["code"] == "validation_error"


async def test_it_051_05_paging_boundaries(client: httpx.AsyncClient, token: str) -> None:
    assert (await get(client, token, "/products", per_page=1)).status_code == 200
    assert (await get(client, token, "/products", per_page=100)).status_code == 200
    for params in ({"per_page": 101}, {"per_page": 0}, {"page": 0}, {"page": "x"}):
        assert (await get(client, token, "/products", **params)).status_code == 400, params
    last = (await get(client, token, "/products", per_page=1, page=PRODUCT_COUNT + 1)).json()
    assert last["items"] == [] and last["total"] == PRODUCT_COUNT and last["has_more"] is False
    assert (await get(client, token, "/products", per_page=1, page=PRODUCT_COUNT)).json()[
        "has_more"
    ] is False


async def test_it_051_06_list_runs_two_queries_regardless_of_product_count(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", before)
    try:

        async def product_queries() -> int:
            statements.clear()
            res = await get(client, token, "/products", per_page=100)
            assert res.status_code == 200, res.text
            return sum(1 for s in statements if "FROM products" in s)

        assert await product_queries() == 2
        async with engine.begin() as conn:
            for i in range(270):
                result = await conn.execute(
                    text(
                        "INSERT INTO products (name, description, material, price_incl_tax,"
                        " published, sort_order) VALUES (:n, '', '', 1000, 1, 1000)"
                    ),
                    {"n": f"追加商品{i}"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO variants (product_id, color, size, sku, stock)"
                        " VALUES (:p, 'ブラック', 'M', :s, 3)"
                    ),
                    {"p": result.lastrowid, "s": f"ZZ-{i:04d}-BK-M"},
                )
        assert await product_queries() == 2
    finally:
        event.remove(sync_engine, "before_cursor_execute", before)


async def test_it_051_07_no_match_is_200_with_empty_items(
    client: httpx.AsyncClient, token: str
) -> None:
    res = await get(client, token, "/products", q="zzz", stock="out")
    assert res.status_code == 200
    assert res.json() == {"items": [], "page": 1, "per_page": 20, "total": 0, "has_more": False}


# ══════════════════════════════════════════════════════════════════════════
# IT-051a 商品詳細
# ══════════════════════════════════════════════════════════════════════════


async def test_it_051a_01_variants_with_waiting_counts_and_no_email(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    vid = await stock0_variant(engine)
    await register_rows(engine, vid, "a@example.com", "b@example.com")
    await register_rows(engine, vid, "done@example.com", notified=True)
    res = await get(client, token, "/products/29")
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {
        "product_id",
        "name",
        "price_incl_tax",
        "published",
        "updated_at",
        "variants",
    }
    assert body["product_id"] == 29 and body["published"] is True
    assert body["updated_at"].endswith("Z")
    ids = [v["variant_id"] for v in body["variants"]]
    assert ids == sorted(ids) and len(ids) == 6
    for v in body["variants"]:
        assert set(v) == {"variant_id", "sku", "color", "size", "stock", "restock_waiting"}
    target = next(v for v in body["variants"] if v["variant_id"] == vid)
    assert target["sku"] == seed_data.TEST_SKU_STOCK0 and target["stock"] == 0
    assert target["restock_waiting"] == 2  # 通知済みは数えない
    assert sum(v["restock_waiting"] for v in body["variants"]) == 2
    assert "@" not in res.text and "example.com" not in res.text


async def test_it_051a_02_unknown_is_404_and_unpublished_is_200(
    client: httpx.AsyncClient, token: str
) -> None:
    res = await get(client, token, "/products/999999")
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    res = await get(client, token, "/products/30")  # P-UNPUB
    assert res.status_code == 200 and res.json()["published"] is False


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "9223372036854775808"])
async def test_it_051a_03_bad_product_id_is_400(
    client: httpx.AsyncClient, token: str, bad: str
) -> None:
    res = await get(client, token, f"/products/{bad}")
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "validation_error"


# ══════════════════════════════════════════════════════════════════════════
# IT-051b 商品の更新
# ══════════════════════════════════════════════════════════════════════════


async def test_it_051b_01_unpublish_hides_from_public_and_audits(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    assert (await client.get("/api/v1/products/1", headers=oh.h())).status_code == 200
    res = await patch(
        client, token, "/products/1", {"published": False, "expected_published": True}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["changed"] is True and body["published"] is False and body["product_id"] == 1
    assert set(body) == {"product_id", "published", "price_incl_tax", "changed", "updated_at"}
    assert await scalar(engine, "SELECT published FROM products WHERE id=1") == 0
    assert (await client.get("/api/v1/products/1", headers=oh.h())).status_code == 404
    rows = await audit_rows(engine, "admin.product.update")
    assert len(rows) == 1
    staff_id = await scalar(engine, "SELECT id FROM staff WHERE login_id='staff-c2'")
    assert rows[0]["actor_type"] == "staff" and rows[0]["actor_id"] == staff_id
    assert (rows[0]["target_type"], rows[0]["target_id"]) == ("product", "1")
    assert rows[0]["detail"] == {"published": {"before": True, "after": False}}
    res = await patch(
        client, token, "/products/1", {"published": True, "expected_published": False}
    )
    assert res.status_code == 200 and res.json()["changed"] is True
    assert (await client.get("/api/v1/products/1", headers=oh.h())).status_code == 200
    assert len(await audit_rows(engine, "admin.product.update")) == 2


async def test_it_051b_02_price_change_reaches_public_and_keeps_past_orders(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    before = seed_data.PRODUCTS[0].price_incl_tax
    vid = await oh.stocked_variant_id(engine, 1)
    cart = await oh.new_token(client)
    await oh.add_item(client, cart, vid, 1)
    prepared = await oh.prepare(client, cart)
    res = await client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(cart))
    assert res.status_code == 201, res.text
    res = await patch(
        client, token, "/products/1", {"price_incl_tax": 2490, "expected_price_incl_tax": before}
    )
    assert res.status_code == 200 and res.json()["price_incl_tax"] == 2490
    detail = (await client.get("/api/v1/products/1", headers=oh.h())).json()
    assert detail["price_incl_tax"] == 2490
    (row,) = await audit_rows(engine, "admin.product.update")
    assert row["detail"] == {"price_incl_tax": {"before": before, "after": 2490}}
    assert await scalar(engine, "SELECT unit_price_at_order FROM order_items") == before


async def test_it_051b_03_stale_expected_is_409_and_nothing_changes(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    price = seed_data.PRODUCTS[0].price_incl_tax
    res = await patch(
        client, token, "/products/1", {"published": False, "expected_published": False}
    )
    assert res.status_code == 409
    assert res.json() == {"code": "stale_data", "field": "published", "current": True}
    res = await patch(
        client, token, "/products/1", {"price_incl_tax": 2000, "expected_price_incl_tax": 1}
    )
    assert res.status_code == 409
    assert res.json() == {"code": "stale_data", "field": "price_incl_tax", "current": price}
    # 片方だけ違う: もう一方（一致している側）も更新しない
    res = await patch(
        client,
        token,
        "/products/1",
        {
            "published": False,
            "expected_published": True,
            "price_incl_tax": 2000,
            "expected_price_incl_tax": 1,
        },
    )
    assert res.status_code == 409 and res.json()["field"] == "price_incl_tax"
    row = (await sql(engine, "SELECT published, price_incl_tax FROM products WHERE id=1"))[0]
    assert (row[0], row[1]) == (1, price)
    assert await audit_rows(engine, "admin.product.update") == []


@pytest.mark.parametrize(
    ("body", "expected_fields"),
    [
        ({"published": False}, [{"name": "expected_published", "reason": "required"}]),
        ({"price_incl_tax": 2000}, [{"name": "expected_price_incl_tax", "reason": "required"}]),
        ({}, [{"name": "body", "reason": "required"}]),
        (
            {"expected_published": True, "expected_price_incl_tax": 1},
            [{"name": "body", "reason": "required"}],
        ),
        (
            {"published": "true", "expected_published": True},
            [{"name": "published", "reason": "format"}],
        ),
        (
            {"published": None, "price_incl_tax": 100, "expected_price_incl_tax": 1},
            [{"name": "published", "reason": "format"}],
        ),
        (
            {"price_incl_tax": "1990", "expected_price_incl_tax": 1},
            [{"name": "price_incl_tax", "reason": "format"}],
        ),
        (
            {"price_incl_tax": 1990.5, "expected_price_incl_tax": 1},
            [{"name": "price_incl_tax", "reason": "format"}],
        ),
        (
            {"price_incl_tax": 2147483648, "expected_price_incl_tax": 1},
            [{"name": "price_incl_tax", "reason": "out_of_range"}],
        ),
    ],
)
async def test_it_051b_04_bad_bodies_are_400(
    client: httpx.AsyncClient, token: str, body: dict[str, Any], expected_fields: list[dict]
) -> None:
    res = await patch(client, token, "/products/1", body)
    assert res.status_code == 400, res.text
    assert res.json() == {"code": "validation_error", "fields": expected_fields}


async def test_it_051b_05_price_range(client: httpx.AsyncClient, engine: AsyncEngine, token: str):
    price = seed_data.PRODUCTS[0].price_incl_tax

    async def put(value: int, expected: int):
        return await patch(
            client,
            token,
            "/products/1",
            {"price_incl_tax": value, "expected_price_incl_tax": expected},
        )

    res = await put(0, price)
    assert res.status_code == 422
    assert res.json() == {"code": "unsupported_value", "field": "price_incl_tax"}
    assert (await put(1, price)).status_code == 200
    assert (await put(1_000_000, 1)).status_code == 200
    res = await put(1_000_001, 1_000_000)
    assert res.status_code == 422
    assert res.json() == {"code": "limit_exceeded", "field": "price_incl_tax", "limit": 1_000_000}
    assert await scalar(engine, "SELECT price_incl_tax FROM products WHERE id=1") == 1_000_000


async def test_it_051b_06_same_values_are_not_a_change(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    price = seed_data.PRODUCTS[0].price_incl_tax
    before = await scalar(engine, "SELECT updated_at FROM products WHERE id=1")
    res = await patch(
        client,
        token,
        "/products/1",
        {
            "published": True,
            "expected_published": True,
            "price_incl_tax": price,
            "expected_price_incl_tax": price,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (
        body["changed"] is False and body["published"] is True and body["price_incl_tax"] == price
    )
    assert await audit_rows(engine, "admin.product.update") == []
    assert await scalar(engine, "SELECT updated_at FROM products WHERE id=1") == before
    # 片方だけ変える: 変えた項目だけ監査ログに残る
    res = await patch(
        client,
        token,
        "/products/1",
        {
            "published": True,
            "expected_published": True,
            "price_incl_tax": 1234,
            "expected_price_incl_tax": price,
        },
    )
    assert res.status_code == 200 and res.json()["changed"] is True
    (row,) = await audit_rows(engine, "admin.product.update")
    assert row["detail"] == {"price_incl_tax": {"before": price, "after": 1234}}


async def test_it_051b_07_extra_fields_are_ignored(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    before = (await sql(engine, "SELECT name, description, material FROM products WHERE id=1"))[0]
    res = await patch(
        client,
        token,
        "/products/1",
        {
            "published": False,
            "expected_published": True,
            "name": "乗っ取り",
            "id": 2,
            "description": "x",
            "role": "admin",
        },
    )
    assert res.status_code == 200, res.text
    assert (await sql(engine, "SELECT name, description, material FROM products WHERE id=1"))[
        0
    ] == before
    assert await scalar(engine, "SELECT COUNT(*) FROM products WHERE name='乗っ取り'") == 0
    assert await scalar(engine, "SELECT published FROM products WHERE id=2") == 1


async def test_it_051b_08_unknown_product_is_404_and_zero_id_is_400(
    client: httpx.AsyncClient, token: str
) -> None:
    body = {"published": False, "expected_published": True}
    res = await patch(client, token, "/products/999999", body)
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    assert (await patch(client, token, "/products/0", body)).status_code == 400


async def test_it_051b_09_ten_parallel_unpublish_one_wins(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同じ商品の `published` を真から偽へ 10 並列。1 本が 200、9 本が 409。監査ログは 1 行。"""
    inflight = track_inflight(monkeypatch, products_repo, "get_product_for_update", hold=0.03)
    for round_no in range(10):
        await sql(engine, "UPDATE products SET published = 1 WHERE id = 1")
        await sql(engine, "DELETE FROM audit_logs")
        inflight.max = 0
        body = {"published": False, "expected_published": True}
        results = await asyncio.gather(
            *(patch(client, token, "/products/1", body) for _ in range(10))
        )
        assert inflight.max >= 2, f"同時性が成立していない（無効試行）: {inflight.max}"
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [409] * 9, (round_no, [(r.status_code, r.text) for r in results])
        assert all(r.json()["code"] == "stale_data" for r in results if r.status_code == 409)
        assert len(await audit_rows(engine, "admin.product.update")) == 1, round_no


async def test_it_051b_10_order_of_checks(client: httpx.AsyncClient, token: str) -> None:
    # 存在しない商品に価格 0 を送る: 404（存在確認が業務の範囲の検査より先）
    res = await patch(
        client, token, "/products/999999", {"price_incl_tax": 0, "expected_price_incl_tax": 1}
    )
    assert res.status_code == 404
    # 管理用セッションなしで不正な本文: 401（認証が最初）
    res = await patch(client, None, "/products/1", {"published": "x"})
    assert res.status_code == 401
    # 範囲外の価格と古い expected: 422 が 409 より先
    res = await patch(
        client, token, "/products/1", {"price_incl_tax": 0, "expected_price_incl_tax": 1}
    )
    assert res.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# IT-051c 在庫の更新
# ══════════════════════════════════════════════════════════════════════════


async def set_stock(
    client: httpx.AsyncClient, token: str | None, vid: Any, stock: Any, expected: Any = ...
):
    body: dict[str, Any] = {"stock": stock}
    if expected is not ...:
        body["expected_stock"] = expected
    return await patch(client, token, f"/variants/{vid}/stock", body)


async def test_it_051c_01_set_without_applicants(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    recording_mail: RecordingMailAdapter,
) -> None:
    vid = await stock0_variant(engine)
    res = await set_stock(client, token, vid, 5, 0)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "variant_id": vid,
        "sku": seed_data.TEST_SKU_STOCK0,
        "stock": 5,
        "previous_stock": 0,
        "changed": True,
        "restock_waiting": 0,
    }
    assert await oh.stock_of(engine, vid) == 5
    (row,) = await audit_rows(engine, "admin.stock.set")
    assert (row["target_type"], row["target_id"]) == ("variant", str(vid))
    assert row["actor_type"] == "staff"
    assert row["detail"] == {
        "sku": seed_data.TEST_SKU_STOCK0,
        "before": 0,
        "after": 5,
        "restock_waiting": 0,
    }
    assert recording_mail.of_kind("restock_notice") == []


async def test_it_051c_02_restock_notifies_each_applicant_after_commit(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    recording_mail: RecordingMailAdapter,
) -> None:
    vid = await stock0_variant(engine)
    emails = ["a@example.com", "b@example.com", "c@example.com"]
    await register_rows(engine, vid, *emails)
    res = await set_stock(client, token, vid, 5, 0)
    assert res.status_code == 200, res.text
    assert res.json()["restock_waiting"] == 3 and res.json()["changed"] is True
    mails = recording_mail.of_kind("restock_notice")
    assert sorted(m.to for m in mails) == emails
    product_id = await scalar(engine, "SELECT product_id FROM variants WHERE id=:v", v=vid)
    assert all(m.args["url"] == f"{WEB_BASE}/products/{product_id}" for m in mails)
    notified = await sql(engine, "SELECT notified_at FROM restock_notifications")
    assert len(notified) == 3 and all(r[0] is not None for r in notified)
    (stock_row,) = await audit_rows(engine, "admin.stock.set")
    assert stock_row["detail"]["restock_waiting"] == 3
    (notified_row,) = await audit_rows(engine, "restock.notified")
    assert notified_row["actor_type"] == "system" and notified_row["detail"] == {"count": 3}


async def test_it_051c_03_only_zero_to_positive_starts_notification(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    recording_mail: RecordingMailAdapter,
) -> None:
    vid = await stock0_variant(engine)
    await register_rows(engine, vid, "a@example.com", "b@example.com", "c@example.com")
    cases = [(5, 0, True), (3, 8, True), (0, 0, False), (8, 8, False)]
    current = 0
    for start, new, changed in cases:
        await oh.set_stock(engine, vid, start)
        before = len(await audit_rows(engine, "admin.stock.set"))
        res = await set_stock(client, token, vid, new, start)
        assert res.status_code == 200, res.text
        assert res.json()["changed"] is changed and res.json()["previous_stock"] == start
        assert res.json()["restock_waiting"] == 0
        assert len(await audit_rows(engine, "admin.stock.set")) == before + (1 if changed else 0)
        assert recording_mail.sent == []
        current = new
    assert await oh.stock_of(engine, vid) == current
    assert all(
        r[0] is None for r in await sql(engine, "SELECT notified_at FROM restock_notifications")
    )


async def test_it_051c_04_stale_expected_is_409_without_notification(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    recording_mail: RecordingMailAdapter,
) -> None:
    vid = await stock0_variant(engine)
    await register_rows(engine, vid, "a@example.com")
    res = await set_stock(client, token, vid, 5, 3)
    assert res.status_code == 409
    assert res.json() == {"code": "stale_data", "field": "stock", "current": 0}
    assert await oh.stock_of(engine, vid) == 0
    assert await audit_rows(engine, "admin.stock.set") == []
    assert recording_mail.sent == []


@pytest.mark.parametrize(
    ("stock", "expected_status", "expected_body"),
    [
        (-1, 422, {"code": "unsupported_value", "field": "stock"}),
        (0, 200, None),
        (9999, 200, None),
        (10000, 422, {"code": "limit_exceeded", "field": "stock", "limit": 9999}),
        (2147483647, 422, {"code": "limit_exceeded", "field": "stock", "limit": 9999}),
        (2147483648, 400, None),
        (5.5, 400, None),
        ("5", 400, None),
        (True, 400, None),
        (None, 400, None),
    ],
)
async def test_it_051c_05_stock_boundaries(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    stock: Any,
    expected_status: int,
    expected_body: dict | None,
) -> None:
    vid = await oh.stocked_variant_id(engine, 3)
    current = await oh.stock_of(engine, vid)
    res = await set_stock(client, token, vid, stock, current)
    assert res.status_code == expected_status, res.text
    if expected_body is not None:
        assert res.json() == expected_body
    if expected_status == 400:
        assert res.json()["code"] == "validation_error"
    if expected_status != 200:
        assert await oh.stock_of(engine, vid) == current


async def test_it_051c_05b_expected_stock_must_be_valid(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    vid = await oh.stocked_variant_id(engine, 3)
    res = await set_stock(client, token, vid, 5)  # expected_stock の欠落
    assert res.status_code == 400
    assert res.json() == {
        "code": "validation_error",
        "fields": [{"name": "expected_stock", "reason": "required"}],
    }
    for bad in (-1, 2147483648, "5", None, True, 1.5):
        assert (await set_stock(client, token, vid, 5, bad)).status_code == 400, bad


async def test_it_051c_06_stock_back_to_zero_before_background_runs(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    recording_mail: RecordingMailAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """後処理が動く前に在庫を 0 へ戻す。1 回目の後処理は何も送らず、申込は未通知のまま残る。"""
    vid = await stock0_variant(engine)
    await register_rows(engine, vid, "a@example.com", "b@example.com")
    held: list[int] = []

    async def hold(session: Any, variant_id: int, *, mail: Any) -> int:
        held.append(variant_id)  # 実行を保留する（あとで動かす）
        return 0

    monkeypatch.setattr(products_service, "notify_restock", hold)
    res = await set_stock(client, token, vid, 5, 0)
    assert res.status_code == 200 and res.json()["restock_waiting"] == 2
    assert held == [vid] and recording_mail.sent == []
    await oh.set_stock(engine, vid, 0)  # 後処理の前に在庫が 0 へ戻る
    async with AsyncSession(engine, expire_on_commit=False) as session:
        assert await notify_restock(session, vid, mail=recording_mail) == 0
    assert recording_mail.sent == []
    assert all(
        r[0] is None for r in await sql(engine, "SELECT notified_at FROM restock_notifications")
    )
    # そのあと 0→3 にすると、申込者に送信される
    monkeypatch.setattr(products_service, "notify_restock", notify_restock)
    res = await set_stock(client, token, vid, 3, 0)
    assert res.status_code == 200 and res.json()["restock_waiting"] == 2
    assert sorted(m.to for m in recording_mail.of_kind("restock_notice")) == [
        "a@example.com",
        "b@example.com",
    ]


async def test_it_051c_07_ten_parallel_restock_updates_send_mail_once(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    recording_mail: RecordingMailAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """申込 3 件の同じバリエーションに `expected_stock: 0`・`stock: 5` を 10 並列。"""
    vid = await stock0_variant(engine)
    inflight = track_inflight(monkeypatch, products_repo, "get_variant_for_update", hold=0.03)
    for round_no in range(10):
        await oh.set_stock(engine, vid, 0)
        await sql(engine, "DELETE FROM restock_notifications")
        await sql(engine, "DELETE FROM audit_logs")
        await register_rows(engine, vid, "a@example.com", "b@example.com", "c@example.com")
        recording_mail.clear()
        inflight.max = 0
        results = await asyncio.gather(*(set_stock(client, token, vid, 5, 0) for _ in range(10)))
        assert inflight.max >= 2, f"同時性が成立していない（無効試行）: {inflight.max}"
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [409] * 9, (round_no, [(r.status_code, r.text) for r in results])
        winner = next(r for r in results if r.status_code == 200)
        assert winner.json()["changed"] is True and winner.json()["restock_waiting"] == 3
        assert all(r.json()["code"] == "stale_data" for r in results if r.status_code == 409)
        assert len(await audit_rows(engine, "admin.stock.set")) == 1, round_no
        assert len(recording_mail.of_kind("restock_notice")) == 3, round_no
        assert await oh.stock_of(engine, vid) == 5


async def test_it_051c_08_stock_update_vs_order_never_loses_an_update(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """在庫 3 に、注文確定（数量 1）と管理者の更新（`expected_stock: 3`・`stock: 10`）を同時に送る。

    結果は「注文が先: 管理者は 409、在庫 2」か「管理者が先: 在庫 10 から注文で 9」のどちらか。
    注文が成立したのに在庫が 10 のまま（更新の消失）となる回が 0。10 回繰り返す。
    """
    vid = await oh.stocked_variant_id(engine, 2)
    # 管理者側が行ロックを持つ窓を広げる（注文の条件付き UPDATE がそれを待つ）
    track_inflight(monkeypatch, products_repo, "get_variant_for_update", hold=0.03)
    outcomes: set[str] = set()
    for round_no in range(10):
        await oh.set_stock(engine, vid, 3)
        await sql(engine, "DELETE FROM audit_logs")
        cart = await oh.new_token(client)
        await oh.add_item(client, cart, vid, 1)
        prepared = await oh.prepare(client, cart)
        order, admin = await asyncio.gather(
            client.post("/api/v1/orders", json=oh.order_body(prepared), headers=oh.h(cart)),
            set_stock(client, token, vid, 10, 3),
        )
        assert order.status_code == 201, (round_no, order.status_code, order.text)
        stock = await oh.stock_of(engine, vid)
        if admin.status_code == 409:
            assert admin.json()["code"] == "stale_data" and admin.json()["current"] == 2
            assert stock == 2, (round_no, stock)
            outcomes.add("order_first")
        else:
            assert admin.status_code == 200, (round_no, admin.status_code, admin.text)
            assert stock == 9, (round_no, stock)  # 管理者が先: 10 から注文で 9。消失なら 10
            outcomes.add("admin_first")
        await oh.set_stock(engine, vid, 3)
    assert outcomes, "結果が記録されていない"


class _FailsOnFirst(RecordingMailAdapter):
    """最初の宛先で例外を出す記録用アダプタ。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def send_restock_notice(self, to, product_name, color, size, url) -> None:  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("smtp down")
        await super().send_restock_notice(to, product_name, color, size, url)


async def test_it_051c_09_mail_failure_does_not_change_the_response(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str, admin_app: FastAPI
) -> None:
    mail = _FailsOnFirst()
    mail.install(admin_app)
    vid = await stock0_variant(engine)
    await register_rows(engine, vid, "a@example.com", "b@example.com", "c@example.com")
    res = await set_stock(client, token, vid, 5, 0)
    assert res.status_code == 200 and res.json()["changed"] is True
    assert "smtp" not in res.text
    assert len(mail.sent) == 2  # 残りの宛先には送信される
    (failed,) = await audit_rows(engine, "restock.mail_failed")
    assert failed["detail"] == {"count": 1}
    assert "@" not in json.dumps(failed["detail"])
    assert await oh.stock_of(engine, vid) == 5


async def test_it_051c_09b_background_exception_is_swallowed(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    token: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """後処理の例外（`PUBLIC_WEB_BASE_URL` 未設定など）は握る。ログには型名だけを出す。"""

    async def boom(session: Any, variant_id: int, *, mail: Any) -> int:
        raise RuntimeError("secret-detail a@example.com")

    monkeypatch.setattr(products_service, "notify_restock", boom)
    vid = await stock0_variant(engine)
    await register_rows(engine, vid, "a@example.com")
    caplog.set_level("ERROR", logger="app.services.admin_products")
    res = await set_stock(client, token, vid, 5, 0)
    assert res.status_code == 200 and res.json()["restock_waiting"] == 1
    assert await oh.stock_of(engine, vid) == 5
    text_logged = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in text_logged
    assert "secret-detail" not in text_logged and "a@example.com" not in text_logged


async def test_it_051c_10_unknown_and_bad_variant_ids(
    client: httpx.AsyncClient, token: str
) -> None:
    res = await set_stock(client, token, 999999, 5, 0)
    assert res.status_code == 404 and res.json() == {"code": "not_found"}
    for bad in ("0", "-1", "abc", "9223372036854775808"):
        assert (await set_stock(client, token, bad, 5, 0)).status_code == 400, bad
    assert (await set_stock(client, None, 999999, 5, 0)).status_code == 401


async def test_it_051c_11_extra_fields_are_ignored(
    client: httpx.AsyncClient, engine: AsyncEngine, token: str
) -> None:
    vid = await oh.stocked_variant_id(engine, 3)
    before = (await sql(engine, "SELECT sku, product_id FROM variants WHERE id=:v", v=vid))[0]
    current = await oh.stock_of(engine, vid)
    res = await patch(
        client,
        token,
        f"/variants/{vid}/stock",
        {
            "stock": current + 1,
            "expected_stock": current,
            "sku": "HACK",
            "variant_id": 1,
            "product_id": 2,
        },
    )
    assert res.status_code == 200, res.text
    assert (await sql(engine, "SELECT sku, product_id FROM variants WHERE id=:v", v=vid))[
        0
    ] == before
    assert res.json()["variant_id"] == vid and res.json()["sku"] == before[0]


async def test_it_051_auth_member_session_is_forbidden_on_every_route(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """会員のセッションでは入れない（403）。DB は変わらない。"""
    member_token = await ph.make_session(engine, await ph.member_id_of(engine))
    vid = await stock0_variant(engine)
    for method, path, body in (
        ("GET", "/products", None),
        ("GET", "/products/1", None),
        ("PATCH", "/products/1", {"published": False, "expected_published": True}),
        ("PATCH", f"/variants/{vid}/stock", {"stock": 5, "expected_stock": 0}),
    ):
        res = await client.request(
            method, f"{PREFIX}{path}", json=body, headers=ah.admin_headers(member_token)
        )
        assert res.status_code == 403 and res.json() == {"code": "forbidden"}, path
    assert await oh.stock_of(engine, vid) == 0
