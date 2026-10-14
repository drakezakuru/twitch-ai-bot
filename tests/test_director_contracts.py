from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import director, director_routes
from app.database import get_db, init_db


@pytest_asyncio.fixture
async def client(disable_auth, tmp_db):
    await init_db()
    app = FastAPI()
    app.include_router(director_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _active_session(channel: str, session_id: str) -> None:
    db = await get_db()
    try:
        await director.ensure_schema(db)
        await db.execute(
            "INSERT INTO director_sessions(id, channel, state, config_version) VALUES (?, ?, 'live', 1)",
            (session_id, channel),
        )
        await db.execute(
            "INSERT INTO director_jobs(id, session_id, state, expires_at) VALUES (?, ?, 'pending', 9999999999)",
            (f"job-{session_id}", session_id),
        )
        await db.execute(
            "INSERT INTO director_messages(id, plan_id, session_id, account_id, text, due_at, expires_at) VALUES (?, 'plan', ?, 1, 'safe', 0, 9999999999)",
            (f"message-{session_id}", session_id),
        )
        await db.commit()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_global_emergency_route_fences_every_active_channel_and_audits(client):
    await _active_session("first", "first-session")
    await _active_session("second", "second-session")

    response = await client.post("/api/director/emergency")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "channels": ["first", "second"], "stopped_count": 2}

    for channel, session_id in (("first", "first-session"), ("second", "second-session")):
        status = await client.get(f"/api/director/{channel}/status")
        assert status.status_code == 200
        assert status.json()["session"]["state"] == "emergency"
        assert status.json()["session"]["emergency_fence"] is True
        audit = await client.get(f"/api/director/{channel}/audit")
        assert audit.status_code == 200
        assert audit.json()["entries"][0]["action"] == "emergency"
        assert audit.json()["entries"][0]["details"] == {"scope": "all_active_channels"}

    db = await get_db()
    try:
        for session_id in ("first-session", "second-session"):
            job = await (await db.execute("SELECT state FROM director_jobs WHERE session_id=?", (session_id,))).fetchone()
            message = await (await db.execute("SELECT state FROM director_messages WHERE session_id=?", (session_id,))).fetchone()
            assert job[0] == "cancelled"
            assert message[0] == "cancelled"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_lifecycle_rejects_invalid_transitions(tmp_db):
    await _active_session("channel", "session")
    with pytest.raises(ValueError, match="invalid_lifecycle_transition"):
        await director.transition("channel", "resume")
    await director.transition("channel", "pause")
    with pytest.raises(ValueError, match="invalid_lifecycle_transition"):
        await director.transition("channel", "pause")


def test_director_frontend_uses_route_and_response_contracts():
    root = Path(__file__).parents[1]
    script = (root / "static/app/20_director.js").read_text()
    # Q40: у Режиссёра снова своя страница (паршал director.html), вкладка на каждый канал.
    markup = (root / "templates/partials/director.html").read_text()
    shell = (root / "templates/base.html").read_text()
    bots = (root / "templates/partials/bots.html").read_text()
    assert "{% include 'partials/director.html' %}" in shell
    assert 'id="section-director"' in markup and 'id="directorChannelTabs"' in markup
    assert 'id="directorBotPanel"' not in bots and "directorEmergencyStop()" not in bots

    assert "api('/api/director/emergency', jopts('POST', {}))" in script
    assert markup.count("directorEmergencyStop()") == 1
    assert "directorEmergencyStop()" not in shell
    assert "overview.channels?.[0]" not in script
    assert "const status = worker.state || 'unknown';" in script
    # Q29: AI теперь трёхсостоянийный — sources только для остальных источников
    assert "const sources = ['vision', 'speech', 'twitch'];" in script
    assert "state.ai_state" in script
    assert script.count("'director.source_twitch': 'Twitch'") == 3
    for field in (
        "directorLanguage", "directorReactionMode", "directorVisionStale", "directorSpeechStale",
        "directorOfflineGrace", "directorRangeSmallMin", "directorRangeMediumMin", "directorRangeLargeMin",
    ):
        assert field in markup
        assert field in script
    for language in ("LANGS.ru", "LANGS.en", "LANGS.ua"):
        assert f"Object.assign({language}, {{\n    'director.reaction_ranges'" in script
