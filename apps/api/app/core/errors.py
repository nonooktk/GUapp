"""エラー応答の統一（設計仕様書 4.5・DS-DEC-32）。

- 業務エラーは `AppError(status, code, **detail)` 1 系統で投げ、ハンドラ 1 か所で
  `{code, ...detail}` に変換する。ルーターに `HTTPException` を直接書かない。
- Pydantic の入力検証エラー（FastAPI 既定 422）は 400 `validation_error` に変換する。
  reason は固定語 required／format／too_long／out_of_range。
- 未捕捉例外は 500 固定文言。詳細（スタックトレース）はログのみ。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")

INTERNAL_ERROR_BODY: dict[str, str] = {
    "code": "internal_error",
    "message": "処理中にエラーが発生しました",
}

# Pydantic v2 のエラー型 → 4.5 の reason 固定語
# 参考: https://docs.pydantic.dev/latest/errors/validation_errors/
_REASON_REQUIRED = {"missing"}
_REASON_TOO_LONG = {"string_too_long", "too_long"}
_REASON_OUT_OF_RANGE = {
    "greater_than",
    "greater_than_equal",
    "less_than",
    "less_than_equal",
    "too_short",
    "string_too_short",
    "multiple_of",
    "finite_number",
}


class AppError(Exception):
    """業務エラー。`status` と `code` に加え、任意の詳細を本文へ載せる。

    例: `AppError(409, "out_of_stock", items=[1, 2])`
        → 409 `{"code": "out_of_stock", "items": [1, 2]}`
    """

    def __init__(self, status: int, code: str, **detail: Any) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code
        self.detail = detail

    def to_body(self) -> dict[str, Any]:
        # code を先頭に置く（detail が code を上書きしないよう順序を固定）
        body: dict[str, Any] = {"code": self.code}
        for key, value in self.detail.items():
            if key != "code":
                body[key] = value
        return body


def internal_error() -> AppError:
    """サービス層から明示的に 500 を返すとき用（本文は未捕捉例外と同じ固定文言）。"""
    return AppError(500, "internal_error", message=INTERNAL_ERROR_BODY["message"])


def map_reason(error_type: str) -> str:
    """Pydantic のエラー型文字列を reason 固定語へ対応付ける。"""
    if error_type in _REASON_REQUIRED:
        return "required"
    if error_type in _REASON_TOO_LONG:
        return "too_long"
    if error_type in _REASON_OUT_OF_RANGE:
        return "out_of_range"
    # 型不一致（int_parsing など）・パターン不一致・enum 外・メール形式などはすべて format
    return "format"


def _field_name(loc: tuple[Any, ...]) -> str:
    """loc から入力項目名を作る。先頭の body/query/path/header は除く。"""
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts) if parts else "body"


def validation_error_body(exc: RequestValidationError) -> dict[str, Any]:
    fields: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for err in exc.errors():
        name = _field_name(tuple(err.get("loc", ())))
        reason = map_reason(str(err.get("type", "")))
        key = (name, reason)
        if key in seen:
            continue
        seen.add(key)
        fields.append({"name": name, "reason": reason})
    return {"code": "validation_error", "fields": fields}


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.to_body())


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content=validation_error_body(exc))


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # 詳細はログのみ（マスクフィルタ経由）。本文は固定文言で、
    # 例外メッセージ・SQL・接続文字列を出さない
    logger.exception(
        "未捕捉例外 %s %s: %s", request.method, request.url.path, type(exc).__name__
    )
    return JSONResponse(status_code=500, content=INTERNAL_ERROR_BODY)


def install_error_handlers(app: FastAPI) -> None:
    """4.5 の規則に沿った例外ハンドラを 1 か所で登録する。"""
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_error_handler)
