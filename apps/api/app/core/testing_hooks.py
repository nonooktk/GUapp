"""テストモード限定の同時性フック（テスト設計書 1.4 #2・#7、プラン 5 章）。

- 「同時処理中カウンタ」: 現在値と最大値。IT で最大値 >= 2 を assert し同時性を証明する。
- 「任意の遅延（ms）」: 引当の読み書き間に待ちを入れ、競合の窓を広げる。

`APP_ENV=test` 以外では全て no-op。本番経路（`app.main` など）はこのモジュールを import しない。
使う側（Wave 2 のサービス層）は `if settings.is_test:` の内側で遅延 import する。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from app.core.config import get_settings


def _enabled() -> bool:
    return get_settings().is_test


@dataclass
class ConcurrencyCounter:
    """同時処理中カウンタ。"""

    current: int = 0
    max_seen: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def enter(self) -> None:
        if not _enabled():
            return
        async with self._lock:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)

    async def leave(self) -> None:
        if not _enabled():
            return
        async with self._lock:
            self.current -= 1

    def reset(self) -> None:
        self.current = 0
        self.max_seen = 0

    @asynccontextmanager
    async def track(self):
        await self.enter()
        try:
            yield
        finally:
            await self.leave()


# 引当処理用のカウンタ（プロセス内 1 つ）
allocation_counter = ConcurrencyCounter()

# 任意遅延（ms）。テストが set_delay_ms で設定する
_delay_ms: int = 0


def set_delay_ms(ms: int) -> None:
    """遅延を設定する。テスト以外では無視。"""
    global _delay_ms
    if not _enabled():
        return
    _delay_ms = max(0, int(ms))


def get_delay_ms() -> int:
    return _delay_ms if _enabled() else 0


async def maybe_delay() -> None:
    """設定された遅延だけ待つ。テスト以外・0ms なら即 return。"""
    if not _enabled():
        return
    if _delay_ms > 0:
        await asyncio.sleep(_delay_ms / 1000)


def reset_all() -> None:
    """テスト間の後始末。"""
    global _delay_ms
    allocation_counter.reset()
    _delay_ms = 0
