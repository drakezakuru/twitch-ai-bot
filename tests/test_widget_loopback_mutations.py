"""Public OBS hotkey mutations are available only to the local machine."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


async def _client(host: str) -> AsyncClient:
    from app.database import init_db
    from app.widgets import ensure_widgets_schema, public_router

    await init_db()
    await ensure_widgets_schema()
    app = FastAPI()
    app.include_router(public_router)
    return AsyncClient(
        transport=ASGITransport(app=app, client=(host, 12345)),
        base_url="http://panel",
    )


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/widgets/public/sub-goal/increment", {"delta": 3}),
        ("/api/widgets/counters/death/increment", {"delta": 3}),
        ("/api/widgets/counters/death/reset", None),
    ],
)
async def test_public_widget_mutations_reject_remote_clients(tmp_db, path, payload):
    async with await _client("203.0.113.8") as client:
        response = await client.post(
            path,
            json=payload,
            headers={"X-Forwarded-For": "127.0.0.1"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Loopback client required"


@pytest.mark.parametrize("host", ["127.0.0.1", "127.20.30.40", "::1"])
async def test_public_widget_mutations_allow_ip_loopback_range(tmp_db, host):
    async with await _client(host) as client:
        response = await client.post(
            "/api/widgets/counters/death/increment", json={"delta": 1}
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
