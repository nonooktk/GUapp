"""レート制限（設計仕様書 7.5「総当たり」・4.5 の順序 6・IT-023-02）。

プロセス内メモリのスライディングウィンドウ。IP ごとに直近 `window_seconds` の呼び出し時刻を
持ち、`limit` 回を超えたら 429 `rate_limited` ＋ `Retry-After`。
P1 はローカル 1 プロセス前提なのでプロセス内で十分（複数インスタンスでは Redis 等に置き換える）。
IP は `X-Forwarded-For` の末尾の要素（BFF が検証済みの 1 要素を付ける前提。
複数なら末尾が直前のホップ）、無ければ接続元。
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from app.core.errors import AppError
from app.core.reject_log import log_rejection

LOOKUP_LIMIT = 100
LOOKUP_WINDOW_SECONDS = 3600


@dataclass(frozen=True)
class RateLimitSpec:
    """名前つきの制限器 1 つ分の設定。"""

    limit: int
    window_seconds: int


# P2-b の個別制限（設計仕様書 P2 追補b DS-DEC-84。IP ごと、プロセス内メモリ）。
# ログインだけは DB の `login_attempts` で数える（DS-DEC-70）ので、ここには無い。
# キーは `build_rate_limiters()` が作る `app.state.rate_limiters` の名前と一致する。
RATE_LIMIT_SPECS: dict[str, RateLimitSpec] = {
    # DS-API-030 会員登録
    "register": RateLimitSpec(10, 3600),
    # DS-API-031 メール確認
    "verify_email": RateLimitSpec(20, 3600),
    # DS-API-034 再設定の要求（IP ごとに 5 回/時、メールごとに 3 回/時の 2 本）
    "password_reset_request": RateLimitSpec(5, 3600),
    "password_reset_request_email": RateLimitSpec(3, 3600),
    # DS-API-035 再設定の確定
    "password_reset_confirm": RateLimitSpec(10, 3600),
    # DS-API-007 再入荷通知の申込
    "restock": RateLimitSpec(20, 3600),
}


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
    """`X-Forwarded-For` の末尾の要素。先頭は呼び出し元が偽れるので使わない（G-14）。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def lookup_rate_limit(request: Request) -> None:
    """DS-API-023 用の依存関数。制限器は `app.state.lookup_rate_limiter`（app ごとに 1 つ）。"""
    limiter: SlidingWindowRateLimiter = request.app.state.lookup_rate_limiter
    ip = client_ip(request)
    retry_after = limiter.hit(ip)
    if retry_after is not None:
        log_rejection(request, status=429, code="rate_limited", ip=ip)
        raise AppError(429, "rate_limited", headers={"Retry-After": str(retry_after)})


def build_rate_limiters() -> dict[str, SlidingWindowRateLimiter]:
    """`RATE_LIMIT_SPECS` の名前ごとに制限器を作る。`create_app()` が `app.state` に載せる。

    担当レーン: A（部品）。使うのは B（register・verify_email・password_reset_*）と
    C（restock）。設計仕様書 P2 追補b DS-DEC-84。
    """
    return {
        name: SlidingWindowRateLimiter(limit=spec.limit, window_seconds=spec.window_seconds)
        for name, spec in RATE_LIMIT_SPECS.items()
    }


def enforce_rate_limit(request: Request, name: str, key: str | None = None) -> None:
    """名前つきの制限器で 1 回数える。超過なら 429 `rate_limited` ＋ `Retry-After`。

    `key` を省略すると IP（`client_ip`）で数える。メール単位など別のキーで数えるときは
    呼び出し側が `key` を渡す（例: DS-API-034 の `password_reset_request_email`。キーは
    正規化したメールの SHA-256 など、平文のメールを避けた値にする）。

    担当レーン: A（部品）。設計仕様書 P2 追補b 4.0・DS-DEC-84。
    """
    limiter: SlidingWindowRateLimiter = request.app.state.rate_limiters[name]
    ip = client_ip(request)
    retry_after = limiter.hit(key if key is not None else ip)
    if retry_after is not None:
        # key が識別子の SHA-256 なら、狙われたアカウントを追えるよう先頭 12 桁を出す（G-19）
        log_rejection(request, status=429, code="rate_limited", ip=ip, subject=key)
        raise AppError(429, "rate_limited", headers={"Retry-After": str(retry_after)})


def ip_rate_limit(name: str) -> Callable[[Request], None]:
    """IP ごとの制限を掛ける依存関数を作る（`dependencies=[Depends(ip_rate_limit("register"))]`）。

    担当レーン: A（部品）。名前は `RATE_LIMIT_SPECS` のキー。未知の名前は起動時に気づけるよう、
    ここ（生成時）で検査する。
    """
    if name not in RATE_LIMIT_SPECS:
        raise ValueError(f"未定義の制限器です: {name}")

    def _dependency(request: Request) -> None:
        enforce_rate_limit(request, name)

    return _dependency
