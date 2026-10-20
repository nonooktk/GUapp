"""パスワードのハッシュ化・検証・再ハッシュ（DS-DEC-68。設計仕様書 P2 追補b 7.1・9.1）。

- アルゴリズムは argon2id（`argon2-cffi`）。パラメータは OWASP の最小構成
  （メモリ 19 MiB・反復 2・並列 1。ハッシュ長 32・ソルト 16 は既定）。
  `app/seed.py` の `_hash_password` と同じ値にする（変えるときは両方）。
- 計算は同期関数 `hash_password` / `verify_password` に集め、非同期のラッパー
  （`*_async`）がスレッドプールで実行する。**同時に走る計算は 2 本まで**
  （F1 のメモリ 1 GB に対し 19 MiB × 2 に抑える。8.2）。
- 会員と管理者（P2-c）が共用する。
- `verify_password` は例外を投げない（壊れたハッシュ・別アルゴリズムのハッシュ・空文字は False）。
- 会員がいないときの「ダミー検証」用に、同じパラメータで作ったハッシュ `dummy_hash()` を持つ
  （応答時間を会員の有無で変えない。DS-DEC-71）。
"""

from __future__ import annotations

import asyncio
import weakref

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

# DS-DEC-68。変えるときは app/seed.py の _hash_password も揃える
TIME_COST = 2
MEMORY_COST_KIB = 19456
PARALLELISM = 1

# 同時に走らせるハッシュ計算の上限（DS-DEC-68）
MAX_CONCURRENT_HASHES = 2

_HASHER = PasswordHasher(time_cost=TIME_COST, memory_cost=MEMORY_COST_KIB, parallelism=PARALLELISM)

# ダミー検証に使う文字列。実在の会員のパスワードではない。このハッシュに照合が一致しても、
# 呼び出し側は「会員がいない」ことを理由に必ず失敗として扱う
_DUMMY_PLAIN = "dummy-password-for-constant-time-verification"  # pragma: allowlist secret
# import 時に 1 回だけ計算する（初回のログインだけ遅くならないように）
_DUMMY_HASH = _HASHER.hash(_DUMMY_PLAIN)

# イベントループごとの Semaphore（テストはループを作り直すため、モジュール全体で 1 つにしない）
_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def hash_password(plain: str) -> str:
    """argon2id のエンコード済み文字列（`$argon2id$v=19$m=19456,t=2,p=1$…`）を返す。"""
    return _HASHER.hash(plain)


def verify_password(encoded: str | None, plain: str) -> bool:
    """`plain` が `encoded` のハッシュと一致するか。不一致・壊れたハッシュは False（例外なし）。"""
    if not encoded:
        return False
    try:
        return _HASHER.verify(encoded, plain)
    except (Argon2Error, InvalidHashError, ValueError):
        return False


def needs_rehash(encoded: str) -> bool:
    """ハッシュのパラメータが現在の設定と違うか（ログイン成功時に調べる。DS-DEC-68）。"""
    try:
        return _HASHER.check_needs_rehash(encoded)
    except (Argon2Error, InvalidHashError, ValueError):
        return False


def dummy_hash() -> str:
    """会員がいないときの照合先。現在のパラメータで作った固定のハッシュ。"""
    return _DUMMY_HASH


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_HASHES)
        _semaphores[loop] = semaphore
    return semaphore


async def hash_password_async(plain: str) -> str:
    """スレッドプールで `hash_password` を実行する（同時 2 本まで）。"""
    async with _semaphore():
        return await asyncio.to_thread(hash_password, plain)


async def verify_password_async(encoded: str | None, plain: str) -> bool:
    """スレッドプールで `verify_password` を実行する（同時 2 本まで）。"""
    async with _semaphore():
        return await asyncio.to_thread(verify_password, encoded, plain)
