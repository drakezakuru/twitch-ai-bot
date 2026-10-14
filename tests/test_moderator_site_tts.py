"""MOD-16 gate: voice policy, unicode bounds, provider failure, stop during synthesis."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_tts as tts


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "tts.db")
    await tts.ensure_schema(conn)
    yield conn
    await conn.close()


async def _ok_synth(text: str, voice: str) -> str:
    return f"audio:{voice}:{len(text)}"


@pytest.mark.asyncio
async def test_voice_policy_and_unicode_bounds(db):
    with pytest.raises(ValueError, match="voice_not_allowed"):
        await tts.submit(db, _ok_synth, channel="chan", text="привет", voice="morgan-freeman-ai")
    with pytest.raises(ValueError, match="tts_text_too_long"):
        await tts.submit(db, _ok_synth, channel="chan", text="ж" * (tts.MAX_TEXT_CHARS + 1), voice="alena")
    with pytest.raises(ValueError, match="tts_text_empty"):
        await tts.submit(db, _ok_synth, channel="chan", text="   ", voice="alena")
    # Emoji count as single code points; 500 are fine.
    ok = await tts.submit(db, _ok_synth, channel="chan", text="🎉" * 500, voice="alena")
    assert ok["status"] == "done"


@pytest.mark.asyncio
async def test_single_admission_not_double_quota(db):
    """This layer never re-checks queue quota — that belongs to cue admission."""
    import inspect
    source = inspect.getsource(tts.submit)
    assert "quota" not in source and "queue_full" not in source
    # Ten rapid submits succeed here: quota is the admission layer's concern.
    for i in range(10):
        result = await tts.submit(db, _ok_synth, channel="chan", text=f"текст {i}", voice="dmitri")
        assert result["status"] == "done"


@pytest.mark.asyncio
async def test_provider_fake_failure_marks_failed(db):
    async def broken_synth(text: str, voice: str) -> str:
        raise RuntimeError("provider down")
    result = await tts.submit(db, broken_synth, channel="chan", text="текст", voice="tanya")
    assert result["status"] == "failed"
    status = await tts.status(db, result["correlation_id"])
    assert status["status"] == "failed"
    # The queue survives: next submit works.
    ok = await tts.submit(db, _ok_synth, channel="chan", text="текст 2", voice="tanya")
    assert ok["status"] == "done"


@pytest.mark.asyncio
async def test_stop_during_synthesis_drops_late_result(db):
    async def slow_synth(text: str, voice: str) -> str:
        await tts_cancel_during_synthesis()
        return "late-audio"
    cancelled = {"flag": False}
    async def tts_cancel_during_synthesis():
        # Cancel arrives while the provider is still synthesizing.
        await db_execute_cancel()
        cancelled["flag"] = True
    async def db_execute_cancel():
        from app import moderator_site_tts as m
        # find the correlation: only one in flight
        row = await db.execute("SELECT correlation_id FROM ms_tts_commands WHERE status='synthesizing'")
        r = await row.fetchone()
        if r:
            await m.cancel(db, r[0])
    result = await tts.submit(db, slow_synth, channel="chan", text="долгий текст", voice="alena")
    assert result["status"] == "cancelled" and result.get("dropped") is True
    status = await tts.status(db, result["correlation_id"])
    assert status["status"] == "cancelled"  # late audio never reaches done
