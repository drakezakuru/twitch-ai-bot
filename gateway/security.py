"""Gateway security middleware helpers (MOD-06).

Exact origin validation, server-bound CSRF double-submit, host allowlist,
trusted-proxy handling and request bounds. Every check fails closed when the
corresponding deployment setting is configured but violated.
"""
from __future__ import annotations

import hmac
import os

MAX_BODY_BYTES = 256 * 1024
CSRF_COOKIE = "ms_csrf"
CSRF_HEADER = "X-Moderator-CSRF"


def env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def host_allowed(host_header: str | None, allowed: list[str]) -> bool:
    """Exact host match; no ports/percent-encoding games — normalised by equality."""
    if not allowed:
        return True  # deployment not configured: dev mode, no proxy in front
    if not host_header:
        return False
    return host_header in allowed


def origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    """Exact origin match for browser mutations; the string "null" is never valid."""
    if not allowed:
        return True  # deployment not configured: dev mode
    if not origin or origin == "null":
        return False
    return origin in allowed


def client_ip_from(xff: str | None, trusted_proxies: list[str], peer: str | None) -> str | None:
    """Honour X-Forwarded-For only when the direct peer is a trusted proxy.

    Without a trusted proxy list the forwarded header is attacker-controlled and
    is ignored entirely (spoofed-headers gate).
    """
    if not trusted_proxies:
        return peer
    if peer not in trusted_proxies or not xff:
        return peer
    parts = [part.strip() for part in xff.split(",")]
    for candidate in reversed(parts):
        if candidate not in trusted_proxies:
            return candidate
    return peer


def csrf_token_for(cookie_token: str) -> str:
    """Server-bound CSRF value: derived from the session cookie token itself."""
    key = os.environ.get(GATEWAY_TOKEN_ENV, "moderator-site")
    return hmac.new(key.encode(), cookie_token.encode(), "sha256").hexdigest()[:32]


def csrf_valid(cookie_token: str | None, header_value: str | None) -> bool:
    if not cookie_token or not header_value:
        return False
    return hmac.compare_digest(csrf_token_for(cookie_token), header_value)


GATEWAY_TOKEN_ENV = "MODERATOR_SITE_TOKEN"
