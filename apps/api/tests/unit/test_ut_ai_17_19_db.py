"""UT-AI-17〜19: トークン・候補プール・往復数の予約と解放。SQLite インメモリ（DB を要する関数）。

MySQL 固有の競合挙動は IT-029-15・19 で担保する（テスト設計書 5.1）。
UT-AI-17 issue_chat_token／hash_token／is_valid_token_format／18 build_candidate_pool／
19 reserve_turn・release_turn
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    Base,
    Category,
    ChatSession,
    Gender,
    Product,
    ProductCategory,
    ProductImage,
    Variant,
)
from app.repositories import chat as chat_repo
from app.services import chat as chat_service
from app.services import chat_prompt


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


# ── UT-AI-17 トークン ──


def test_ut_ai_17_issue_chat_token_is_43_chars_base64url_and_unique() -> None:
    tokens = {chat_service.issue_chat_token() for _ in range(1000)}
    assert len(tokens) == 1000
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", t) for t in tokens)


def test_ut_ai_17_hash_token_is_sha256_hex() -> None:
    h = chat_service.hash_token("a" * 43)
    assert re.fullmatch(r"[0-9a-f]{64}", h)
    assert h == chat_service.hash_token("a" * 43)
    assert h != chat_service.hash_token("b" * 43)
    assert "a" * 43 not in h


@pytest.mark.parametrize(
    ("token", "valid"),
    [
        ("a" * 43, True),
        ("A1_-" * 10 + "abc", True),
        ("a" * 42, False),
        ("a" * 44, False),
        ("a" * 42 + "!", False),
        ("a" * 42 + "=", False),
        ("a" * 42 + "\n", False),
        ("", False),
        (None, False),
    ],
)
def test_ut_ai_17_token_format(token: str | None, valid: bool) -> None:
    assert chat_service.is_valid_token_format(token) is valid


# ── UT-AI-18 build_candidate_pool ──


async def _seed_products(session: AsyncSession) -> dict[str, int]:
    """公開 31 件（うち 1 件は全在庫 0）＋非公開 1 件。id は昇順に振られる。"""
    parent = Category(name="レディース", slug="women", gender=Gender.women, sort_order=0)
    session.add(parent)
    await session.flush()
    child = Category(
        name="トップス", slug="women-tops", gender=Gender.women, parent_id=parent.id, kind="tops"
    )
    session.add(child)
    await session.flush()

    ids: dict[str, int] = {}
    for n in range(1, 34):
        unpublished = n == 32
        all_zero = n == 31
        product = Product(
            name=f"商品{n:02d}",
            price_incl_tax=1000 + n,
            published=not unpublished and n != 33,
            material="綿100%",
        )
        session.add(product)
        await session.flush()
        if n == 33:
            continue  # 33 番目は作らない（欠番にして、id の飛びがあっても昇順で安定することを見る）
        session.add(ProductImage(product_id=product.id, path=f"/p/{n}.png", sort_order=0))
        session.add(ProductCategory(product_id=product.id, category_id=child.id))
        for color, size in (("ホワイト", "S"), ("ホワイト", "M"), ("ブラック", "M")):
            session.add(
                Variant(
                    product_id=product.id,
                    color=color,
                    size=size,
                    sku=f"SKU-{n}-{color}-{size}",
                    stock=0 if all_zero else 5,
                )
            )
        ids[f"p{n}"] = product.id
    await session.flush()
    ids["unpublished"] = ids["p32"]
    ids["all_zero"] = ids["p31"]
    return ids


async def test_ut_ai_18_pool_excludes_unpublished_and_marks_no_stock(
    session: AsyncSession,
) -> None:
    ids = await _seed_products(session)
    pool = await chat_prompt.build_candidate_pool(session)
    pool_ids = [e.id for e in pool.entries]
    assert ids["unpublished"] not in pool_ids
    assert len(pool_ids) == 31  # 公開 31 件（全在庫 0 の 1 件を含む）
    assert pool_ids == sorted(pool_ids)  # id 昇順で安定
    by_id = {e.id: e for e in pool.entries}
    assert by_id[ids["all_zero"]].in_stock is False
    assert by_id[ids["p1"]].in_stock is True
    first = by_id[ids["p1"]]
    assert (first.gender, first.kind) == ("women", "tops")
    assert first.colors == ("ホワイト", "ブラック")
    assert first.sizes == ("S", "M")
    assert first.price_incl_tax == 1001 and first.material == "綿100%"
    assert pool.context is None


@pytest.mark.parametrize("limit", [31, 30, 5])
async def test_ut_ai_18_pool_limit_drops_larger_ids_first(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    ids = await _seed_products(session)
    monkeypatch.setattr(chat_prompt, "CHAT_CATALOG_MAX", limit)
    pool = await chat_prompt.build_candidate_pool(session)
    expected = [ids[f"p{n}"] for n in range(1, 32)][:limit]
    assert [e.id for e in pool.entries] == expected


async def test_ut_ai_18_context_product_is_added_beyond_the_limit(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await _seed_products(session)
    monkeypatch.setattr(chat_prompt, "CHAT_CATALOG_MAX", 5)
    outside = ids["p20"]
    pool = await chat_prompt.build_candidate_pool(session, context_product_id=outside)
    assert [e.id for e in pool.entries][:5] == [ids[f"p{n}"] for n in range(1, 6)]
    assert pool.entries[-1].id == outside  # 上限を超えても加わる
    assert pool.context is not None and pool.context.id == outside
    assert outside in pool.ids

    inside = await chat_prompt.build_candidate_pool(session, context_product_id=ids["p2"])
    assert len(inside.entries) == 5 and inside.context is not None


async def test_ut_ai_18_unknown_or_unpublished_context_is_ignored(session: AsyncSession) -> None:
    ids = await _seed_products(session)
    for bad in (ids["unpublished"], 987654321):  # 非公開・存在しない
        pool = await chat_prompt.build_candidate_pool(session, context_product_id=bad)
        assert pool.context is None
        assert bad not in pool.ids


# ── UT-AI-19 reserve_turn／release_turn ──


async def _chat_session(session: AsyncSession, turns: int) -> int:
    row = ChatSession(token_hash=f"{turns:064d}", turns=turns)
    session.add(row)
    await session.flush()
    return row.id


async def _turns(session: AsyncSession, chat_id: int) -> int:
    return int(
        (
            await session.execute(select(ChatSession.turns).where(ChatSession.id == chat_id))
        ).scalar_one()
    )


@pytest.mark.parametrize(("start", "ok", "end"), [(0, True, 1), (9, True, 10), (10, False, 10)])
async def test_ut_ai_19_reserve_turn(session: AsyncSession, start: int, ok: bool, end: int) -> None:
    chat_id = await _chat_session(session, start)
    assert await chat_repo.reserve_turn(session, chat_id, 10) is ok
    assert await _turns(session, chat_id) == end


async def test_ut_ai_19_release_turn_never_goes_below_zero(session: AsyncSession) -> None:
    chat_id = await _chat_session(session, 1)
    assert await chat_repo.release_turn(session, chat_id) is True
    assert await _turns(session, chat_id) == 0
    assert await chat_repo.release_turn(session, chat_id) is False  # turns > 0 のときだけ減る
    assert await _turns(session, chat_id) == 0


async def test_ut_ai_19_reserve_unknown_session_fails(session: AsyncSession) -> None:
    assert await chat_repo.reserve_turn(session, 123456, 10) is False
