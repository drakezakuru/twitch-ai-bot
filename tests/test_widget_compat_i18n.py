"""Compatibility HTML only: no application startup, sockets or provider calls."""
import ast
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request

from app import widgets
from app.widget_inventory import (
    ALIAS_WIDGETS, LEGACY_PARAM_URLS, LEGACY_WIDGET_OUTPUTS,
    RETIRED_WIDGETS, RETIRED_WIDGET_TRANSLATIONS,
)

ROOT = Path(__file__).resolve().parents[1]


def isolated_route(name):
    # routes.py imports the application runtime; execute only the real HTML handler.
    tree = ast.parse((ROOT / 'app/routes.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    node.decorator_list = []
    namespace = {'json': json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app/routes.py', 'exec'), namespace)
    return namespace[name]


def compatibility_documents():
    env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape())
    documents = {route: widgets._retired_widget_html(route) for route in RETIRED_WIDGETS}
    documents['/obs-widget'] = asyncio.run(isolated_route('obs_widget')())
    for preview in (True, False):
        route = '/api/moderator-media/preview' if preview else '/widget/moderator-media'
        documents[route] = env.get_template('obs_moderator_media.html').render(preview=preview)
    for route, target in LEGACY_PARAM_URLS.items():
        documents[route] = widgets._top_donator_html(target.split('period=')[1], '').body.decode()
    documents['/obs/blur-guard'] = widgets._widget_html('blur-guard-v2')
    return documents


def test_compatibility_dom(tmp_path):
    fixture = tmp_path / 'compatibility.json'
    fixture.write_text(json.dumps(compatibility_documents(), ensure_ascii=False), encoding='utf-8')
    subprocess.run(
        ['node', '--test', 'tests/widget_compat_i18n.test.js'], cwd=ROOT, check=True, timeout=30,
        env={**os.environ, 'WIDGET_COMPAT_FIXTURES': str(fixture), 'PYTHON': sys.executable},
    )


@pytest.mark.parametrize('route', RETIRED_WIDGETS)
@pytest.mark.asyncio
async def test_retired_handlers_keep_url_reason_and_dark_fallback(route):
    endpoint = next(r.endpoint for r in widgets.public_router.routes if r.path == route)
    response = await endpoint()
    document = response.body.decode()
    assert response.status_code == 200
    assert document == widgets._retired_widget_html(route)
    assert '#0f0f1a' in document and 'color-scheme:dark' in document
    title, reason, _ = RETIRED_WIDGETS[route]
    assert title in document and reason in document
    assert document.index('/widget/_shared/i18n.js') < document.index('WidgetI18n.add(')
    for locale in ('en', 'ua'):
        assert all(RETIRED_WIDGET_TRANSLATIONS[locale][route])


def test_retired_missing_translation_and_script_safe_text(monkeypatch):
    route = '/widget/counter'
    monkeypatch.delitem(RETIRED_WIDGET_TRANSLATIONS['en'], route)
    document = widgets._retired_widget_html(route)
    labels = json.loads(document.split('WidgetI18n.add(', 1)[1].split(');</script>', 1)[0])
    assert 'retired.reason' not in labels['en']
    assert labels['ru']['retired.reason'] == RETIRED_WIDGETS[route][1]
    monkeypatch.setitem(RETIRED_WIDGETS, route, ('</script><img src=x>', '<b>reason</b>', '<replacement>'))
    document = widgets._retired_widget_html(route)
    assert '</script><img src=x>' not in document
    assert '\\u003c/script>' in document
    assert '&lt;replacement&gt;' in document


@pytest.mark.parametrize('route,target', LEGACY_PARAM_URLS.items())
@pytest.mark.asyncio
async def test_legacy_period_handlers_reuse_canonical_localization(route, target):
    endpoint = next(r.endpoint for r in widgets.public_router.routes if r.path == route)
    period = target.split('period=')[1]
    legacy = await endpoint(theme='glass')
    canonical = await widgets.widget_top_donator_page(period=period, theme='glass')
    assert legacy.status_code == 200
    assert legacy.body == canonical.body
    assert b'/widget/_shared/i18n.js' in legacy.body
    assert '__PERIOD__' not in legacy.body.decode()


@pytest.mark.parametrize('route,target', ALIAS_WIDGETS.items())
@pytest.mark.asyncio
async def test_blur_alias_reuses_localized_canonical_document(route, target):
    endpoint = next(r.endpoint for r in widgets.public_router.routes if r.path == route)
    replacement = next(r.endpoint for r in widgets.public_router.routes if r.path == target)
    response = await endpoint()
    assert response.status_code == 200
    assert response.body.decode() == await replacement()
    assert b'/widget/_shared/i18n.js' in response.body


@pytest.mark.parametrize('route', LEGACY_PARAM_URLS)
@pytest.mark.parametrize('locale,expected', [
    ('ru', 'Укажите канал Twitch'), ('en', 'Add a Twitch channel'),
    ('ua', 'Додайте Twitch-канал'), ('uk', 'Додайте Twitch-канал'),
    ('unknown', 'Укажите канал Twitch'),
])
@pytest.mark.asyncio
async def test_legacy_period_diagnostics_keep_locale_and_fail_closed(route, locale, expected):
    from app.widget_channel_scope import widget_channel_middleware

    request = Request({'type': 'http', 'method': 'GET', 'path': route,
                       'query_string': f'ui_lang={locale}&lang=en'.encode(),
                       'headers': [], 'server': ('test', 80), 'scheme': 'http'})

    async def unexpected(_):
        pytest.fail('A data URL without channel must not reach its handler')

    response = await widget_channel_middleware(request, unexpected)
    assert response.status_code == 200
    assert expected in response.body.decode()


@pytest.mark.asyncio
async def test_tts_speech_language_placeholder_is_not_ui_language(monkeypatch):
    async def design(widget, _overrides):
        return widgets._normalize_widget_design(widget, {})

    monkeypatch.setattr(widgets, '_resolve_widget_design', design)
    document = await isolated_route('obs_tts')(channel='demo', lang='en-US')
    assert '"en-US"' in document
    assert '__LANG__' not in document
    assert '/widget/_shared/i18n.js' in document


def test_serving_inventory_preserves_legacy_and_unserved_backups():
    assert set(LEGACY_WIDGET_OUTPUTS) == {'/obs-widget'}
    source = (ROOT / 'app/routes.py').read_text(encoding='utf-8')
    assert '@router.get("/obs-widget", response_class=HTMLResponse)' in source
    assert '@ws_router.get("/obs/tts", response_class=HTMLResponse)' in source
    assert '_widget_html("tts-raw")' in source
    routes = '\n'.join(p.read_text(encoding='utf-8') for p in (ROOT / 'app').glob('*.py'))
    # index_v10_backup.html удалён по DEC-CLEANUP-001; obs_tts_widget.html — единственный
    # оставшийся мёртвый, но неудалённый backup-шаблон.
    assert (ROOT / 'templates' / 'obs_tts_widget.html').is_file()
    assert 'obs_tts_widget.html' not in routes
    server = (ROOT / 'app/server.py').read_text(encoding='utf-8')
    assert 'StaticFiles(directory=str(static_dir))' in server
    assert 'StaticFiles(directory=str(_FRAMES_DIR))' in server
    media = (ROOT / 'app/moderator_media_routes.py').read_text(encoding='utf-8')
    assert 'prefix="/api/moderator-media"' in media
    assert '@admin_router.get("/preview", response_class=HTMLResponse)' in media
    assert '_valid_obs_token(account_id, channel, token)' in media
    # starlette 1.6: новый сигнатурный стиль TemplateResponse (request=, name=, context=)
    assert 'name="obs_moderator_media.html", context={"preview": False}' in media
