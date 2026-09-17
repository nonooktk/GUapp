"""IT-020-01 公開設定（MySQL・seed 必須）。3 キーのみ返し、内部設定は含まない。"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import INTERNAL_ERROR_BODY
from app.models import SystemSetting
from tests.conftest import TEST_INTERNAL_TOKEN

HEADERS = {"X-Internal-Token": TEST_INTERNAL_TOKEN}


async def test_it_020_01_only_three_public_keys(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    client = client_factory(it_app)
    res = await client.get("/api/v1/settings/public", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "tax_rate": "0.10",
        "shipping_fee": 550,
        "free_shipping_threshold": 4990,
    }
    assert "payment_timeout_minutes" not in res.text


async def test_it_020_missing_key_is_500_fixed_body(
    it_app: FastAPI, seed_db: AsyncEngine, client_factory
) -> None:
    async with seed_db.begin() as conn:
        await conn.execute(delete(SystemSetting).where(SystemSetting.key == "shipping_fee"))
    client = client_factory(it_app)
    res = await client.get("/api/v1/settings/public", headers=HEADERS)
    assert res.status_code == 500
    assert res.json() == INTERNAL_ERROR_BODY
