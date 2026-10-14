"""Explicit remote surface registry for the moderator gateway (MOD-03).

Default-deny: only (method, gateway_path, bridge_path) entries listed here are
proxied. There is no prefix forwarding and no catch-all; every new remote surface
must be added here deliberately and reviewed against FORBIDDEN_REMOTE_PREFIXES.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.moderator_site_contract import FORBIDDEN_REMOTE_PREFIXES


@dataclass(frozen=True)
class GatewayRoute:
    method: str
    gateway_path: str
    bridge_path: str


GATEWAY_ROUTES: frozenset[GatewayRoute] = frozenset({
    GatewayRoute("GET", "/moderator-site/health", "/bridge/health"),
    GatewayRoute("POST", "/moderator-site/identity/login-attempt", "/bridge/identity/login-attempt"),
    GatewayRoute("POST", "/moderator-site/identity/exchange", "/bridge/identity/exchange"),
    GatewayRoute("POST", "/moderator-site/identity/logout", "/bridge/identity/logout"),
    GatewayRoute("GET", "/moderator-site/identity/session", "/bridge/identity/session"),
})

# Gateway mutations and session reads require a moderator cookie session; health stays open.
UNAUTHENTICATED_PATHS: frozenset[str] = frozenset({
    "/moderator-site/health",
    "/moderator-site/identity/login-attempt",
    "/moderator-site/identity/exchange",
})


def validate_registry() -> list[str]:
    """Contract checks for the explicit registry; empty list = valid."""
    violations: list[str] = []
    for route in GATEWAY_ROUTES:
        if not route.gateway_path.startswith("/moderator-site/"):
            violations.append(f"gateway path outside /moderator-site: {route.gateway_path}")
        if any(route.gateway_path.startswith(prefix + "/") for prefix in FORBIDDEN_REMOTE_PREFIXES):
            violations.append(f"gateway path in forbidden surface: {route.gateway_path}")
        if (route.method, route.gateway_path) in {
            (m, p) for m, p in _owner_manifest()
        }:
            violations.append(f"gateway path collides with an owner route: {route.gateway_path}")
    return violations


def resolve(gateway_path: str) -> GatewayRoute | None:
    for route in GATEWAY_ROUTES:
        if route.gateway_path == gateway_path:
            return route
    return None


def _owner_manifest() -> list[tuple[str, str]]:
    # Lazy import: keeps the gateway process free of app.server at module load; this
    # helper runs only in offline contract tests.
    import app.server
    from app.moderator_site_contract import build_app_route_manifest

    return sorted(build_app_route_manifest(app.server.app))
