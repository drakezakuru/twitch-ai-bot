"""MOD-18 gate: restart after Stop, single-output failure isolation, neighbouring channel safe."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_controls as controls
from app import moderator_site_cues as cues
from app import moderator_site_sound as sound
from app import moderator_site_tts as tts


class _Spy:
    def __init__(self): self.calls = []
    async def __call__(self, channel, kind, meta): self.calls.append((channel, kind, meta))


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "controls.db")
    await controls.ensure_schema(conn)
    await tts.ensure_schema(conn)
    await sound.ensure_schema(conn)
    from app import moderator_site_schema as ms
    await ms.ensure_schema(conn)
    yield conn
    await conn.close()


async def _ok_synth(text: str, voice: str) -> str:
    return "audio"


@pytest.mark.asyncio
async def test_restart_after_stop_keeps_kill_active(db, tmp_path):
    """Simulated restart: a fresh connection to the same DB still sees the kill."""
    await controls.activate_kill(db, by="owner", reason="incidents")
    import aiosqlite
    fresh = await aiosqlite.connect(tmp_path / "controls.db")  # «после рестарта»
    try:
        assert await controls.kill_active(fresh) is True
        with pytest.raises(ValueError, match="kill_switch_active"):
            await controls.check_admission(fresh)
    finally:
        await fresh.close()


@pytest.mark.asyncio
async def test_persistent_kill_blocks_admission_until_deactivated(db):
    await controls.activate_kill(db, by="owner", reason="pause")
    with pytest.raises(ValueError, match="kill_switch_active"):
        await controls.check_admission(db)
    await controls.deactivate_kill(db)
    await controls.check_admission(db)  # admission resumes
    assert not await controls.kill_active(db)


@pytest.mark.asyncio
async def test_failure_of_one_output_does_not_stop_neighbours(db):
    spy = _Spy()
    await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1", correlation_id="c1")
    # sound lane stop fails (dispatch raises) — must not touch tts lane
    async def broken_dispatch(channel, kind, meta):
        raise RuntimeError("renderer down")
    await sound.play(db, spy, account_id=1, channel="chan2", sound_id="s1", correlation_id="c2")
    with pytest.raises(RuntimeError, match="renderer down"):
        await sound.stop_scope(db, broken_dispatch, "chan")
    # соседний канал жив: его команды всё ещё dispatched
    status = await sound.safe_status(db, "c2")
    assert status["status"] == "dispatched"


@pytest.mark.asyncio
async def test_stop_lane_neighbouring_channel_not_stopped(db):
    spy = _Spy()
    await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1", correlation_id="c1")
    await sound.play(db, spy, account_id=1, channel="other", sound_id="s1", correlation_id="c2")
    result = await controls.stop_lane(db, spy, channel="chan", lane="sound")
    assert result["stopped"] == 1 and result["generation"] == 1
    assert (await sound.safe_status(db, "c1"))["status"] == "stopped"
    assert (await sound.safe_status(db, "c2"))["status"] == "dispatched"  # соседний канал не задет
    await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1", correlation_id="c3")
    gen = await controls.scope_generation(db, "sound:chan")
    assert gen == 1  # не бампнулся от новой игры


@pytest.mark.asyncio
async def test_stop_lane_bumps_generation_and_cancels_synth(db):
    spy = _Spy()
    await tts.submit(db, _ok_synth, channel="chan", text="текст", voice="alena", correlation_id="t1")
    result = await controls.stop_lane(db, spy, channel="chan", lane="tts")
    assert result["generation"] == 1
    assert await controls.scope_generation(db, "tts:chan") == 1
    again = await controls.stop_lane(db, spy, channel="chan", lane="tts")
    assert again["generation"] == 2  # каждый stop бампает generation скоупа
