"""受け取りコードの生成（DS-DEC-79・DS-PRC-014-3 手順 1）。

8 文字。文字集合は注文番号と同じ（`ORDER_NUMBER_ALPHABET`: A-Z と 2-9 から I・O を除いた 32 文字）、
`secrets.choice`（暗号論的乱数）で選ぶ。第三者が推測すると受け取りを横取りできるため、
32^8（約 1.1×10^12）の空間にする。UNIQUE 制約との衝突時の 1 回再生成は repositories/orders。
"""

from __future__ import annotations

import re
import secrets

from app.services.order_number import ORDER_NUMBER_ALPHABET

PICKUP_CODE_LENGTH = 8
PICKUP_CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


def generate_pickup_code() -> str:
    return "".join(secrets.choice(ORDER_NUMBER_ALPHABET) for _ in range(PICKUP_CODE_LENGTH))
