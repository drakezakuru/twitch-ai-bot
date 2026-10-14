import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


def test_profile_ui_has_no_global_scope_option():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    brain = (root / "templates" / "partials" / "brain.html").read_text()
    bots = (root / "templates" / "partials" / "bots.html").read_text()
    bot_js = (root / "static" / "app" / "03_bots.js").read_text()
    assert 'option value="" data-i18n="streamer.global_scope"' not in brain
    assert "streamer.attitude_global" not in bots
    assert "_sel('')" not in bot_js


async def test_profile_api_rejects_empty_channel(tmp_db, disable_auth):
    from app import database
    from app.routes import router
    from fastapi import FastAPI
    await database.init_db()
    app = FastAPI(); app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        assert (await c.get('/api/streamer-profile')).status_code == 400
        assert (await c.put('/api/streamer-profile', json={'bio': 'x'})).status_code == 400
        assert (await c.get('/api/accounts/1/streamer-profile')).status_code == 400


async def test_legacy_global_migrates_once_without_overwrite(tmp_db):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts(id,nickname,token) VALUES(41,'b','t')")
    await db.execute("INSERT INTO channels(account_id,channel_name,enabled) VALUES(41,'chan',1)")
    await db.execute("INSERT INTO streamer_profile(account_id,channel,bio) VALUES(41,'','legacy')")
    await db.commit(); await db.close()
    await database.init_db()
    db = await database.get_db()
    row = await (await db.execute("SELECT bio FROM streamer_profile WHERE account_id=41 AND channel='#chan'")).fetchone()
    assert row['bio'] == 'legacy'
    await db.execute("UPDATE streamer_profile SET bio='custom' WHERE account_id=41 AND channel='#chan'")
    await db.commit(); await db.close()
    await database.init_db()
    db = await database.get_db()
    row = await (await db.execute("SELECT bio FROM streamer_profile WHERE account_id=41 AND channel='#chan'")).fetchone()
    assert row['bio'] == 'custom'
    await db.close()
