"""テスト専用ルート（`APP_ENV=test` のときだけ `create_app` が登録する。他環境では 404）。

- `GET /_test/metrics`  → `{"inflight_now", "inflight_max"}`（注文確定の同時処理中カウンタ。1.4 #2）
- `POST /_test/reset`   → カウンタとレート制限器を初期化

`app.core.testing_hooks` を import するので、本番経路（`app.main` のモジュール読込）からは
参照しない（create_app の `if settings.is_test:` 内で遅延 import）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core import testing_hooks

router = APIRouter(prefix="/_test", tags=["_test"], include_in_schema=False)


@router.get("/metrics")
async def metrics() -> dict[str, int]:
    return {
        "inflight_now": testing_hooks.allocation_counter.current,
        "inflight_max": testing_hooks.allocation_counter.max_seen,
    }


@router.post("/reset")
async def reset(request: Request) -> dict[str, str]:
    testing_hooks.allocation_counter.reset()
    limiter = getattr(request.app.state, "lookup_rate_limiter", None)
    if limiter is not None:
        limiter.reset()
    return {"status": "reset"}
