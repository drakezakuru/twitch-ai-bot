import pytest
from httpx import ASGITransport, AsyncClient

from app.widget_bindings import ALLOWED_ACTIONS, validate_widget_action


def test_all_allowed_pairs_and_rejections():
    for widget, actions in ALLOWED_ACTIONS.items():
        for action in actions:
            assert validate_widget_action(widget, action) is None
    assert validate_widget_action('goals', 'start') == 'incompatible_widget_action'
    assert validate_widget_action('missing', 'reset') == 'unknown_widget'
    assert validate_widget_action('goals', 'missing') == 'unknown_action'
    assert validate_widget_action('soundboard', 'play_track') == 'unknown_action'
    assert validate_widget_action('soundboard', 'play_track:0') == 'unknown_action'


@pytest.mark.asyncio
async def test_binding_api_returns_stable_400(tmp_db, disable_auth):
    from app import database
    from app.widgets import admin_router
    from fastapi import FastAPI
    await database.init_db()
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'binding_test', 'fake')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (1, 'chan', 1)"
        )
        await db.commit()
    finally:
        await db.close()
    app = FastAPI(); app.include_router(admin_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        contract = (await c.get('/api/widgets/binding-contract')).json()
        # Q27a: контракт v2 — осмысленные действия для остальных виджетов.
        assert contract['version'] == 2
        assert 'counter' not in contract['widgets']
        assert contract['sources']['chat_command']['roles'] == ['mod', 'streamer']
        assert contract['sources']['eventsub']['roles'] == ['any']
        assert contract['sources']['hotkey']['roles'] == ['streamer']
        assert contract['widgets']['goals']['key']['type'] == 'positive_integer'
        assert contract['widgets']['now_playing']['actions']['set']['value'] == {
            'type': 'string', 'required': True,
        }
        good = await c.post('/api/widgets/bindings', json={
            'account_id': 1, 'channel': 'chan',
            'source': 'chat_command', 'match': '!goal', 'widget': 'goals',
            'widget_key': '1', 'action': 'add_percent',
        })
        assert good.status_code == 200 and good.json()['ok']
        bad = await c.post('/api/widgets/bindings', json={'account_id':1,'channel':'chan','source':'chat_command','match':'!goal','widget':'goals','action':'start'})
        assert bad.status_code == 400 and bad.json()['detail'] == 'incompatible_widget_action'
        unknown = await c.post('/api/widgets/bindings', json={'account_id':1,'channel':'chan','source':'chat_command','match':'!x','widget':'x','action':'reset'})
        assert unknown.status_code == 400 and unknown.json()['detail'] == 'unknown_widget'
