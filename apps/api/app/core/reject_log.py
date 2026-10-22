"""拒否したときの 1 行ログ（セキュリティ強化 S9）。

401（内部トークン不一致）・429（回数制限）を `logger.warning` で 1 行出す。
項目は event／path／method／status／code／ip。本文・Cookie・トークン・個人情報は出さない。
IP は丸める（IPv4 は末尾 1 オクテットを 0、IPv6 は先頭 3 ブロック以外を 0）。

識別子があるもの（ログイン失敗・ロック・再設定の拒否など）は、どのアカウントが狙われたかを追えるよう
`subject` を足す（G-19）。値は「正規化した識別子（メールは小文字化、管理 ID はそのまま）の
SHA-256 の先頭 12 桁」だけで、生のメール・ID は出さない。呼び手は `login_attempts.identifier` と
同じ SHA-256（16 進 64 文字）を渡す。
出力は既存の `SecretMaskFilter`（`setup_logging`）を通る。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re

from fastapi import Request

logger = logging.getLogger("app.security")

REJECT_EVENT = "request_rejected"
SUBJECT_LENGTH = 12
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")


def mask_ip(ip: str) -> str:
    """IP を丸める。解釈できない値は `unknown`（元の文字列をログに出さない）。"""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return "unknown"
    if isinstance(addr, ipaddress.IPv4Address):
        a, b, c, _ = addr.packed
        return str(ipaddress.IPv4Address(bytes((a, b, c, 0))))
    # IPv6: 先頭 3 ブロック（48 ビット）だけ残す
    return str(ipaddress.IPv6Address(addr.packed[:6] + bytes(10)))


def subject_fingerprint(identifier_sha256: str) -> str | None:
    """識別子の SHA-256（16 進 64 文字）の先頭 12 桁。形が違う値（生のメールなど）は None。"""
    if _SHA256_HEX_RE.fullmatch(identifier_sha256) is None:
        return None
    return identifier_sha256[:SUBJECT_LENGTH]


def log_rejection(
    request: Request, *, status: int, code: str, ip: str, subject: str | None = None
) -> None:
    """拒否ログを 1 行出す。`path` はクエリを含まない URL パスだけ。

    `subject` は識別子の SHA-256（16 進 64 文字）。先頭 12 桁だけを `subject` として出す。
    SHA-256 の形でない値は、生の値の混入を避けるため出さない。
    """
    record: dict[str, str | int] = {
        "event": REJECT_EVENT,
        "path": request.url.path,
        "method": request.method,
        "status": status,
        "code": code,
        "ip": mask_ip(ip),
    }
    if subject is not None:
        fingerprint = subject_fingerprint(subject)
        if fingerprint is not None:
            record["subject"] = fingerprint
    logger.warning("%s", json.dumps(record, ensure_ascii=False))
