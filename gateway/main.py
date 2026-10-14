"""Moderator gateway: a separate ASGI app (MOD-03).

The gateway runs as its own process. It never imports app.server at request time
(registry validation uses a lazy import only in offline contract tests) and proxies
exactly the routes listed in routes.GATEWAY_ROUTES — everything else is default-deny.
"""
from __future__ import annotations

import hmac
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from gateway import security
from gateway.bridge_client import BridgeClient
from gateway.routes import resolve, UNAUTHENTICATED_PATHS

GATEWAY_TOKEN_ENV = "MODERATOR_SITE_TOKEN"

gateway_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _browser_authorized(request: Request) -> bool:
    expected = os.environ.get(GATEWAY_TOKEN_ENV, "")
    if not expected:
        return False  # fail-closed
    provided = request.headers.get("X-Moderator-Site-Auth", "")
    return bool(provided) and hmac.compare_digest(provided, expected)


@gateway_app.middleware("http")
async def _security_middleware(request: Request, call_next):
    # Host allowlist (exact) — deployment-scoped; unset keeps local dev usable.
    if not security.host_allowed(request.headers.get("host"), security.env_list("MODERATOR_SITE_ALLOWED_HOSTS")):
        return JSONResponse(status_code=403, content={"detail": {"code": "host_not_allowed"}})
    # Request size bound before touching the bridge.
    length = request.headers.get("content-length")
    if length and int(length) > security.MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": {"code": "payload_too_large"}})
    return await call_next(request)


@gateway_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def _dispatch(request: Request, path: str) -> dict:
    if not _browser_authorized(request):
        raise HTTPException(status_code=403, detail={"code": "gateway_unauthorized"})
    target = f"/{path}"
    route = resolve(target)
    if route is None or route.method != request.method:
        # Default-deny first: unmapped or method-mismatched paths never reach the
        # bridge and do not even reveal that a session would be required.
        raise HTTPException(status_code=404, detail={"code": "gateway_not_found"})
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        # Exact origin validation for browser mutations, after default-deny so unmapped
        # paths stay 404; Origin "null" is never valid (MOD-06).
        if not security.origin_allowed(request.headers.get("origin"), security.env_list("MODERATOR_SITE_ALLOWED_ORIGINS")):
            raise HTTPException(status_code=403, detail={"code": "origin_not_allowed"})
    if target not in UNAUTHENTICATED_PATHS:
        cookie = request.cookies.get("ms_session", "")
        if not cookie:
            raise HTTPException(status_code=401, detail={"code": "session_required"})
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            # Server-bound CSRF double-submit: header must match the session-derived
            # cookie value; missing or mismatched header = 403 (MOD-06).
            if not security.csrf_valid(request.cookies.get("ms_session"), request.headers.get(security.CSRF_HEADER)):
                raise HTTPException(status_code=403, detail={"code": "csrf_required"})
    client = BridgeClient()
    try:
        response = await client.request(route.method, route.bridge_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"code": str(exc)}) from exc
    except httpx.HTTPError as exc:  # type: ignore[name-defined]
        raise HTTPException(status_code=502, detail={"code": "bridge_unreachable"}) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail={"code": "bridge_error"})
    payload = response.json()
    if target == "/moderator-site/identity/exchange" and "cookie_token" in payload:
        # HttpOnly session cookie: the Twitch access token never reaches JS (MOD-05).
        cookie_token = payload.pop("cookie_token")
        # Server-bound CSRF token for later mutations (MOD-06): readable by JS,
        # verified against the session-derived value on the server.
        csrf = security.csrf_token_for(cookie_token)
        max_age = int(payload.get("expires_in", 43200))
        response = JSONResponse(content={**payload, "csrf_token": csrf})
        response.headers.append("set-cookie", f"ms_session={cookie_token}; HttpOnly; SameSite=Strict; "
                                              f"Path=/moderator-site; Max-Age={max_age}")
        response.headers.append("set-cookie", f"{security.CSRF_COOKIE}={csrf}; SameSite=Strict; "
                                              f"Path=/moderator-site; Max-Age={max_age}")
        return response
    return payload
