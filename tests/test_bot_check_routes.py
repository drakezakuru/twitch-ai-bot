from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import bot_check_routes
from app.database import get_db, init_db


@pytest_asyncio.fixture
async def client(disable_auth, tmp_db):
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token) VALUES (1, 'alpha', 'secret')")
        await db.commit()
    finally:
        await db.close()
    bot_check_routes._jobs.clear()
    app = FastAPI()
    app.include_router(bot_check_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await bot_check_routes.cancel_active_checks()
    bot_check_routes._jobs.clear()


@pytest.mark.asyncio
async def test_job_completes_with_safe_report_and_summary_audit(client, monkeypatch):
    async def fake_run(accounts, channel, message_template, **kwargs):
        assert [item["id"] for item in accounts] == [1, 99]
        assert channel == "qa_channel"
        assert kwargs["read_timeout"] == 30
        return [
            {"account_id": 1, "nickname": "alpha", "channel": channel, "result": "success", "reason": "ok"},
            {"account_id": 99, "nickname": "", "channel": channel, "result": "error", "reason": "bot_not_found"},
        ]

    monkeypatch.setattr(bot_check_routes, "run_bot_check", fake_run)
    response = await client.post("/api/bot-checks", json={
        "account_ids": [1, 99], "channel": "#QA_Channel",
        "message_template": "test [ник]", "read_timeout": 1,
    })
    payload = response.json()
    assert payload["status"] == "running"
    for _ in range(20):
        status = (await client.get(f"/api/bot-checks/{payload['check_id']}")).json()
        if status["status"] != "running":
            break
        await asyncio.sleep(0)
    assert status["status"] == "completed"
    assert status["counts"] == {"success": 1, "not_confirmed": 0, "error": 1}
    assert "secret" not in str(status)

    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT detail FROM action_log WHERE action = 'bot_check' ORDER BY id DESC LIMIT 1"
        )).fetchone()
    finally:
        await db.close()
    assert "channel=qa_channel" in row["detail"]
    assert "bot_not_found" not in row["detail"]


@pytest.mark.asyncio
async def test_validation_and_cancel(client, monkeypatch):
    invalid_ids = await client.post("/api/bot-checks", json={"account_ids": [], "channel": "ok"})
    invalid_channel = await client.post(
        "/api/bot-checks", json={"account_ids": [1], "channel": "bad channel"},
    )
    assert invalid_ids.json()["code"] == "invalid_account_ids"
    assert invalid_channel.json()["code"] == "invalid_channel"

    started = asyncio.Event()

    async def waiting_run(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(bot_check_routes, "run_bot_check", waiting_run)
    job = (await client.post(
        "/api/bot-checks", json={"account_ids": [1], "channel": "ok"},
    )).json()
    await started.wait()
    cancelled = (await client.post(f"/api/bot-checks/{job['check_id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"

