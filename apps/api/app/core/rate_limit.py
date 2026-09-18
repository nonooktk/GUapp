"""レート制限（設計仕様書 7.5「総当たり」・4.5 の順序 6・IT-023-02）。

プロセス内メモリのスライディングウィンドウ。IP ごとに直近 `window_seconds` の呼び出し時刻を
持ち、`limit` 回を超えたら 429 `rate_limited` ＋ `Retry-After`。
P1 はローカル 1 プロセス前提なのでプロセス内で十分（複数インスタンスでは Redis 等に置き換える）。
IP は `X-Forwarded-For` の先頭、無ければ接続元。
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.core.errors import AppError

LOOKUP_LIMIT = 100
LOOKUP_WINDOW_SECONDS = 3600


class SlidingWindowRateLimiter:
    """キーごとの呼び出し回数を数える。`hit()` は制限内なら None、超過なら Retry-After 秒を返す。"""

    def __init__(
        self,
        *,
        limit: int = LOOKUP_LIMIT,
        window_seconds: int = LOOKUP_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = float(window_seconds)
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> int | None:
        now = self._clock()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return max(1, math.ceil(q[0] + self.window - now))
        q.append(now)
        return None

    def reset(self) -> None:
        self._hits.clear()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def lookup_rate_limit(request: Request) -> None:
    """DS-API-023 用の依存関数。制限器は `app.state.lookup_rate_limiter`（app ごとに 1 つ）。"""
    limiter: SlidingWindowRateLimiter = request.app.state.lookup_rate_limiter
    retry_after = limiter.hit(client_ip(request))
    if retry_after is not None:
        raise AppError(429, "rate_limited", headers={"Retry-After": str(retry_after)})
