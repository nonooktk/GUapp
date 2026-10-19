"""全応答に付けるセキュリティヘッダ（セキュリティ強化 S5・G-05／G-09）。

API は JSON しか返さないので、ブラウザに解釈させない側へ倒す（nosniff・フレーム禁止・CSP none）。
すでに同名のヘッダが付いている応答は上書きしない（例: 個別に `Cache-Control` を決めた応答）。
`Server` ヘッダは起動コマンドの `--no-server-header` で消すのでここでは触らない。
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=31536000",
    "Cache-Control": "no-store",
}

# 開発時だけ有効な Swagger UI／ReDoc は CDN のスクリプトを読むので、CSP だけ外す（本番は無効化済み）
_DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})


def apply_security_headers(headers: MutableHeaders, *, path: str = "") -> None:
    """未設定のヘッダだけ足す。"""
    for name, value in SECURITY_HEADERS.items():
        if name == "Content-Security-Policy" and path in _DOCS_PATHS:
            continue
        if name not in headers:
            headers[name] = value


class SecurityHeadersMiddleware:
    """純 ASGI のミドルウェア（BaseHTTPMiddleware より例外の扱いが単純）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                apply_security_headers(MutableHeaders(scope=message), path=path)
            await send(message)

        await self.app(scope, receive, send_with_headers)
