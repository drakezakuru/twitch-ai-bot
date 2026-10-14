import pytest
from app import channel_points_tts as cpt

pytestmark = pytest.mark.asyncio


async def test_channel_and_voice_round_trip(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT OR IGNORE INTO accounts(id,nickname,token) VALUES(55,'b','t')")
    await db.commit(); await db.close()
    saved = await cpt.save_config(55, {'enabled':1, 'channel':'#FreeChannel', 'voice':'voice-x'})
    loaded = await cpt.get_config(55)
    assert loaded['channel'] == 'freechannel' and loaded['voice'] == 'voice-x'


async def test_redemption_uses_configured_channel_and_voice(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT OR IGNORE INTO accounts(id,nickname,token) VALUES(56,'b','t')")
    await db.commit(); await db.close()
    await cpt.save_config(56, {'enabled':1, 'channel':'chosen', 'voice':'v2', 'cooldown_sec':0})
    got = {}
    async def fake(self, kind, account_id, channel, text, **kw): got.update(channel=channel, **kw)
    monkeypatch.setattr('app.audio_queue.AudioQueue.enqueue', fake)
    ok = await cpt.handle_redemption(56, 'event-channel', {'reward':{'title':'x'},'user_login':'u','user_input':'hello'})
    assert ok and got['channel'] == 'chosen' and got['voice_override'] == 'v2'
