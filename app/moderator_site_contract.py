"""Moderator-site contract inventory (MOD-01): default-deny remote surface guard.

The future moderator gateway may only expose routes that are EXPLICITLY listed in
REMOTE_ROUTE_ALLOWLIST and live under the /moderator-site prefix. Everything else in
the owner application is remote-forbidden by default — the test suite enforces it.
"""
from __future__ import annotations

from fastapi import FastAPI

REMOTE_SITE_PREFIX = "/moderator-site"

# Explicit allowlist of remote surfaces the gateway may proxy. Default-deny: empty
# until MOD-03 adds explicit gateway methods/paths, one entry per decision.
REMOTE_ROUTE_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()

# Surface categories that are NEVER remotely proxied, whatever future decisions say
# (owner credentials, tokens, backups, owner control plane, raw media).
FORBIDDEN_REMOTE_PREFIXES: tuple[str, ...] = (
    "/api/accounts",          # bot OAuth tokens
    "/api/twitch-oauth",      # OAuth exchange
    "/api/token-status",
    "/api/backup",            # owner backups
    "/api/import",
    "/api/custom-providers",  # provider API keys
    "/api/security",
    "/api/maintenance",
    "/api/director",          # owner control plane
    "/api/voice-clone",
    "/api/voice-clones",
    "/frames",                # raw stream frames
    "/ws",                    # owner websocket
)


def build_app_route_manifest(app: FastAPI) -> frozenset[tuple[str, str]]:
    """(METHOD, path) pairs of every HTTP route currently registered in the app."""
    manifest: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        methods = getattr(route, "methods", None) or {"GET"}
        for method in methods:
            manifest.add((str(method).upper(), path))
    return frozenset(manifest)


def check_default_deny(app: FastAPI) -> list[str]:
    """Return contract violations; an empty list means default-deny holds."""
    violations: list[str] = []
    for method, path in sorted(REMOTE_ROUTE_ALLOWLIST):
        if not path.startswith(REMOTE_SITE_PREFIX):
            violations.append(f"allowlist entry outside {REMOTE_SITE_PREFIX}: {method} {path}")
        if any(path.startswith(prefix) for prefix in FORBIDDEN_REMOTE_PREFIXES):
            violations.append(f"allowlist entry in forbidden surface: {method} {path}")
        if (method, path) in build_app_route_manifest(app):
            violations.append(f"allowlist entry proxies an existing owner route: {method} {path}")
    return violations
