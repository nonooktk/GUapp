"""コードトレーサー素材用: ローカル DB の読み取り専用スナップショット（SELECT のみ）。

使い方（capture.py が呼ぶ。単体でも動く）:
  cd ~/GUapp/apps/api && PRODUCT_ID=31 CART_TOKEN=... uv run --env-file .env python <このファイル>
標準出力に JSON を 1 つ出す。接続文字列・.env の中身は出力しない。
氏名・住所・電話・メールは取得しない。
"""

import asyncio
import json
import os
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


def _jsonable(v):
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    return v


async def main() -> None:
    engine = create_async_engine(get_settings().DATABASE_URL)
    product_id = int(os.environ["PRODUCT_ID"])
    cart_token = os.environ.get("CART_TOKEN", "")
    out: dict = {}
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id, color, size, stock FROM variants WHERE product_id = :pid ORDER BY id"),
                {"pid": product_id},
            )
        ).mappings().all()
        out["variants"] = [dict(r) for r in rows]

        out["orders_count"] = (await conn.execute(text("SELECT COUNT(*) FROM orders"))).scalar_one()
        latest = (
            await conn.execute(
                text(
                    "SELECT id, order_number, status, total, created_at FROM orders ORDER BY id DESC LIMIT 1"
                )
            )
        ).mappings().first()
        if latest is None:
            out["latest_order"] = None
            out["latest_order_items"] = []
        else:
            out["latest_order"] = {k: _jsonable(latest[k]) for k in ("order_number", "status", "total", "created_at")}
            items = (
                await conn.execute(
                    text(
                        "SELECT variant_id, quantity, unit_price_at_order AS unit_price "
                        "FROM order_items WHERE order_id = :oid ORDER BY id"
                    ),
                    {"oid": latest["id"]},
                )
            ).mappings().all()
            out["latest_order_items"] = [dict(r) for r in items]

        if cart_token:
            cart = (
                await conn.execute(
                    text("SELECT id, status FROM carts WHERE anonymous_token = :t"),
                    {"t": cart_token},
                )
            ).mappings().first()
            if cart is None:
                out["cart"] = None
            else:
                items = (
                    await conn.execute(
                        text("SELECT variant_id, quantity FROM cart_items WHERE cart_id = :cid ORDER BY id"),
                        {"cid": cart["id"]},
                    )
                ).mappings().all()
                out["cart"] = {"status": cart["status"], "items": [dict(r) for r in items]}
        else:
            out["cart"] = None
    await engine.dispose()
    print(json.dumps(out, ensure_ascii=False, default=str))


asyncio.run(main())
