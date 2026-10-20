"""IT-007（再入荷通知の申込 DS-API-007）・IT-007a（通知の送信 DS-PRC-007a）。MySQL・seed 必須。

V-STOCK0 は商品 29 の色ブラック・サイズ M（SKU `GU-029-BK-M`、在庫 0）。メールはダミー
（`example.com`）。送信は記録用アダプタ（`tests/recording_mail.py`）で読む。
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import seed_data
from app.services.restock import notify_restock
from tests.integration import concurrency_helpers as ch
from tests.integration import order_helpers as oh
from tests.integration import p2b_helpers as ph
from tests.recording_mail import RecordingMailAdapter

WEB_BASE = "http://localhost:3000"
URL = "/api/v1/restock-notifications"


@pytest.fixture
def restock_app(make_app: Callable[..., FastAPI], test_database_url: str, migrated_schema: str):
    return make_app(APP_ENV="test", DATABASE_URL=test_database_url, PUBLIC_WEB_BASE_URL=WEB_BASE)


@pytest.fixture
async def client(restock_app: FastAPI, seed_db: AsyncEngine, client_factory, recording_mail):
    recording_mail.install(restock_app)
    return client_factory(restock_app)


async def _stock0(engine: AsyncEngine) -> int:
    return await oh.variant_id(engine, seed_data.TEST_SKU_STOCK0)


async def _post(client: httpx.AsyncClient, variant_id, email, token: str | None = None, **h):
    headers = {**ph.sess(token), **h}
    return await client.post(URL, json={"variant_id": variant_id, "email": email}, headers=headers)


async def _rows(engine: AsyncEngine, where: str = "1=1", **params) -> list[dict]:
    async with engine.connect() as conn:
        res = await conn.execute(
            text(
                "SELECT variant_id, email, member_id, notified_at FROM restock_notifications"
                f" WHERE {where} ORDER BY id"
            ),
            params,
        )
        return [dict(r._mapping) for r in res]


async def _register_rows(engine: AsyncEngine, vid: int, *emails: str) -> None:
    """申込行を直接入れる（件数を作るための近道）。"""
    async with engine.begin() as conn:
        for email in emails:
            await conn.execute(
                text("INSERT INTO restock_notifications (variant_id, email) VALUES (:v, :e)"),
                {"v": vid, "e": email},
            )


def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


# ── IT-007-01〜08 申込 ───────────────────────────────────────────────────────


async def test_it_007_01_registers_with_normalized_email(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    vid = await _stock0(seed_db)
    res = await _post(client, vid, " Dummy.User@Example.COM ")
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "registered"}
    rows = await _rows(seed_db)
    assert len(rows) == 1
    assert rows[0]["variant_id"] == vid and rows[0]["email"] == "dummy.user@example.com"
    assert rows[0]["notified_at"] is None and rows[0]["member_id"] is None


async def test_it_007_02_in_stock_variant_is_409(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    vid = await oh.stocked_variant_id(seed_db, 5)
    res = await _post(client, vid, "a@example.com")
    assert res.status_code == 409 and res.json() == {"code": "in_stock"}
    assert await _rows(seed_db) == []


async def test_it_007_03_unpublished_or_missing_variant_is_404(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    unpub = await oh.scalar(
        seed_db,
        "SELECT v.id FROM variants v JOIN products p ON p.id = v.product_id"
        " WHERE p.published = 0 LIMIT 1",
    )
    assert unpub is not None
    for variant_id in (int(unpub), 999999):
        res = await _post(client, variant_id, "a@example.com")
        assert res.status_code == 404 and res.json() == {"code": "not_found"}, variant_id
    assert await _rows(seed_db) == []


async def test_it_007_04_resubmission_is_one_row_and_reactivates_a_notified_one(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    vid = await _stock0(seed_db)
    for _ in range(2):
        assert (await _post(client, vid, "a@example.com")).status_code == 200
    assert len(await _rows(seed_db)) == 1
    async with seed_db.begin() as conn:
        await conn.execute(text("UPDATE restock_notifications SET notified_at = NOW()"))
    assert (await _rows(seed_db))[0]["notified_at"] is not None
    assert (await _post(client, vid, "a@example.com")).status_code == 200
    rows = await _rows(seed_db)
    assert len(rows) == 1 and rows[0]["notified_at"] is None


@pytest.mark.parametrize(
    ("variant_id", "email"),
    [
        (0, "a@example.com"),
        (-1, "a@example.com"),
        (9223372036854775808, "a@example.com"),
        ("abc", "a@example.com"),
        (1, "not-an-email"),
        (1, "a@b"),
        (1, "a" * 243 + "@example.com"),  # 255 文字
        (1, ""),
        (1, "a​@example.com"),  # ゼロ幅スペース
    ],
)
async def test_it_007_05_invalid_input_is_400(
    client: httpx.AsyncClient, seed_db: AsyncEngine, variant_id, email
) -> None:
    res = await _post(client, variant_id, email)
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "validation_error"
    assert await _rows(seed_db) == []


async def test_it_007_06_rate_limit_is_20_per_hour_per_ip(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    vid = await _stock0(seed_db)
    for i in range(20):
        res = await _post(client, vid, f"u{i}@example.com", **{"X-Forwarded-For": "7.7.7.7"})
        assert res.status_code == 200, (i, res.text)
    res = await _post(client, vid, "u20@example.com", **{"X-Forwarded-For": "7.7.7.7"})
    assert res.status_code == 429 and res.json() == {"code": "rate_limited"}
    assert int(res.headers["Retry-After"]) >= 1
    res = await _post(client, vid, "u21@example.com", **{"X-Forwarded-For": "8.8.8.8"})
    assert res.status_code == 200, "別の IP は数えない"


async def test_it_007_07_pending_limit_is_10_per_email(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    email = "many@example.com"
    stock0 = await _stock0(seed_db)
    other_ids = [
        int(r)
        for r in (
            await oh.scalar(  # 他の variant を 9 件（在庫は関係なく、未通知の申込行だけを作る）
                seed_db,
                "SELECT GROUP_CONCAT(id) FROM (SELECT id FROM variants WHERE id <> :v"
                " ORDER BY id LIMIT 9) t",
                v=stock0,
            )
        ).split(",")
    ]
    for vid in other_ids:
        await _register_rows(seed_db, vid, email)

    # 9 件の状態から: 10 件目は可
    assert (await _post(client, stock0, email)).status_code == 200
    # 10 件の状態から: 新しい variant は 422。在庫 0 にした別の variant を使う
    extra = await oh.stocked_variant_id(seed_db, 5)
    await oh.set_stock(seed_db, extra, 0)
    res = await _post(client, extra, email)
    assert res.status_code == 422, res.text
    assert res.json() == {"code": "limit_exceeded", "field": "email", "limit": 10}
    # 既に申し込んだ variant への再申込は件数に数えず 200
    assert (await _post(client, stock0, email)).status_code == 200
    # 別のメールは数えない
    assert (await _post(client, extra, "someone-else@example.com")).status_code == 200
    # 通知済みの行は未通知に数えない
    async with seed_db.begin() as conn:
        await conn.execute(
            text("UPDATE restock_notifications SET notified_at = NOW() WHERE variant_id = :v"),
            {"v": other_ids[0]},
        )
    assert (await _post(client, extra, email)).status_code == 200


async def test_it_007_08_member_id_is_recorded_only_for_a_valid_session(
    client: httpx.AsyncClient, seed_db: AsyncEngine
) -> None:
    vid = await _stock0(seed_db)
    member_id = await ph.member_id_of(seed_db)
    tok = await ph.make_session(seed_db, member_id)
    assert (await _post(client, vid, "m@example.com", tok)).status_code == 200
    assert (await _post(client, vid, "g@example.com", "A" * 43)).status_code == 200
    assert (await _post(client, vid, "e@example.com", "short")).status_code == 200
    rows = {r["email"]: r["member_id"] for r in await _rows(seed_db)}
    assert rows == {"m@example.com": member_id, "g@example.com": None, "e@example.com": None}
    # セッション無しの再申込は、記録済みの member_id を消さない
    assert (await _post(client, vid, "m@example.com")).status_code == 200
    assert {r["email"]: r["member_id"] for r in await _rows(seed_db)}["m@example.com"] == member_id


async def test_it_007_demo_email_domains_restricts_the_domain(
    make_app: Callable[..., FastAPI],
    test_database_url: str,
    migrated_schema: str,
    seed_db: AsyncEngine,
    client_factory,
) -> None:
    """DEMO_EMAIL_DOMAINS 設定時は許可ドメインの完全一致だけ（外れたら 422 unsupported_value）。"""
    app = make_app(
        APP_ENV="test",
        DATABASE_URL=test_database_url,
        DEMO_EMAIL_DOMAINS="example.com, example.net",
    )
    client = client_factory(app)
    vid = await _stock0(seed_db)
    for email in ("a@example.com", "a@EXAMPLE.net"):
        assert (await _post(client, vid, email)).status_code == 200, email
    for email in ("a@example.org", "a@sub.example.com"):
        res = await _post(client, vid, email)
        assert res.status_code == 422, email
        assert res.json() == {"code": "unsupported_value", "field": "email"}
    assert len(await _rows(seed_db)) == 2


# ── IT-007-09 同時申込 ───────────────────────────────────────────────────────


def _max_overlap(intervals: list[tuple[float, float]]) -> int:
    events = sorted([(s, 1) for s, _ in intervals] + [(e, -1) for _, e in intervals])
    cur = best = 0
    for _, d in events:
        cur += d
        best = max(best, cur)
    return best


async def test_it_007_09_ten_parallel_registrations_make_one_row(
    live_server, seed_db: AsyncEngine
) -> None:
    """同じ（variant, email）を 10 並列で申し込む（10 反復）。全応答 200・1 行・500 なし。

    1.4 #2 の同時性の証明は、`/_test/metrics` のカウンタが注文確定専用のため使えない。代わりに
    クライアント側で各リクエストの (送信, 受信) 時刻を測り、重なりの最大数が 2 以上であることを
    確かめる（満たさない試行は無効試行として数え、やり直す）。
    """
    vid = await _stock0(seed_db)
    n_parallel = 10

    async def attempt(iteration: int, n: int) -> tuple[list[httpx.Response], dict[str, int]]:
        async with seed_db.begin() as conn:
            await conn.execute(text("DELETE FROM restock_notifications"))
        async with httpx.AsyncClient(base_url=live_server.base_url, timeout=30.0) as client:
            barrier = asyncio.Barrier(n_parallel)
            spans: list[tuple[float, float]] = []

            async def one(k: int) -> httpx.Response:
                req = client.build_request(
                    "POST",
                    URL,
                    json={"variant_id": vid, "email": "same@example.com"},
                    headers={**oh.h(), "X-Forwarded-For": f"10.{iteration}.{n}.{k}"},
                )
                await barrier.wait()
                start = time.perf_counter()
                res = await client.send(req)
                spans.append((start, time.perf_counter()))
                return res

            responses = list(await asyncio.gather(*(one(k) for k in range(n_parallel))))
        return responses, {"inflight_max": _max_overlap(spans)}

    for i in range(10):
        counter = itertools.count(1)
        responses, m = await ch.run_until_concurrent(
            f"IT-007-09#{i}",
            lambda i=i, counter=counter: attempt(i, next(counter)),
            lambda r: r[1],
        )
        assert [r.status_code for r in responses] == [200] * n_parallel, [
            (r.status_code, r.text) for r in responses
        ]
        assert m["inflight_max"] >= 2
        assert len(await _rows(seed_db)) == 1, i


# ── IT-007a 通知の送信 ───────────────────────────────────────────────────────


async def test_it_007a_01_notifies_each_applicant_once_with_product_link(
    seed_db: AsyncEngine, restock_app: FastAPI, recording_mail: RecordingMailAdapter
) -> None:
    vid = await _stock0(seed_db)
    emails = ["a@example.com", "b@example.com", "c@example.com"]
    await _register_rows(seed_db, vid, *emails)
    await oh.set_stock(seed_db, vid, 5)
    async with _session(seed_db) as session:
        sent = await notify_restock(session, vid, mail=recording_mail)
    assert sent == 3
    mails = recording_mail.of_kind("restock_notice")
    assert sorted(m.to for m in mails) == emails
    product_id = await oh.scalar(seed_db, "SELECT product_id FROM variants WHERE id = :v", v=vid)
    first = mails[0].args
    assert first["url"] == f"{WEB_BASE}/products/{product_id}"
    assert first["product_name"] == seed_data.PRODUCTS[28].name
    async with seed_db.connect() as conn:
        color, size = (
            await conn.execute(text("SELECT color, size FROM variants WHERE id = :v"), {"v": vid})
        ).one()
    assert (first["color"], first["size"]) == (color, size) and size == "M"
    assert all(r["notified_at"] is not None for r in await _rows(seed_db))
    detail = await oh.scalar(
        seed_db, "SELECT detail FROM audit_logs WHERE action = 'restock.notified'"
    )
    assert (json.loads(detail) if isinstance(detail, str) else detail) == {"count": 3}


async def test_it_007a_02_two_concurrent_notifications_send_each_mail_once(
    seed_db: AsyncEngine, restock_app: FastAPI, recording_mail: RecordingMailAdapter
) -> None:
    vid = await _stock0(seed_db)
    await oh.set_stock(seed_db, vid, 5)
    for _ in range(10):
        recording_mail.clear()
        async with seed_db.begin() as conn:
            await conn.execute(text("DELETE FROM restock_notifications"))
        await _register_rows(seed_db, vid, "a@example.com", "b@example.com", "c@example.com")
        barrier = asyncio.Barrier(2)

        async def call(barrier: asyncio.Barrier = barrier) -> int:
            async with _session(seed_db) as session:
                await barrier.wait()
                return await notify_restock(session, vid, mail=recording_mail)

        results = await asyncio.gather(call(), call())
        assert sum(results) == 3, results
        assert len(recording_mail.of_kind("restock_notice")) == 3
        assert all(r["notified_at"] is not None for r in await _rows(seed_db))


async def test_it_007a_03_no_stock_or_no_applicants_sends_nothing(
    seed_db: AsyncEngine, restock_app: FastAPI, recording_mail: RecordingMailAdapter
) -> None:
    vid = await _stock0(seed_db)
    await _register_rows(seed_db, vid, "a@example.com")
    async with _session(seed_db) as session:
        assert await notify_restock(session, vid, mail=recording_mail) == 0  # 在庫 0
    assert recording_mail.sent == []
    assert (await _rows(seed_db))[0]["notified_at"] is None
    other = await oh.stocked_variant_id(seed_db, 5)  # 在庫あり・申込 0 件
    async with _session(seed_db) as session:
        assert await notify_restock(session, other, mail=recording_mail) == 0
        assert await notify_restock(session, 999999, mail=recording_mail) == 0  # 存在しない
    assert recording_mail.sent == []


class _FailsOnce(RecordingMailAdapter):
    """最初の宛先で例外を出す記録用アダプタ。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def send_restock_notice(self, to, product_name, color, size, url) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("smtp down")
        await super().send_restock_notice(to, product_name, color, size, url)


