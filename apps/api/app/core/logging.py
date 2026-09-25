"""ロギングと秘密マスクフィルタ（設計仕様書 7.2「ログ」・UT-SEC-01）。

マスク対象:
- Stripe キー `sk_live_…`／`sk_test_…`（`rk_`／`whsec_` も同様）
- 接続文字列 `scheme://user:pass@host` のユーザー名:パスワード部分  # pragma: allowlist secret
- `Bearer <token>`
- `X-Internal-Token: <値>` ヘッダ形式
- `INTERNAL_TOKEN` の実値（設定から受け取る。空なら対象外）
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable

MASK = "***"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Stripe 系キー
    (re.compile(r"\b(sk|rk|pk)_(live|test)_[A-Za-z0-9]+"), r"\1_\2_" + MASK),
    (re.compile(r"\bwhsec_[A-Za-z0-9]+"), "whsec_" + MASK),
    # URL 中の資格情報 scheme://user:pass@  → scheme://***:***@  # pragma: allowlist secret
    (
        re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"),
        r"\1" + MASK + ":" + MASK + "@",
    ),
    # Bearer トークン
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer " + MASK),
    # X-Internal-Token ヘッダ（"X-Internal-Token: xxx" / "x-internal-token=xxx" / JSON 形式）
    (
        re.compile(r"(?i)(x-internal-token[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
        r"\1" + MASK,
    ),
]


class SecretMaskFilter(logging.Filter):
    """ログレコードのメッセージと引数から秘密パターンを潰すフィルタ。"""

    def __init__(self, extra_secrets: Iterable[str] = ()) -> None:
        super().__init__()
        # 4 文字未満の値は誤マスクの危険が大きいので対象外
        self._secrets = [s for s in extra_secrets if s and len(s) >= 4]

    def mask(self, text: str) -> str:
        for pattern, repl in _PATTERNS:
            text = pattern.sub(repl, text)
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        return text

    def _mask_value(self, value: object) -> object:
        return self.mask(value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        # msg と args を個別にマスクし、args の構造は保つ。
        # uvicorn の AccessFormatter は record.args（5 要素タプル）を展開するため、
        # args を潰すと毎リクエストで Logging error になる（実起動で確認済み）。
        if isinstance(record.msg, str):
            record.msg = self.mask(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(self._mask_value(a) for a in args)
        elif isinstance(args, dict):
            record.args = {k: self._mask_value(v) for k, v in args.items()}
        elif args is not None:
            record.args = self._mask_value(args)  # type: ignore[assignment]
        if record.exc_text:
            record.exc_text = self.mask(record.exc_text)
        return True


def setup_logging(level: int = logging.INFO, extra_secrets: Iterable[str] = ()) -> SecretMaskFilter:
    """ルートロガーを構成し、全ハンドラにマスクフィルタを付ける。戻り値は付けたフィルタ。"""
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)

    mask_filter = SecretMaskFilter(extra_secrets)
    for handler in root.handlers:
        # 同種フィルタの重複を避ける
        for existing in list(handler.filters):
            if isinstance(existing, SecretMaskFilter):
                handler.removeFilter(existing)
        handler.addFilter(mask_filter)

    # uvicorn のロガーは propagate しない設定になることがあるので個別にも付ける
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            for existing in list(handler.filters):
                if isinstance(existing, SecretMaskFilter):
                    handler.removeFilter(existing)
            handler.addFilter(mask_filter)
    return mask_filter
