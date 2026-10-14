"""HTTP client from the moderator gateway to the panel bridge (MOD-03).

Service credentials: the bridge token travels only on the loopback hop. The client
speaks to one fixed base URL and never rewrites paths — the registry decides them.
"""
from __future__ import annotations

import os

import httpx

BRIDGE_BASE_URL_ENV = "MODERATOR_BRIDGE_BASE_URL"
BRIDGE_TOKEN_ENV = "MODERATOR_BRIDGE_TOKEN"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8201"


class BridgeClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 5.0):
        self._base_url = (base_url or os.environ.get(BRIDGE_BASE_URL_ENV, DEFAULT_BRIDGE_URL)).rstrip("/")
        self._token = token or os.environ.get(BRIDGE_TOKEN_ENV, "")
        self._timeout = timeout

    async def request(self, method: str, bridge_path: str) -> httpx.Response:
        # Fail-closed: without a configured credential nothing leaves the gateway.
        if not self._token:
            raise RuntimeError("bridge_token_missing")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.request(
                method,
                f"{self._base_url}{bridge_path}",
                headers={"X-Moderator-Bridge-Token": self._token},
            )