async def test_it_007a_04_one_failure_does_not_stop_the_others(
    seed_db: AsyncEngine, restock_app: FastAPI
) -> None:
    mail = _FailsOnce()
    vid = await _stock0(seed_db)
    await _register_rows(seed_db, vid, "a@example.com", "b@example.com", "c@example.com")
    await oh.set_stock(seed_db, vid, 5)
    async with _session(seed_db) as session:
        sent = await notify_restock(session, vid, mail=mail)  # 例外は伝わらない
    assert sent == 2 and len(mail.sent) == 2
    failed = await oh.scalar(
        seed_db, "SELECT detail FROM audit_logs WHERE action = 'restock.mail_failed'"
    )
    failed = json.loads(failed) if isinstance(failed, str) else failed
    assert failed == {"count": 1}
    async with seed_db.connect() as conn:
        dumped = json.dumps(
            [r[0] for r in (await conn.execute(text("SELECT detail FROM audit_logs"))).all()]
        )
    assert "@" not in dumped, "宛先を audit_logs に残さない"


async def test_it_007a_05_reapplication_after_notification_is_notified_again(
    client: httpx.AsyncClient,
    seed_db: AsyncEngine,
    recording_mail: RecordingMailAdapter,
) -> None:
    vid = await _stock0(seed_db)
    assert (await _post(client, vid, "a@example.com")).status_code == 200
    await oh.set_stock(seed_db, vid, 5)
    async with _session(seed_db) as session:
        assert await notify_restock(session, vid, mail=recording_mail) == 1
        assert await notify_restock(session, vid, mail=recording_mail) == 0, "通知済みは対象外"
    assert len(recording_mail.of_kind("restock_notice")) == 1

    await oh.set_stock(seed_db, vid, 0)  # 在庫を一度 0 に戻す
    assert (await _post(client, vid, "a@example.com")).status_code == 200  # 再申込
    await oh.set_stock(seed_db, vid, 3)
    async with _session(seed_db) as session:
        assert await notify_restock(session, vid, mail=recording_mail) == 1
    assert len(recording_mail.of_kind("restock_notice")) == 2
