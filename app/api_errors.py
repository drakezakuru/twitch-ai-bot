"""Shared HTTP error responses for the v13 compatibility API."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "request_invalid",
    429: "rate_limited",
    500: "internal_error",
}


def _safe_code(value: Any, fallback: str) -> str:
    code = str(value or "").strip()
    return code if _CODE_RE.fullmatch(code) else fallback


def _safe_params(value: Any) -> dict[str, str | int | float | bool | None]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str | int | float | bool | None] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if not _PARAM_RE.fullmatch(key):
            continue
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            result[key] = raw_value
        elif isinstance(raw_value, str):
            result[key] = raw_value[:200]
    return result


def error_payload(code: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": _safe_code(code, "request_failed"),
            "params": _safe_params(params),
        },
    }


def install_api_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException,
    ) -> JSONResponse:
        fallback = _STATUS_CODES.get(exc.status_code, "request_failed")
        detail = exc.detail
        if isinstance(detail, Mapping):
            code = _safe_code(detail.get("code"), fallback)
            params = detail.get("params")
        else:
            code = fallback
            params = None
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code, params),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content=error_payload("request_invalid"))

    @app.exception_handler(Exception)
    async def internal_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error [%s %s]", request.method, request.url.path)
        return JSONResponse(status_code=500, content=error_payload("internal_error"))
