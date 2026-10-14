from __future__ import annotations

import json
import sys
import types

import pytest

from app.eventsub import EVENTSUB_WS_URL, EventSubClient


pytestmark = pytest.mark.asyncio


def _welcome(session_id: str) -> dict:
    return {"metadata": {"message_type": "session_welcome"}, "payload": {"session": {"id": session_id}}}


def _reconnect(url: str | None) -> dict:
    return {
        "metadata": {"message_type": "session_reconnect"},
        "payload": {"session": {"reconnect_url": url}},
    }


def _notification(message_id: str) -> dict:
    return {
        "metadata": {"message_type": "notification", "message_id": message_id},
        "payload": {
            "subscription": {"type": "channel.subscribe"},
            "event": {"broadcaster_user_login": "channel"},
        },
    }


class _FakeWebSocket:
    def __init__(self, messages: list[dict], on_exhausted=None) -> None:
        self.messages = messages
        self.on_exhausted = on_exhausted
        self.closed = False
        self._index = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    def __aiter__(self):
        return self._messages()

    async def close(self):
        self.closed = True

    async def _messages(self):
        while self._index < len(self.messages):
            message = self.messages[self._index]
            self._index += 1
            yield json.dumps(message)
        if self.on_exhausted:
            self.on_exhausted()


async def test_session_reconnect_uses_supplied_url_and_preserves_subscriptions(monkeypatch):
    reconnect_url = "wss://eventsub.twitch.tv/ws?session=migrated"
    callback_calls: list[str] = []
    subscription_sessions: list[str | None] = []

    async def callback(_account_id, _event_type, _channel, _event) -> None:
        callback_calls.append("called")

    client = EventSubClient(7, "fake", "fake", ["channel"], callback)

    async def subscribe_all() -> None:
        subscription_sessions.append(client.session_id)

    client._subscribe_all = subscribe_all  # type: ignore[method-assign]
    old_socket = _FakeWebSocket(
        [_welcome("original"), _reconnect(reconnect_url), _notification("delivered")]
    )
    new_socket = _FakeWebSocket(
        [_welcome("migrated"), _notification("delivered")], client._stop.set
    )
    sockets = [old_socket, new_socket]
    connected_urls: list[str] = []

    def connect(url: str, **_kwargs):
        connected_urls.append(url)
        return sockets.pop(0)

    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=connect))

    await client._run_loop()

    assert connected_urls == [EVENTSUB_WS_URL, reconnect_url]
    assert subscription_sessions == ["original"]
    assert client.session_id == "migrated"
    assert callback_calls == ["called"]
    assert old_socket.closed


async def test_session_reconnect_without_url_keeps_current_connection_alive():
    client = EventSubClient(7, "fake", "fake", ["channel"], lambda *_args: None)

    await client._handle_message(_reconnect(None))

    assert not client._stop.is_set()
    assert client._reconnect_url is None
    assert not client._awaiting_reconnect_welcome
