"""Minimal OBS WebSocket v5 client for toggling a configured blur filter."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid

import websockets


def _authentication(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


async def set_filter_enabled(source_name: str, filter_name: str, enabled: bool) -> None:
    url = os.getenv("OBS_WEBSOCKET_URL", "ws://127.0.0.1:4455").strip()
    password = os.getenv("OBS_WEBSOCKET_PASSWORD", "")
    async with websockets.connect(url, open_timeout=3, close_timeout=2) as ws:
        hello = json.loads(await ws.recv())
        identify = {"rpcVersion": 1}
        auth = hello.get("d", {}).get("authentication")
        if auth:
            identify["authentication"] = _authentication(
                password, auth["salt"], auth["challenge"]
            )
        await ws.send(json.dumps({"op": 1, "d": identify}))
        identified = json.loads(await ws.recv())
        if identified.get("op") != 2:
            raise RuntimeError("OBS WebSocket authentication failed")
        request_id = uuid.uuid4().hex
        await ws.send(json.dumps({
            "op": 6,
            "d": {
                "requestType": "SetSourceFilterEnabled",
                "requestId": request_id,
                "requestData": {
                    "sourceName": source_name,
                    "filterName": filter_name,
                    "filterEnabled": enabled,
                },
            },
        }))
        response = json.loads(await ws.recv())
        status = response.get("d", {}).get("requestStatus", {})
        if response.get("op") != 7 or not status.get("result"):
            raise RuntimeError(status.get("comment") or "OBS rejected blur filter request")
