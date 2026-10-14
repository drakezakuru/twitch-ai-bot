from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_output_selection_is_exact_scoped_and_legacy_is_unconfigured():
    from app.database import get_db, init_db
    from app.tts_output_routes import get_output, owner_set_output

    await init_db()
    db = await get_db()
    try:
        await db.executemany("INSERT INTO accounts(id,nickname,token) VALUES(?,?,'t')", [(1, 'one'), (2, 'two')])
        await db.executemany("INSERT INTO channels(account_id,channel_name) VALUES(?,?)", [(1, '#same'), (2, 'same')])
        await db.commit()
    finally:
        await db.close()

    assert not (await get_output(1, 'same'))['configured']
    saved = await owner_set_output(1, '#SAME', {'source': 'chat-reader'})
    assert saved['source'] == 'chat-reader' and saved['telemetry'] == 'unverified'
    assert not (await get_output(2, 'same'))['configured']


async def test_widgets_use_additive_exact_scoped_output_guard():
    from pathlib import Path

    core = Path('widgets/_shared/tts-core.js').read_text(encoding='utf-8')
    assert "if (!accountId || !channel) return Promise.resolve(true)" in core
    assert "state.source === source" in core
    for name in ('tts-bot', 'chat-reader', 'tts-raw'):
        html = Path(f'widgets/{name}/index.html').read_text(encoding='utf-8')
        assert f"TtsCore.outputAllowed('{name}')" in html


async def test_owner_output_test_reports_admission_not_playback(monkeypatch):
    from app import tts_output_routes as output

    async def fake_state(account_id, channel):
        return {"configured": True, "source": "tts-bot", "channel": "scope"}

    captured = []
    async def enqueue(self, *args, **kwargs):
        captured.append((args, kwargs))

    monkeypatch.setattr(output, "get_output", fake_state)
    monkeypatch.setattr("app.audio_queue.AudioQueue.enqueue", enqueue)
    result = await output.owner_test_output(1, "scope", {"text": "check"})
    assert result == {"ok": True, "source": "tts-bot", "status": "accepted", "telemetry": "unverified"}
    assert captured[0][0][3] == "check"
