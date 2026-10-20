"""UT-FIT-01・02 サイズ感の集計（DS-PRC-003a・DS-DEC-81）。SQLite インメモリ。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, Product, Review, ReviewFit
from app.repositories import reviews as reviews_repo
from app.services.catalog import build_fit_summary


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _product(session: AsyncSession) -> int:
    product = Product(name="テスト商品", price_incl_tax=1000, published=True)
    session.add(product)
    await session.flush()
    return product.id


def _reviews(product_id: int, fit: str | None, n: int, approved: bool = True) -> list[Review]:
    return [
        Review(
            product_id=product_id,
            rating=4,
            body="",
            fit=ReviewFit(fit) if fit else None,
            approved=approved,
        )
        for _ in range(n)
    ]


async def _summary(session: AsyncSession, product_id: int) -> dict:
    return build_fit_summary(await reviews_repo.fit_counts(session, product_id)).model_dump()


async def test_ut_fit_01_counts_by_fit_for_zero_one_and_mixed_reviews(
    session: AsyncSession,
) -> None:
    none, one, mixed = [await _product(session) for _ in range(3)]
    session.add_all(_reviews(one, "just", 1))
    session.add_all(
        _reviews(mixed, "small", 2) + _reviews(mixed, "just", 6) + _reviews(mixed, "large", 2)
    )
    await session.flush()
    assert await _summary(session, none) == {"total": 0, "small": 0, "just": 0, "large": 0}
    assert await _summary(session, one) == {"total": 1, "small": 0, "just": 1, "large": 0}
    assert await _summary(session, mixed) == {"total": 10, "small": 2, "just": 6, "large": 2}


async def test_ut_fit_01_null_fit_unapproved_and_other_products_are_not_counted(
    session: AsyncSession,
) -> None:
    target, other = await _product(session), await _product(session)
    session.add_all(
        _reviews(target, "small", 1)
        + _reviews(target, None, 3)  # fit が NULL
        + _reviews(target, "large", 2, approved=False)  # 未承認
        + _reviews(other, "just", 4)  # 別の商品
    )
    await session.flush()
    summary = await _summary(session, target)
    assert summary == {"total": 1, "small": 1, "just": 0, "large": 0}
    assert summary["total"] == summary["small"] + summary["just"] + summary["large"]


def test_ut_fit_02_zero_reviews_still_have_all_four_keys() -> None:
    summary = build_fit_summary({})
    assert summary.model_dump() == {"total": 0, "small": 0, "just": 0, "large": 0}
    assert set(summary.model_dump_json().replace('"', "").strip("{}").split(",")) == {
        "total:0",
        "small:0",
        "just:0",
        "large:0",
    }
