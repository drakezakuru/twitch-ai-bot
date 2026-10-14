"""Offline UI-locale contract, without OBS/browser or provider access."""
from pathlib import Path
import subprocess

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]


def test_widget_locale_runtime():
    subprocess.run(["node", "--test", "tests/widget_i18n.test.js", "tests/widget_state_i18n.test.js",
                    "tests/widget_event_i18n.test.js"], cwd=ROOT, check=True, timeout=30)


def test_shared_locale_precedes_every_active_widget_script():
    from app.widget_inventory import WIDGET_INVENTORY
    from app.widgets import _widget_html

    for widget in WIDGET_INVENTORY:
        source = _widget_html(widget.folder)
        assert source.index('/widget/_shared/i18n.js') < source.index('</head>'), widget.slug
        assert source.index('/widget/_shared/i18n.js') < source.index('</script>'), widget.slug


@pytest.mark.parametrize('route', ['/widget/goals', '/widget/now-playing', '/widget/schedule'])
@pytest.mark.asyncio
async def test_default_titles_are_client_localized_but_saved_titles_remain_content(disable_auth, monkeypatch, route):
    from app import widgets
    from app.server import app

    async def no_title(_):
        return ''

    async def saved_title(_):
        return 'Сейчас <img src=x onerror=alert(1)>'

    monkeypatch.setattr(widgets, '_get_widget_title', no_title)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        empty = await client.get(route, params={'preview': '1', 'ui_lang': 'en'})
        title_id = 'labelText' if route == '/widget/now-playing' else 'title'
        assert f'id="{title_id}"></' in empty.text
        monkeypatch.setattr(widgets, '_get_widget_title', saved_title)
        saved = await client.get(route, params={'preview': '1', 'ui_lang': 'en'})
        assert 'Сейчас &lt;img src=x onerror=alert(1)&gt;' in saved.text
        override = await client.get(route, params={'preview': '1', 'ui_lang': 'ua', 'title': 'My title'})
        assert '>My title</' in override.text
        assert 'Сейчас &lt;img' not in override.text


@pytest.mark.asyncio
async def test_diagnostic_ui_locale_is_separate_from_tts_voice_language(disable_auth):
    from app.database import init_db
    from app.server import app

    await init_db()

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        english = await client.get('/obs/tts?ui_lang=en&lang=ru-RU')
        ukrainian = await client.get('/widget/goals?ui_lang=ua&lang=en')
        fallback = await client.get('/obs/tts?lang=en-US')
        preview = await client.get('/obs/tts?preview=1&ui_lang=ua&lang=en-US')
        asset = await client.get('/widget/_shared/i18n.js')
    assert 'Add a Twitch channel' in english.text
    assert "lang='uk'" in ukrainian.text and 'Додайте Twitch-канал' in ukrainian.text
    assert 'Укажите канал Twitch' in fallback.text
    assert '"en-US"' in preview.text
    assert '/widget/_shared/i18n.js' in preview.text
    assert asset.status_code == 200 and 'window.WidgetI18n' in asset.text


def test_diagnostic_missing_translation_falls_back_to_russian(monkeypatch):
    from app import widget_channel_scope as scope

    monkeypatch.delitem(scope._MESSAGES['en'], 'missing')
    assert 'Укажите канал Twitch' in scope.diagnostic_html('missing', lang='en')
    assert 'Widget is not connected' in scope.diagnostic_html('unknown-code', lang='en') or 'Виджет не подключён' in scope.diagnostic_html('unknown-code', lang='en')
