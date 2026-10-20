"""再入荷通知の手動実行 CLI（DS-PRC-007a・DS-DEC-80。手動確認用）。

    uv run python -m app.restock_notify --sku GU-029-BK-M

SKU のバリエーションの在庫が 1 以上のとき、未通知の申込にメールを送る（開発は
`apps/api/.mail-outbox/` にファイル出力）。`APP_ENV=production` では実行を拒否する。
管理画面の在庫更新（P2-c）は、更新を COMMIT した後で `services.restock.notify_restock` を呼ぶ。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.adapters.mail import get_mail_adapter
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.models import Variant
from app.services.restock import notify_restock

EXIT_REFUSED = 2
EXIT_NOT_FOUND = 3


async def _run(sku: str) -> int:
    async with get_sessionmaker()() as session:
        variant_id = (
            await session.execute(select(Variant.id).where(Variant.sku == sku))
        ).scalar_one_or_none()
        await session.rollback()
        if variant_id is None:
            print(f"SKU が見つかりません: {sku}", file=sys.stderr)
            return EXIT_NOT_FOUND
        sent = await notify_restock(session, variant_id, mail=get_mail_adapter())
    print(f"送信 {sent} 件")
    return 0


async def _main(sku: str) -> int:
    try:
        return await _run(sku)
    finally:
        await get_engine().dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="再入荷通知を手動で送る（開発・手動確認用）")
    parser.add_argument("--sku", required=True, help="在庫を入れたバリエーションの SKU")
    args = parser.parse_args(argv)
    if get_settings().is_production:
        print("APP_ENV=production では実行できません。", file=sys.stderr)
        return EXIT_REFUSED
    return asyncio.run(_main(args.sku))


if __name__ == "__main__":
    raise SystemExit(main())
