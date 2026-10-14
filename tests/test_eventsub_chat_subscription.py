from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.eventsub import EventSubClient


pytestmark = pytest.mark.asyncio


class _Response:
    status_code = 202
    text = ""


class _HttpClient:
    def __init__(self, posts: list[dict], **_kwargs) -> None:
        self.posts = posts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, _url: str, **kwargs):
        self.posts.append(kwargs["json"])
        return _Response()


async def test_chat_subscription_includes_broadcaster_and_bot_user_ids(monkeypatch):
    posts: list[dict] = []
    monkeypatch.setattr("app.eventsub._chat_messages_enabled", lambda _account_id: _async_value(True))
    monkeypatch.setattr(
        "app.eventsub.get_user_id",
        lambda login, _token: _async_value("bot-id" if login == "qa_bot" else "channel-id"),
    )
    monkeypatch.setattr("app.eventsub.twitch_credentials.get_client_id", lambda: "client-id")
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: _HttpClient(posts, **kwargs))

    client = EventSubClient(7, "qa_bot", "fake", ["qa_channel"], lambda *_args: None)
    client.session_id = "session-id"
    await client._subscribe_all()

    chat = next(post for post in posts if post["type"] == "channel.chat.message")
    assert chat["condition"] == {
        "broadcaster_user_id": "channel-id",
        "user_id": "bot-id",
    }


async def test_missing_bot_user_id_skips_subscriptions_that_require_it(monkeypatch):
    posts: list[dict] = []
    monkeypatch.setattr("app.eventsub._chat_messages_enabled", lambda _account_id: _async_value(True))
    monkeypatch.setattr(
        "app.eventsub.get_user_id",
        lambda login, _token: _async_value(None if login == "qa_bot" else "channel-id"),
    )
    monkeypatch.setattr("app.eventsub.twitch_credentials.get_client_id", lambda: "client-id")
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: _HttpClient(posts, **kwargs))

    client = EventSubClient(7, "qa_bot", "fake", ["qa_channel"], lambda *_args: None)
    client.session_id = "session-id"
    await client._subscribe_all()

    posted_types = {post["type"] for post in posts}
    assert "channel.chat.message" not in posted_types
    assert "channel.follow" not in posted_types


async def _async_value(value):
    return value


class _EventSubManager:
    def __init__(self) -> None:
        self.stopped: list[int] = []
        self.started: list[tuple] = []

    async def stop_for_account(self, account_id: int) -> bool:
        self.stopped.append(account_id)
        return True

    async def start_for_account(self, *args) -> bool:
        self.started.append(args)
        return True


class _BotManager:
    def get_status(self, _account_id: int) -> dict:
        return {"connected": True}


async def test_disabling_chat_restarts_enabled_eventsub_without_chat(tmp_db, monkeypatch):
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, enabled, eventsub_enabled, eventsub_chat_messages) "
            "VALUES (7, 'qa_bot', 'fake-token', 1, 1, 1)"
        )
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (7, 'qa_channel', 1)"
        )
        await db.commit()
    finally:
        await db.close()

    eventsub_manager = _EventSubManager()
    monkeypatch.setitem(
        sys.modules,
        "app.server",
        SimpleNamespace(eventsub_manager=eventsub_manager, bot_manager=_BotManager()),
    )
    monkeypatch.setattr("app.routes_modpanel.decrypt_token", lambda value: value)

    from app.routes_modpanel import moderation_eventsub_chat_toggle

    result = await moderation_eventsub_chat_toggle(7, {"enabled": False})

    assert result == {"ok": True, "enabled": False}
    assert eventsub_manager.stopped == [7]
    assert eventsub_manager.started == [(7, "qa_bot", "fake-token", ["qa_channel"])]

    db = await get_db()
    try:
        row = await (
            await db.execute("SELECT eventsub_chat_messages FROM accounts WHERE id = 7")
        ).fetchone()
        assert row["eventsub_chat_messages"] == 0
    finally:
        await db.close()


async def test_chat_toggle_does_not_start_disabled_eventsub(tmp_db, monkeypatch):
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, enabled, eventsub_enabled) "
            "VALUES (8, 'qa_bot', 'fake-token', 1, 0)"
        )
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (8, 'qa_channel', 1)"
        )
        await db.commit()
    finally:
        await db.close()

    eventsub_manager = _EventSubManager()
    monkeypatch.setitem(
        sys.modules,
        "app.server",
        SimpleNamespace(eventsub_manager=eventsub_manager, bot_manager=_BotManager()),
    )

    from app.routes_modpanel import moderation_eventsub_chat_toggle

    result = await moderation_eventsub_chat_toggle(8, {"enabled": True})

    assert result == {"ok": True, "enabled": True}
    assert eventsub_manager.stopped == []
    assert eventsub_manager.started == []
