"""Offline localization contract and producer tests, without loading the server/ML stack."""
import ast
import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import AsyncMock

import pytest

from app import mod_feed_routes as feed, stream_intents
from app.mod_feed_i18n import CAPTION_PARAMS, caption, sanitize_localization, stream_localization

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_feed(monkeypatch):
    for store in (feed._BUFFER, feed._DEDUP, feed._INTENTS, feed._INTENT_EXECUTORS, feed._LAST_VIOLATOR):
        store.clear()
    server = ModuleType('app.server')
    server.broadcast_log = AsyncMock()
    server.chat_analyzer = SimpleNamespace(_account_token={1: 'offline-token'})
    server.send_chat = AsyncMock(side_effect=AssertionError('No chat announcements'))
    monkeypatch.setitem(sys.modules, 'app.server', server)
    yield server
    server.send_chat.assert_not_called()
    for store in (feed._BUFFER, feed._DEDUP, feed._INTENTS, feed._INTENT_EXECUTORS, feed._LAST_VIOLATOR):
        store.clear()


def load_method(file, name):
    tree = ast.parse((ROOT / file).read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    namespace = {'logger': logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(ROOT / file), 'exec'), namespace)
    return namespace[name]


@pytest.mark.parametrize('metadata', [None, [], 'mod-feed.caption.applied', {'text': []}, {'text': {'key': []}},
    {'text': {'key': '__proto__'}}, {'text': {'key': 'mod-feed.caption.timeout', 'params': {'minutes': True}}},
    {'text': {'key': 'mod-feed.caption.timeout', 'params': {'minutes': 1e100}}},
    {'text': {'key': 'mod-feed.caption.moderation', 'params': {'category': {'secret': 'no'}}}},
    {'text': {'key': 'mod-feed.caption.moderation', 'params': {'category': 'x' * 201}}},
    {'text': {'key': 'mod-feed.caption.stream_enable', 'params': {'tool': 'constructor', 'result': 'done'}}}])
def test_invalid_metadata_preserves_legacy(metadata):
    event = feed.publish_event(1, 'ch', 'action', text='таймаут/блок применён', action='slow_on', localization=metadata)
    assert event['text'] == 'таймаут/блок применён'
    assert event['action'] == 'slow_on'
    assert 'localization' not in event


def test_sanitize_copies_only_whitelisted_data():
    raw = {'text': {'key': 'mod-feed.caption.moderation', 'params': {'category': '<b>{severity}</b>', 'token': 'secret'}, '_executor': object()}, 'status': 'ignored'}
    clean = sanitize_localization(raw)
    assert clean == {'text': caption('mod-feed.caption.moderation', category='<b>{severity}</b>')}
    raw['text']['params']['category'] = 'changed'
    assert clean['text']['params']['category'] == '<b>{severity}</b>'
    json.dumps(clean)


