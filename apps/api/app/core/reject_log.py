"""拒否したときの 1 行ログ（セキュリティ強化 S9）。

401（内部トークン不一致）・429（回数制限）を `logger.warning` で 1 行出す。
項目は event／path／method／status／code／ip。本文・Cookie・トークン・個人情報は出さない。
IP は丸める（IPv4 は末尾 1 オクテットを 0、IPv6 は先頭 3 ブロック以外を 0）。
出力は既存の `SecretMaskFilter`（`setup_logging`）を通る。
"""

from __future__ import annotations

import ipaddress
import json
import logging

from fastapi import Request

logger = logging.getLogger("app.security")

REJECT_EVENT = "request_rejected"


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


def log_rejection(request: Request, *, status: int, code: str, ip: str) -> None:
    """拒否ログを 1 行出す。`path` はクエリを含まない URL パスだけ。"""
    record = {
        "event": REJECT_EVENT,
        "path": request.url.path,
        "method": request.method,
        "status": status,
        "code": code,
        "ip": mask_ip(ip),
    }
    logger.warning("%s", json.dumps(record, ensure_ascii=False))
