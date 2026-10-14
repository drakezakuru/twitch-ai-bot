"""Closed bridge between the panel runtime and the separate moderator gateway (MOD-03).

The bridge is mounted by the panel on a loopback listener and accepts only explicit
service-authenticated, explicitly-enumerated endpoints. It never imports app.server:
domain logic is exposed through small helper calls, not through the owner router.
"""
from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, HTTPException, Request

BRIDGE_TOKEN_ENV = "MODERATOR_BRIDGE_TOKEN"

bridge_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Explicit bridge surface. Everything not listed here is 404 by design (default-deny,
# no wildcard forwarding); gateway paths are decided one by one, never by prefix.
BRIDGE_ENDPOINTS: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/bridge/health"),
    ("POST", "/bridge/identity/login-attempt"),
    ("POST", "/bridge/identity/exchange"),
    ("POST", "/bridge/identity/logout"),
    ("GET", "/bridge/identity/session"),
})


def _authorized(request: Request) -> bool:
    expected = os.environ.get(BRIDGE_TOKEN_ENV, "")
    if not expected:
        # Fail-closed: an unconfigured bridge serves nothing at all.
        return False
    provided = request.headers.get("X-Moderator-Bridge-Token", "")
    return bool(provided) and hmac.compare_digest(provided, expected)


@bridge_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def _dispatch(request: Request, path: str) -> dict:
    if not _authorized(request):
        raise HTTPException(status_code=403, detail={"code": "bridge_unauthorized"})
    key = (request.method, "/" + path.strip("/"))
    if key not in BRIDGE_ENDPOINTS:
        raise HTTPException(status_code=404, detail={"code": "bridge_not_found"})
    if key == ("GET", "/bridge/health"):
        return {"ok": True, "bridge": "moderator-site", "pid": os.getpid()}
    if key == ("POST", "/bridge/identity/login-attempt"):
        from app.moderator_site_identity import create_login_attempt
        data = await request.json()
        try:
            return await create_login_attempt(
                await _db(), str(data.get("twitch_user_id", "")), str(data.get("twitch_login", "")),
                str(data.get("browser_fingerprint", "")), grant_version=int(data.get("grant_version", 1)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    if key == ("POST", "/bridge/identity/exchange"):
        from app.moderator_site_identity import exchange_login
        data = await request.json()
        try:
            return await exchange_login(
                await _db(), str(data.get("nonce", "")), str(data.get("browser_fingerprint", "")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
    if key == ("POST", "/bridge/identity/logout"):
        from app.moderator_site_identity import logout_session
        data = await request.json()
        return {"logged_out": await logout_session(await _db(), str(data.get("cookie_token", "")))}
    if key == ("GET", "/bridge/identity/session"):
        from app.moderator_site_identity import validate_session
        session = await validate_session(
            await _db(), request.headers.get("X-Moderator-Cookie", ""), request.headers.get("X-Moderator-Fingerprint", ""))
        if session is None:
            raise HTTPException(status_code=401, detail={"code": "session_invalid"})
        # The Twitch access token never crosses the bridge (MOD-05 contract).
        return session
    raise HTTPException(status_code=404, detail={"code": "bridge_not_found"})


async def _db():
    from app.database import get_db
    return await get_db()
