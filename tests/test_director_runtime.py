import time
import pytest
from app import director


@pytest.fixture(autouse=True)
def _fresh_source_health():
    """The health hub is a module singleton; other suites report the same channel name."""
    director.health = director.SourceHealthHub()
    yield
    director.health = director.SourceHealthHub()


async def _worker(channel="channel"):
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (1, 'lurker', 'x', 1, 'lurker')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, ?, 1)", (channel,))
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (2, 'director', 'x', 1, 'director')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (2, ?, 1)", (channel,))
        await db.commit()
    finally:
        await db.close()


def _healthy(channel="channel"):
    now = time.monotonic()
    for source in ("ai", "vision", "speech", "twitch"):
        director.health.report(channel, source, at=now)


@pytest.mark.asyncio
async def test_start_requires_all_live_sources_and_never_enables_send(tmp_db):
    from app.database import init_db
    await init_db(); await _worker(); await director.save_config("channel", {}, [1], 2)
    with pytest.raises(ValueError, match="sources_unhealthy"):
        await director.start("channel")
    _healthy()
    status = await director.start("channel")
    assert status["session"]["state"] == "warming"
    assert status["live_send_enabled"] is False
    assert status["workers"][0]["state"] == "scheduled"


@pytest.mark.asyncio
async def test_emergency_fence_cancels_jobs_and_blocks_resume_after_restart(tmp_db):
    from app.database import init_db, get_db
    await init_db(); await _worker(); await director.save_config("channel", {}, [1], 2); _healthy()
    status = await director.start("channel"); sid = status["session"]["id"]
    db = await get_db()
    try:
        await db.execute("INSERT INTO director_jobs(id, session_id, state, expires_at) VALUES ('job', ?, 'pending', 9999999999)", (sid,))
        await db.commit()
    finally: await db.close()
    status = await director.transition("channel", "emergency")
    assert status["session"]["state"] == "emergency"
    with pytest.raises(ValueError, match="emergency_requires_dry_run"):
        await director.transition("channel", "resume")
    await director.recover_after_restart()
    status = await director.get_status("channel")
    assert status["session"]["state"] == "paused"
    db = await get_db()
    try:
        assert (await (await db.execute("SELECT state FROM director_jobs WHERE id='job'")).fetchone())[0] == "cancelled"
    finally: await db.close()


@pytest.mark.asyncio
async def test_session_evidence_manifest_is_channel_scoped_and_requires_confirmation(tmp_db, tmp_path, monkeypatch):
    from app.database import init_db
    monkeypatch.setattr(director, "DATA_ROOT", tmp_path / "storage")
    await init_db(); await _worker(); await director.save_config("channel", {}, [1], 2); _healthy()
    session_id = (await director.start("channel"))["session"]["id"]
    await director.write_session_asset("channel", session_id, "transcript", "speech/session.json", b'{"session": 1}', metadata={"format": "json"})
    manifest = await director.session_storage_manifest("channel", session_id)
    assert manifest["total_size_bytes"] == 14
    assert manifest["audit_preserved"] is True
    with pytest.raises(ValueError, match="deletion_confirmation_required"):
        await director.delete_session_evidence("channel", session_id, "DELETE")
    result = await director.delete_session_evidence("channel", session_id, "УДАЛИТЬ")
    assert result["deleted_artifact_count"] == 1
    assert (await director.session_storage_manifest("channel", session_id))["artifacts"] == []
