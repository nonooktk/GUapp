"""Azure MySQL への疎通確認（IT-AZ-01・02、DS-DEC-42 の実接続の試行）。

`DATABASE_URL`（環境変数）から `app.core.db.build_engine()` でエンジンを作り、
`SELECT 1` と `SHOW STATUS LIKE 'Ssl_cipher'` を実行する。書き込みは一切行わない
（読み取り専用の確認。テスト設計書追補 IT-AZ-01）。

パスワードを一切標準出力・エラー出力に出さない。接続文字列を直接 print しない。
万一 SQLAlchemy 等の例外メッセージに接続文字列が含まれる場合に備え、
例外を表示する前に `mask_url()` でパスワード部分を伏せ字にする。

使い方（scripts/azure-db/with-azure-db.sh 経由での実行を想定。DATABASE_URL は
ラッパースクリプトが環境変数として渡す。ここでは値を一切表示しない）:

    scripts/azure-db/with-azure-db.sh uv run --directory apps/api python \
        ../../scripts/azure-db/check_connection.py

または apps/api を cwd にして:

    (DATABASE_URL を環境変数にセットした状態で)
    uv run python /path/to/scripts/azure-db/check_connection.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

# app.core.db を import するため apps/api を sys.path に通す
_API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))


def mask_url(url: str) -> str:
    """接続文字列のパスワード部分を伏せ字にする（エラーメッセージ表示用）。"""
    # mysql+asyncmy://user:PASSWORD@host:port/db?... の PASSWORD 部分だけを消す  # pragma: allowlist secret  # gitleaks:allow
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", url)


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL が未設定です（環境変数で与えてください）", file=sys.stderr)
        return 2

    from sqlalchemy import text

    from app.core.db import build_engine

    pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "5"))

    engine = build_engine(database_url, pool_size=pool_size, max_overflow=max_overflow)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            one = result.scalar_one()
            print(f"[check_connection] SELECT 1 -> {one}")

            cipher_row = (
                await conn.execute(text("SHOW STATUS LIKE 'Ssl_cipher'"))
            ).fetchone()
            cipher = cipher_row[1] if cipher_row else "(なし＝平文接続)"
            print(f"[check_connection] Ssl_cipher -> {cipher}")

            version_row = (
                await conn.execute(text("SHOW STATUS LIKE 'Ssl_version'"))
            ).fetchone()
            version = version_row[1] if version_row else "(なし)"
            print(f"[check_connection] Ssl_version -> {version}")
        print("[check_connection] 接続成功")
        return 0
    except Exception as exc:  # noqa: BLE001
        # 例外メッセージに接続文字列（パスワード含む）が含まれる可能性があるためマスクする
        masked = mask_url(str(exc))
        print(f"[check_connection] 接続失敗: {type(exc).__name__}: {masked}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
