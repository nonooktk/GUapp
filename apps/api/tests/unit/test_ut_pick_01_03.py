"""UT-PICK-01〜03 受け取りコード（DS-DEC-79・DS-PRC-014-3・DS-PRC-024a）。

衝突時の再生成（UT-PICK-02）は SQLite インメモリで UNIQUE 違反を起こして確かめる
（MySQL 固有の挙動は IT-014-16）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.models import Base, Cart, CartStatus, OrderStatus, ReceiveMethod
from app.repositories import orders as orders_repo
from app.repositories.orders import PendingOrderInput
from app.services import order_status
from app.services.pickup_code import PICKUP_CODE_RE, generate_pickup_code


def test_ut_pick_01_generated_codes_have_the_right_alphabet_and_do_not_collide() -> None:
    codes = [generate_pickup_code() for _ in range(10_000)]
    assert all(len(c) == 8 and PICKUP_CODE_RE.fullmatch(c) for c in codes)
    used = set("".join(codes))
    assert used.isdisjoint("IO01"), "I・O・0・1 は一度も出ない"
    assert used <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    assert len(set(codes)) == len(codes), "10,000 回で重複 0"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _cart(session: AsyncSession) -> int:
    cart = Cart(status=CartStatus.active, anonymous_token="t" * 43)
    session.add(cart)
    await session.flush()
    return cart.id


def _pending(cart_id: int, key: str) -> PendingOrderInput:
    return PendingOrderInput(
        idempotency_key=key,
        cart_id=cart_id,
        guest_email="a@example.com",
        subtotal=1990,
        shipping_fee=0,
        total=1990,
        tax_rate_at_order="0.10",
        ship_name="テスト 太郎",
        ship_postal_code="0000001",
        ship_address="東京都千代田区デモ町1-2-3",
        ship_phone="09012345678",
        receive_method="store",
        store_id=1,
    )


def _numbers() -> Iterator[str]:
    n = 0
    while True:
        n += 1
        yield f"GU-261020-{n:08d}"  # UNIQUE を満たす連番（形式の検査はここではしない）


async def test_ut_pick_02_first_collision_regenerates_once(session: AsyncSession) -> None:
    cart_id, numbers = await _cart(session), _numbers()
    first = await orders_repo.insert_pending_order(
        session,
        _pending(cart_id, "K" * 43),
        generate=lambda: next(numbers),
        generate_pickup=lambda: "AAAAAAAA",
    )
    await session.commit()
    assert first.pickup_code == "AAAAAAAA"

    codes = iter(["AAAAAAAA", "BBBBBBBB"])
    second = await orders_repo.insert_pending_order(
        session,
        _pending(cart_id, "L" * 43),
        generate=lambda: next(numbers),
        generate_pickup=lambda: next(codes),
    )
    await session.commit()
    assert second.pickup_code == "BBBBBBBB"


async def test_ut_pick_02_two_consecutive_collisions_are_internal_error(
    session: AsyncSession,
) -> None:
    cart_id, numbers = await _cart(session), _numbers()
    await orders_repo.insert_pending_order(
        session,
        _pending(cart_id, "K" * 43),
        generate=lambda: next(numbers),
        generate_pickup=lambda: "AAAAAAAA",
    )
    await session.commit()
    with pytest.raises(AppError) as excinfo:
        await orders_repo.insert_pending_order(
            session,
            _pending(cart_id, "L" * 43),
            generate=lambda: next(numbers),
            generate_pickup=lambda: "AAAAAAAA",
        )
    assert excinfo.value.status == 500 and excinfo.value.code == "internal_error"


async def test_ut_pick_02_delivery_order_has_no_pickup_code(session: AsyncSession) -> None:
    cart_id, numbers = await _cart(session), _numbers()
    data = _pending(cart_id, "K" * 43)
    delivery = PendingOrderInput(
        **{**data.__dict__, "receive_method": "delivery", "store_id": None}
    )
    order = await orders_repo.insert_pending_order(
        session, delivery, generate=lambda: next(numbers), generate_pickup=lambda: "AAAAAAAA"
    )
    assert order.pickup_code is None and order.store_id is None


def test_ut_pick_03_pickup_code_is_visible_for_exactly_three_of_sixteen_combinations() -> None:
    visible = {
        (status, method)
        for status in OrderStatus
        for method in ReceiveMethod
        if order_status.pickup_code_visible(status, method)
    }
    assert visible == {
        (OrderStatus.accepted, ReceiveMethod.store),
        (OrderStatus.preparing, ReceiveMethod.store),
        (OrderStatus.shipped, ReceiveMethod.store),
    }
    assert len(list(OrderStatus)) * len(list(ReceiveMethod)) == 16
    # 値を返す関数も同じ判定（条件を満たさなければ None）
    for status in OrderStatus:
        for method in ReceiveMethod:
            expected = "ABCDEFGH" if (status, method) in visible else None
            assert order_status.visible_pickup_code(status, method, "ABCDEFGH") == expected
    assert order_status.visible_pickup_code(OrderStatus.accepted, ReceiveMethod.store, None) is None
