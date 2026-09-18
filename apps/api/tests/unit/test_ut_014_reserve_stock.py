"""UT-014-03／04 在庫引当（条件付き UPDATE）の影響行数。SQLite インメモリで関数だけを検証する。

MySQL 固有の競合挙動は IT-014-04 で担保する（テスト設計書 5.1）。
注文番号の UNIQUE 衝突時の 1 回再生成（UT-014-01 後段）もここで SQLite を使って確認する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.models import Base, Cart, CartStatus, Order, OrderStatus, Product, Variant
from app.repositories import orders as orders_repo
from app.repositories.orders import PendingOrderInput


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _variant(session: AsyncSession, stock: int) -> int:
    product = Product(name="テスト商品", price_incl_tax=1000, published=True)
    session.add(product)
    await session.flush()
    v = Variant(product_id=product.id, color="黒", size="M", sku=f"T-{stock}", stock=stock)
    session.add(v)
    await session.flush()
    return v.id


async def _stock(session: AsyncSession, variant_id: int) -> int:
    stmt = select(Variant.stock).where(Variant.id == variant_id)
    return int((await session.execute(stmt)).scalar_one())


async def test_ut_014_03_quantity_2_stock_5_affects_1_row(session: AsyncSession) -> None:
    vid = await _variant(session, stock=5)
    assert await orders_repo.reserve_stock(session, variant_id=vid, quantity=2) == 1
    assert await _stock(session, vid) == 3


async def test_ut_014_04_quantity_equals_stock_affects_1_row(session: AsyncSession) -> None:
    vid = await _variant(session, stock=5)
    assert await orders_repo.reserve_stock(session, variant_id=vid, quantity=5) == 1
    assert await _stock(session, vid) == 0


async def test_ut_014_04_quantity_over_stock_affects_0_rows_and_keeps_stock(
    session: AsyncSession,
) -> None:
    vid = await _variant(session, stock=5)
    assert await orders_repo.reserve_stock(session, variant_id=vid, quantity=6) == 0
    assert await _stock(session, vid) == 5


async def test_ut_014_04_restore_stock_adds_back(session: AsyncSession) -> None:
    vid = await _variant(session, stock=5)
    await orders_repo.reserve_stock(session, variant_id=vid, quantity=5)
    await orders_repo.restore_stock(session, variant_id=vid, quantity=5)
    assert await _stock(session, vid) == 5


# ── UT-014-01 後段: 注文番号の UNIQUE 衝突は 1 回だけ再生成 ─────────────────────


def _pending(cart_id: int, key: str) -> PendingOrderInput:
    return PendingOrderInput(
        idempotency_key=key,
        cart_id=cart_id,
        guest_email="test@example.com",
        subtotal=1000,
        shipping_fee=550,
        total=1550,
        tax_rate_at_order="0.10",
        ship_name="テスト 太郎",
        ship_postal_code="1000001",
        ship_address="東京都千代田区千代田1-1",
        ship_phone="09012345678",
    )


async def _cart(session: AsyncSession) -> int:
    cart = Cart(anonymous_token="tok", status=CartStatus.active)
    session.add(cart)
    await session.flush()
    return cart.id


async def test_ut_014_01_order_number_collision_regenerates_once(session: AsyncSession) -> None:
    cart_id = await _cart(session)
    first = await orders_repo.insert_pending_order(
        session, _pending(cart_id, "K" * 43), generate=lambda: "GU-260918-AAAAAAAA"
    )
    await session.commit()
    assert first.order_number == "GU-260918-AAAAAAAA"

    numbers = iter(["GU-260918-AAAAAAAA", "GU-260918-BBBBBBBB"])
    second = await orders_repo.insert_pending_order(
        session, _pending(cart_id, "L" * 43), generate=lambda: next(numbers)
    )
    await session.commit()
    assert second.order_number == "GU-260918-BBBBBBBB"
    assert second.status == OrderStatus.pending_payment


async def test_ut_014_01_order_number_second_collision_is_internal_error(
    session: AsyncSession,
) -> None:
    cart_id = await _cart(session)
    await orders_repo.insert_pending_order(
        session, _pending(cart_id, "K" * 43), generate=lambda: "GU-260918-AAAAAAAA"
    )
    await session.commit()
    with pytest.raises(AppError) as ei:
        await orders_repo.insert_pending_order(
            session, _pending(cart_id, "L" * 43), generate=lambda: "GU-260918-AAAAAAAA"
        )
    assert ei.value.status == 500


async def test_ut_014_01_idempotency_key_collision_raises_duplicate_key(
    session: AsyncSession,
) -> None:
    cart_id = await _cart(session)
    await orders_repo.insert_pending_order(
        session, _pending(cart_id, "K" * 43), generate=lambda: "GU-260918-AAAAAAAA"
    )
    await session.commit()
    with pytest.raises(orders_repo.DuplicateIdempotencyKey):
        await orders_repo.insert_pending_order(
            session, _pending(cart_id, "K" * 43), generate=lambda: "GU-260918-CCCCCCCC"
        )
    await session.rollback()
    n = len((await session.execute(select(Order))).scalars().all())
    assert n == 1
