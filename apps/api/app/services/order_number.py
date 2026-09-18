"""注文番号生成（DS-PRC-014-1 手順 8・UT-014-01/02・プラン 5 章「注文番号の日付は JST」）。

`GU-YYMMDD-XXXXXXXX`。日付は JST、8 文字は `secrets.choice` で英大文字＋数字から
紛らわしい I・O・0・1 を除いた 32 文字。UNIQUE 衝突時の 1 回再生成は repositories/orders 側。
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

# A-Z から I・O、0-9 から 0・1 を除いた 32 文字
ORDER_NUMBER_ALPHABET = "".join(c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789" if c not in "IO")  # pragma: allowlist secret  # noqa: E501
ORDER_NUMBER_RANDOM_LENGTH = 8
ORDER_NUMBER_RE = re.compile(r"^GU-\d{6}-[A-HJ-NP-Z2-9]{8}$")


def generate_order_number(now: datetime | None = None) -> str:
    """注文番号を 1 つ生成する。`now` は tz 付き datetime（省略時は現在時刻）。"""
    current = now if now is not None else datetime.now(JST)
    date_part = current.astimezone(JST).strftime("%y%m%d")
    rand = "".join(secrets.choice(ORDER_NUMBER_ALPHABET) for _ in range(ORDER_NUMBER_RANDOM_LENGTH))
    return f"GU-{date_part}-{rand}"
