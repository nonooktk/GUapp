"""UT-VAL-01／02 注文入力の Pydantic 検証（設計仕様書 4.4 の入力形式）。

ルーター経由（SQLite の空 app）で 400 `validation_error` と fields の name/reason まで確認する。
DB を見ない検証なので、カートの有無に関係なく 400 が先に返る（4.5 の順序 2）。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.order import OrderCreateIn
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN, "X-Cart-Token": "A" * 43}


def valid_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
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
    body.update(over)
    return body


def _fields(errors: list[dict[str, Any]]) -> set[str]:
    return {str(e["loc"][0]) for e in errors}


# ── UT-VAL-01 形式 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("postal", ["100000", "10000012", "100-000", "abcdefg"])
def test_ut_val_01_postal_code_6_or_8_digits_rejected(postal: str) -> None:
    with pytest.raises(ValidationError) as ei:
        OrderCreateIn(**valid_body(ship_postal_code=postal))
    assert _fields(ei.value.errors()) == {"ship_postal_code"}


@pytest.mark.parametrize("postal", ["1000001", "100-0001", "100 0001", "１００-０００１"])
def test_ut_val_01_postal_code_hyphen_and_spaces_normalized(postal: str) -> None:
    if not postal.isascii():
        # 全角数字は仕様外（除去するのはハイフン・空白のみ）→ 不可
        with pytest.raises(ValidationError):
            OrderCreateIn(**valid_body(ship_postal_code=postal))
        return
    assert OrderCreateIn(**valid_body(ship_postal_code=postal)).ship_postal_code == "1000001"


def test_ut_val_01_phone_with_letters_rejected() -> None:
    with pytest.raises(ValidationError) as ei:
        OrderCreateIn(**valid_body(ship_phone="0901234567a"))  # pragma: allowlist secret
    assert _fields(ei.value.errors()) == {"ship_phone"}


def test_ut_val_01_phone_hyphens_normalized() -> None:
    assert OrderCreateIn(**valid_body(ship_phone="090-1234-5678")).ship_phone == "09012345678"
    assert OrderCreateIn(**valid_body(ship_phone="03-1234-5678")).ship_phone == "0312345678"


def test_ut_val_01_email_without_at_rejected() -> None:
    with pytest.raises(ValidationError) as ei:
        OrderCreateIn(**valid_body(guest_email="test.example.com"))
    assert _fields(ei.value.errors()) == {"guest_email"}


def test_ut_val_01_idempotency_key_shape() -> None:
    for bad in ("k" * 42, "k" * 44, "k" * 42 + "+", ""):
        with pytest.raises(ValidationError) as ei:
            OrderCreateIn(**valid_body(idempotency_key=bad))
        assert _fields(ei.value.errors()) == {"idempotency_key"}


async def test_ut_val_01_via_router_returns_400_with_fields(make_app, client_factory) -> None:
    client = client_factory(make_app())
    res = await client.post(
        "/api/v1/orders",
        json=valid_body(
            ship_postal_code="100000",
            ship_phone="0901234567a",  # pragma: allowlist secret
            guest_email="no-at",
        ),
        headers=HEADERS,
    )
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["code"] == "validation_error"
    assert {f["name"] for f in body["fields"]} == {
        "ship_postal_code",
        "ship_phone",
        "guest_email",
    }
    assert all(f["reason"] == "format" for f in body["fields"])


async def test_ut_val_01_missing_required_is_400_required(make_app, client_factory) -> None:
    client = client_factory(make_app())
    body = valid_body()
    del body["ship_name"]
    del body["display"]
    res = await client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert res.status_code == 400
    assert {(f["name"], f["reason"]) for f in res.json()["fields"]} == {
        ("ship_name", "required"),
        ("display", "required"),
    }


# ── UT-VAL-02 境界 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("length", [1, 50])
def test_ut_val_02_name_1_and_50_ok(length: int) -> None:
    assert len(OrderCreateIn(**valid_body(ship_name="あ" * length)).ship_name) == length


def test_ut_val_02_name_51_rejected_and_blank_rejected() -> None:
    with pytest.raises(ValidationError) as ei:
        OrderCreateIn(**valid_body(ship_name="あ" * 51))
    assert _fields(ei.value.errors()) == {"ship_name"}
    for blank in ("", " ", "　", "  \t"):
        with pytest.raises(ValidationError) as ei:
            OrderCreateIn(**valid_body(ship_name=blank))
        assert _fields(ei.value.errors()) == {"ship_name"}


def test_ut_val_02_address_200_ok_201_rejected() -> None:
    assert len(OrderCreateIn(**valid_body(ship_address="あ" * 200)).ship_address) == 200
    with pytest.raises(ValidationError) as ei:
        OrderCreateIn(**valid_body(ship_address="あ" * 201))
    assert _fields(ei.value.errors()) == {"ship_address"}


@pytest.mark.parametrize("phone", ["090123456", "090123456789"])
def test_ut_val_02_phone_9_and_12_digits_rejected(phone: str) -> None:
    with pytest.raises(ValidationError) as ei:
        OrderCreateIn(**valid_body(ship_phone=phone))
    assert _fields(ei.value.errors()) == {"ship_phone"}


@pytest.mark.parametrize("phone", ["0312345678", "09012345678"])
def test_ut_val_02_phone_10_and_11_digits_ok(phone: str) -> None:
    assert OrderCreateIn(**valid_body(ship_phone=phone)).ship_phone == phone


def test_ut_val_02_email_255_rejected() -> None:
    local = "a" * (255 - len("@example.com"))
    with pytest.raises(ValidationError) as ei:
        OrderCreateIn(**valid_body(guest_email=f"{local}@example.com"))
    assert _fields(ei.value.errors()) == {"guest_email"}


async def test_ut_val_02_name_51_via_router_is_too_long(make_app, client_factory) -> None:
    client = client_factory(make_app())
    res = await client.post("/api/v1/orders", json=valid_body(ship_name="あ" * 51), headers=HEADERS)
    assert res.status_code == 400
    assert res.json()["fields"] == [{"name": "ship_name", "reason": "too_long"}]


# ── ST 検収指摘: 空文字・空白のみは reason=required（4.5 の固定語） ────────────


@pytest.mark.parametrize("blank", ["", "   ", "　", "  \t"])
async def test_ut_val_02_name_blank_via_router_is_required(
    make_app, client_factory, blank: str
) -> None:
    client = client_factory(make_app())
    res = await client.post("/api/v1/orders", json=valid_body(ship_name=blank), headers=HEADERS)
    assert res.status_code == 400, res.text
    assert res.json()["fields"] == [{"name": "ship_name", "reason": "required"}]


async def test_ut_val_02_name_1_char_via_router_ok(make_app, client_factory) -> None:
    """1 文字は許容（min_length=1）。検証は通り、DB を見る段階（カート無し）で先へ進む。"""
    client = client_factory(make_app())
    res = await client.post("/api/v1/orders", json=valid_body(ship_name="a"), headers=HEADERS)
    assert res.status_code != 400, res.text
    assert res.json().get("code") != "validation_error"


async def test_ut_val_02_address_empty_via_router_is_required(make_app, client_factory) -> None:
    client = client_factory(make_app())
    res = await client.post("/api/v1/orders", json=valid_body(ship_address=""), headers=HEADERS)
    assert res.status_code == 400, res.text
    assert res.json()["fields"] == [{"name": "ship_address", "reason": "required"}]
