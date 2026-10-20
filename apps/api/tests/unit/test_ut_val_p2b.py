"""UT-VAL-03／04: 注文入力の P2-b 差分（受け取り方法の条件・店舗受け取りの連絡先）。

設計仕様書 P2 追補b 4.4・4.8 DS-PRC-014-3 手順 0。DB を見ない検証なので、ルーター経由
（SQLite の空 app）で 400 `validation_error` と fields の name/reason まで確認する。
未知の `receive_method`（422）と `delivery` での `store_code`（422）はサービス層（レーン C）の仕事。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.core.errors import map_reason
from app.schemas.order import OrderCreateIn
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN, "X-Cart-Token": "A" * 43}


_DROP = object()  # 本文からそのキーを取り除く印


def body(**over: Any) -> dict[str, Any]:
    """配送の正常な本文。`over` の値が `_DROP` なら、そのキーを取り除く。"""
    base: dict[str, Any] = {
        "idempotency_key": "k" * 43,
        "ship_name": "テスト 太郎",
        "ship_postal_code": "1000001",
        "ship_address": "東京都千代田区千代田1-1",
        "ship_phone": "09012345678",
        "guest_email": "test@example.com",
        "receive_method": "delivery",
        "payment_method": "card",
        "display": {"subtotal": 1000, "shipping_fee": 550, "total": 1550},
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not _DROP}


def store_body(**over: Any) -> dict[str, Any]:
    """店舗受け取りの正常な本文（郵便番号・住所なし、store_code あり）。"""
    return body(
        **{
            "receive_method": "store",
            "store_code": "demo-tokyo",
            "ship_postal_code": _DROP,
            "ship_address": _DROP,
            "display": {"subtotal": 1000, "shipping_fee": 0, "total": 1000},
            **over,
        }
    )


def errors_of(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """検証エラーを (項目名, reason) にする（API の fields と同じ変換）。"""
    with pytest.raises(ValidationError) as ei:
        OrderCreateIn(**payload)
    return sorted(
        (str(e["loc"][0]), map_reason(str(e["type"]), e.get("input"))) for e in ei.value.errors()
    )


# ── UT-VAL-03 受け取り方法の条件 ────────────────────────────────────────────────


def test_ut_val_03_store_without_store_code_is_required() -> None:
    assert errors_of(store_body(store_code=_DROP)) == [("store_code", "required")]


def test_ut_val_03_delivery_without_postal_code_or_address_is_required() -> None:
    assert errors_of(body(ship_postal_code=_DROP)) == [("ship_postal_code", "required")]
    assert errors_of(body(ship_address=_DROP)) == [("ship_address", "required")]
    assert errors_of(body(ship_postal_code=_DROP, ship_address=_DROP)) == [
        ("ship_address", "required"),
        ("ship_postal_code", "required"),
    ]


def test_ut_val_03_store_without_postal_code_and_address_is_ok_and_ignored() -> None:
    parsed = OrderCreateIn(**store_body())
    assert parsed.receive_method == "store" and parsed.store_code == "demo-tokyo"
    assert parsed.ship_postal_code is None and parsed.ship_address is None


def test_ut_val_03_store_ignores_ship_fields_even_if_given_or_garbage() -> None:
    """mass assignment を許さない: 渡されても捨てる。形が不正でも 400 にしない。"""
    given = OrderCreateIn(**store_body(ship_postal_code="9999999", ship_address="別の住所"))
    assert given.ship_postal_code is None and given.ship_address is None
    garbage = OrderCreateIn(**store_body(ship_postal_code="あいう", ship_address="x" * 500))
    assert garbage.ship_postal_code is None and garbage.ship_address is None


@pytest.mark.parametrize("code", ["demo-tokyo", "demo-osaka", "a", "0", "a-b-9", "a" * 32])
def test_ut_val_03_store_code_valid(code: str) -> None:
    assert OrderCreateIn(**store_body(store_code=code)).store_code == code


@pytest.mark.parametrize(
    "code",
    [
        "DEMO",  # 大文字
        "demo_tokyo",  # アンダースコア
        "ｄｅｍｏ",  # 全角
        "デモ",
        "a" * 33,  # 33 文字
        "",  # 空文字
        "demo tokyo",
        "demo-tokyo\n",  # 末尾の改行
        "demo​",  # ゼロ幅スペース
    ],
)
def test_ut_val_03_store_code_invalid(code: str) -> None:
    assert errors_of(store_body(store_code=code)) == [("store_code", "format")]


def test_ut_val_03_delivery_may_carry_store_code_for_the_service_to_reject() -> None:
    """`delivery` + `store_code` は形としては正しい。422 にするのはサービス層（C）。"""
    parsed = OrderCreateIn(**body(store_code="demo-tokyo"))
    assert parsed.receive_method == "delivery" and parsed.store_code == "demo-tokyo"


def test_ut_val_03_unknown_receive_method_passes_shape_check_for_422_in_service() -> None:
    parsed = OrderCreateIn(**body(receive_method="pickup", ship_postal_code=_DROP))
    assert parsed.receive_method == "pickup"


def test_ut_val_03_delivery_postal_code_hyphen_still_normalized() -> None:
    assert OrderCreateIn(**body(ship_postal_code="100-0001")).ship_postal_code == "1000001"


# ── UT-VAL-04 店舗受け取りの連絡先 ──────────────────────────────────────────────


@pytest.mark.parametrize("phone", ["０９０１２３４５６７８", "0901234567a", "090-1234-567a"])
def test_ut_val_04_store_phone_must_be_ascii_digits(phone: str) -> None:
    assert errors_of(store_body(ship_phone=phone)) == [("ship_phone", "format")]


def test_ut_val_04_store_blank_name_is_required() -> None:
    assert errors_of(store_body(ship_name="　　")) == [("ship_name", "required")]
    assert errors_of(store_body(ship_name="")) == [("ship_name", "required")]


def test_ut_val_04_store_email_without_at_is_format() -> None:
    assert errors_of(store_body(guest_email="test.example.com")) == [("guest_email", "format")]


def test_ut_val_04_store_hyphenated_phone_normalized() -> None:
    assert OrderCreateIn(**store_body(ship_phone="090-1234-5678")).ship_phone == "09012345678"


# ── HTTP 経由（400 の本文の形）────────────────────────────────────────────────


async def test_ut_val_03_http_400_body_for_missing_store_code(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], httpx.AsyncClient]
) -> None:
    client = client_factory(make_app())
    res = await client.post("/api/v1/orders", json=store_body(store_code=_DROP), headers=HEADERS)
    assert res.status_code == 400
    assert res.json() == {
        "code": "validation_error",
        "fields": [{"name": "store_code", "reason": "required"}],
    }


async def test_ut_val_03_http_400_body_for_delivery_without_postal_code(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], httpx.AsyncClient]
) -> None:
    client = client_factory(make_app())
    res = await client.post("/api/v1/orders", json=body(ship_postal_code=_DROP), headers=HEADERS)
    assert res.status_code == 400
    assert res.json() == {
        "code": "validation_error",
        "fields": [{"name": "ship_postal_code", "reason": "required"}],
    }


async def test_ut_val_04_http_400_for_fullwidth_phone_in_store_order(
    make_app: Callable[..., FastAPI], client_factory: Callable[[FastAPI], httpx.AsyncClient]
) -> None:
    client = client_factory(make_app())
    res = await client.post(
        "/api/v1/orders", json=store_body(ship_phone="０９０１２３４５６７８"), headers=HEADERS
    )
    assert res.status_code == 400
    assert res.json()["fields"] == [{"name": "ship_phone", "reason": "format"}]
