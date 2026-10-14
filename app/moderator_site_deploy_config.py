"""MOD-22: deployment configuration — fail-closed validation, no owner port leak.

The config lives in the repository as TOML/JSON-like data; validation refuses to
boot the public gateway when TLS, public origin or allowed hosts are missing.
The owner panel port is never part of the published config. The invite link is
built from the configured moderator public origin, never from the panel's
location.origin.
"""
from __future__ import annotations

from typing import Any

REQUIRED_KEYS = {"public_origin", "allowed_hosts", "tls_cert", "tls_key", "gateway_port", "bridge_port"}
RESERVED_PORTS = {"gateway_port", "bridge_port"}


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed: every missing/invalid key raises; nothing falls back to defaults."""
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in config or config[key] in (None, "", []):
            errors.append(f"missing_or_empty:{key}")
    if errors:
        raise ValueError("config_invalid:" + ",".join(errors))
    if not str(config["public_origin"]).startswith("https://"):
        raise ValueError("config_invalid:public_origin_must_be_https")
    if not config["allowed_hosts"]:
        raise ValueError("config_invalid:allowed_hosts_empty")
    # Owner panel port must never appear as a published address.
    for key in RESERVED_PORTS:
        port = int(config[key])
        if not (0 < port < 65536):
            raise ValueError(f"config_invalid:{key}_out_of_range")
    published = config.get("published_ports", [])
    for entry in published:
        if int(entry) in {int(config["bridge_port"]), int(config.get("owner_panel_port", -1))}:
            raise ValueError("config_invalid:owner_port_published")
    return {"valid": True, "public_origin": config["public_origin"],
            "allowed_hosts": list(config["allowed_hosts"]),
            "published_ports": [int(p) for p in published]}


def invite_link(public_origin: str, invite_token: str) -> str:
    """Invite uses the configured moderator origin — never panel location.origin."""
    if not public_origin.startswith("https://"):
        raise ValueError("invite_requires_https_origin")
    return f"{public_origin.rstrip('/')}/moderator-site/join?invite={invite_token}"


def health_readiness(config: dict[str, Any], bridge_healthy: bool, gateway_listening: bool) -> dict[str, Any]:
    """Readiness is honest: any missing dependency means not ready, never fake-ok."""
    ready = bool(gateway_listening) and bool(bridge_healthy)
    return {"ready": ready, "gateway": bool(gateway_listening), "bridge": bool(bridge_healthy),
            "public_origin": config.get("public_origin") if ready else None}