@pytest.mark.asyncio
async def test_metadata_roundtrip_http_list_poll_ws_and_dedup(isolated_feed):
    metadata = {'action': caption('mod-feed.caption.applied')}
    response = await feed.mod_feed_publish({'account_id': 1, 'channel': '#Ch', 'kind': 'violation', 'text': 'user text', 'action': 'таймаут/блок применён', 'localization': metadata})
    event = response['event']
    assert (await feed.mod_feed_list())['items'][0]['localization'] == metadata
    assert (await feed.mod_feed_poll())['events'][0]['localization'] == metadata
    await asyncio.sleep(0)
    payload = isolated_feed.broadcast_log.call_args.args[0]
    assert payload['localization'] == metadata and payload['text'] == 'user text'
    assert payload['type'] == 'mod_feed'
    assert feed.publish_event(1, 'ch', 'violation', localization={'action': caption('mod-feed.caption.rule')}) is None
    assert (await feed.mod_feed_poll(since=event['id']))['events'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('executed,confirm,masked', [(True, False, 'сработал словарь/правило'), (True, False, ''), (False, True, 'USER'), (False, False, 'USER')])
async def test_moderation_producer_keeps_content_and_never_sends_chat(executed, confirm, masked):
    method = load_method('app/chat_analyzer.py', '_modfeed_moderation')
    owner = SimpleNamespace(_account_role=AsyncMock(return_value=('moderator', {'confirm_mode': 'confirm' if confirm else 'auto', 'tts_announce': False})), _account_token={1: ''}, send_message=AsyncMock(side_effect=AssertionError('No chat')))
    verdict = SimpleNamespace(action='timeout', category='user category', severity=4, masked_text=masked, rule_name='rule')
    await method(owner, 1, 'ch', 'viewer', [verdict], executed=executed)
    first = feed._BUFFER[0]
    if executed or not confirm:
        assert first['text'] == (masked or 'сработал словарь/правило')
        assert ('text' in first['localization']) == (not bool(masked))
        assert first['localization']['action']['key'] == ('mod-feed.caption.applied' if executed else 'mod-feed.caption.decision_required')
    else:
        assert first['localization']['text'] == caption('mod-feed.caption.timeout_proposal', minutes=1, category='user category')
        assert first['status'] == 'pending'
    owner.send_message.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,result,status', [('suggest', {'ok': True}, 'pending'), ('auto', {'ok': True}, 'done'), ('auto', {'ok': False, 'error': 'PRIVATE'}, 'failed'), ('auto', {'ok': False, 'scope_error': True}, 'scope_failed')])
async def test_stream_producer_execution_and_caption_are_separate(monkeypatch, mode, result, status):
    monkeypatch.setattr(stream_intents, '_load_moderator', AsyncMock(return_value=({'nickname': 'mod'}, {'stream_tool_modes': {'title': mode}})))
    executor = AsyncMock(return_value=result)
    monkeypatch.setattr(stream_intents, '_make_executor', lambda *args: executor)
    monkeypatch.setattr(stream_intents, '_log_history', AsyncMock())
    title = 'название <b>{result}</b>'
    answer = await stream_intents.propose_stream_action(1, 'title', {'channel': 'ch', 'title': title})
    event = answer['event']
    assert title in event['text'] and event['action'] == 'title'
    assert event['localization']['text'] == caption('mod-feed.caption.stream_title', value=title, result=status)
    assert 'PRIVATE' not in json.dumps(event['localization'])
    assert executor.await_count == (1 if mode == 'auto' else 0)
    if mode == 'suggest':
        await feed.mod_feed_intent(str(event['id']), 'approve')
        executor.assert_awaited_once()
        assert (await feed.mod_feed_intent(str(event['id']), 'approve'))['ok'] is False


@pytest.mark.parametrize('tool', ['category', 'ai_category', 'title', 'slow', 'follower', 'emote_only', 'unique'])
def test_stream_metadata_supports_all_tools_without_mutating_parameters(tool):
    params = {'game_name': '<b>{result}</b>', 'title': '<b>{result}</b>', 'enabled': False}
    result = stream_localization(tool, params, 'done')
    assert sanitize_localization(result) == result
    assert result['action'] == caption(f'mod-feed.caption.tool.{tool}')
    assert params == {'game_name': '<b>{result}</b>', 'title': '<b>{result}</b>', 'enabled': False}
    if tool in ('category', 'ai_category', 'title'):
        assert result['text']['params']['value'] == '<b>{result}</b>'
    else:
        assert result['text']['key'] == 'mod-feed.caption.stream_disable'


def test_oversized_category_falls_back_instead_of_truncating_user_content():
    name = 'x' * 201
    localized = sanitize_localization(stream_localization('category', {'game_name': name}, 'done'))
    assert 'text' not in localized


@pytest.mark.asyncio
async def test_rejection_does_not_execute():
    execute = AsyncMock()
    event = feed.publish_event(1, 'ch', 'intent', intent={'_executor': execute}, localization={'text': caption('mod-feed.caption.rule')})
    result = await feed.mod_feed_intent(str(event['id']), 'reject')
    assert result['event']['status'] == 'rejected'
    execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('action,ok,key', [
    ('timeout_last', True, 'mod-feed.caption.hotkey_timeout'), ('timeout_last', False, 'mod-feed.caption.failed'),
    ('warn_last', True, 'mod-feed.caption.hotkey_warn'), ('clear', True, 'mod-feed.caption.hotkey_clear'),
    ('slow_on', True, 'mod-feed.caption.hotkey_applied'), ('slow_off', True, 'mod-feed.caption.hotkey_applied'),
    ('emote_on', True, 'mod-feed.caption.hotkey_applied'), ('emote_off', True, 'mod-feed.caption.hotkey_applied'),
    ('unique_on', True, 'mod-feed.caption.hotkey_applied'), ('unique_off', True, 'mod-feed.caption.hotkey_applied'),
])
async def test_hotkey_captions_do_not_change_execution(monkeypatch, action, ok, key):
    from app import database, twitch_helix
    row = {'id': 1, 'nickname': 'mod', 'bot_role': 'moderator', 'role_config_json': '{}'}
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(fetchone=AsyncMock(return_value=row))), close=AsyncMock())
    monkeypatch.setattr(database, 'get_db', AsyncMock(return_value=db))
    timeout = AsyncMock(return_value=(ok, '' if ok else 'PRIVATE'))
    settings = AsyncMock(return_value=(ok, ''))
    clear = AsyncMock(return_value=(ok, ''))
    monkeypatch.setattr(twitch_helix, 'timeout_user', timeout)
    monkeypatch.setattr(twitch_helix, 'update_chat_settings', settings)
    monkeypatch.setattr(twitch_helix, 'clear_chat_messages', clear)
    feed._LAST_VIOLATOR[(1, 'ch')] = {'user': 'viewer', 'text': 'USER'}
    result = await feed._moderator_action(1, 'ch', action)
    event = feed._BUFFER[-1]
    assert result['ok'] is ok
    assert event['localization']['text']['key'] == key
    assert 'PRIVATE' not in json.dumps(event['localization'])
    assert timeout.await_count == (1 if action == 'timeout_last' else 0)
    assert clear.await_count == (1 if action == 'clear' else 0)
    assert settings.await_count == (0 if action in ('timeout_last', 'warn_last', 'clear') else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('confidence', [0.1, 0.9])
async def test_voice_transcript_is_not_a_caption_and_execution_is_unchanged(confidence):
    import time
    method = load_method('app/voice_control.py', 'handle_stream_transcript')
    config = {'enabled': True, 'account_id': 1, 'channel': 'ch', 'activation_phrase': 'bot',
              'confidence_threshold': .65, 'sample_path': '/offline/sample.wav', 'profile_ready': True}
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(fetchone=AsyncMock(return_value={'profile_json': '{"version":2}'}))), close=AsyncMock())
    execute = AsyncMock(return_value={'ok': True})
    method.__globals__.update(get_config=AsyncMock(return_value=config), get_db=AsyncMock(return_value=db),
        parse_voice_intent=lambda *args: {'widget': 'countdown', 'action': 'start'},
        json=json, Path=Path, time=time, _read_pcm16_mono=lambda path: ([], 16000, 2),
        verify_owner_voice=AsyncMock(return_value=confidence), execute_reversible_binding=execute)
    transcript = 'Таймаут/блок применён <b>{result}</b>'
    result = await method(1, 'ch', transcript, '/offline/test.wav')
    if confidence < .65:
        assert result['status'] == 'suggested'
        event = feed._BUFFER[-1]
        assert event['text'] == transcript and event['action'] == 'countdown:start'
        assert event['localization'] == {'action': caption('mod-feed.caption.voice.countdown.start')}
        execute.assert_not_called()
        await feed.mod_feed_intent(str(event['id']), 'approve')
        execute.assert_awaited_once()
    else:
        assert result['status'] == 'executed'
        execute.assert_awaited_once()
        assert not feed._BUFFER


def test_moderator_caption_node_behavior():
    import subprocess
    subprocess.run(["node", "--test", "tests/mod_feed_i18n.test.js"], cwd=ROOT, check=True, timeout=30)


def test_all_contract_keys_have_ru_en_ua_and_matching_consumers():
    panel = (ROOT / 'static/app/24_dynamic_i18n.js').read_text()
    widget = (ROOT / 'widgets/mod-feed/index.html').read_text()
    start = 'const MOD_FEED_CAPTIONS = {'
    panel_dictionary = panel.split(start, 1)[1].split('\n};', 1)[0]
    assert widget.split(start, 1)[1].split('\n};', 1)[0] == panel_dictionary
    for key in CAPTION_PARAMS:
        assert f"'{key}': [" in panel_dictionary
