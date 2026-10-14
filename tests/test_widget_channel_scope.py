from __future__ import annotations

from httpx import ASGITransport, AsyncClient
import pytest


pytestmark = pytest.mark.asyncio


async def _seed_channels() -> None:
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts(id,nickname,token,enabled) VALUES(?,?,?,?)",
            [(1, "bot1", "token", 1), (2, "bot2", "token", 1), (3, "offbot", "token", 1)],
        )
        await db.executemany(
            "INSERT INTO channels(account_id,channel_name,enabled,twitch_channel_id,twitch_channel_login) "
            "VALUES(?,?,?,?,?)",
            [
                (1, "alpha", 1, "100", "alpha"),
                (2, "alpha", 1, "100", "alpha"),
                (1, "beta", 1, "200", "beta"),
                (3, "disabled", 0, "300", "disabled"),
                (1, "12345", 1, "999", "12345"),
                (1, "id-owner", 1, "12345", "id-owner"),
            ],
        )
        await db.execute(
            "INSERT INTO stream_goals(text,done,percent,sort_order) VALUES('legacy-global',0,0,1)"
        )
        await db.execute(
            "INSERT INTO widget_goals_scoped(account_id,channel,text,done,percent,sort_order) "
            "VALUES(1,'alpha','alpha-only',0,0,1)"
        )
        await db.commit()
    finally:
        await db.close()


async def test_resolver_login_before_numeric_id_and_disabled_state(disable_auth):
    await _seed_channels()
    from app.widget_channel_scope import resolve_channel

    assert (await resolve_channel("#ALPHA")).key == "100"
    assert (await resolve_channel("12345")).login == "12345"
    assert (await resolve_channel("200")).login == "beta"
    assert (await resolve_channel("disabled")).enabled is False
    assert await resolve_channel("missing") is None


async def test_stable_id_retains_renamed_login(disable_auth):
    await _seed_channels()
    from app.widget_channel_scope import remember_channel_identity, resolve_channel

    await remember_channel_identity("alpha", "100")
    await remember_channel_identity("alpha-renamed", "100")
    old_url = await resolve_channel("alpha")
    assert old_url and old_url.login == "alpha-renamed" and old_url.renamed
    by_id = await resolve_channel("100")
    assert by_id and by_id.login == "alpha-renamed" and not by_id.renamed


async def test_widget_url_diagnostic_matrix_and_decorative_bypass(disable_auth):
    await _seed_channels()
    from app.server import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/widget/goals?lang=en")
        unknown = await client.get("/widget/goals?channel=absent&lang=ua")
        disabled = await client.get("/widget/goals?channel=disabled")
        active = await client.get("/widget/goals?channel=alpha")
        decorative = await client.get("/widget/animated-bg")
        preview = await client.get("/widget/goals?preview=1")

    assert "data-widget-diagnostic='missing'" in missing.text
    assert "Add a Twitch channel" in missing.text
    assert "data-widget-diagnostic='unknown'" in unknown.text
    assert "Twitch-канал не знайдено" in unknown.text
    assert "data-widget-diagnostic='disabled'" in disabled.text
    assert "data-widget-diagnostic" not in active.text
    assert "data-widget-diagnostic" not in decorative.text
    assert "data-widget-diagnostic" not in preview.text


async def test_renamed_url_shows_warning_while_id_and_new_login_work(disable_auth):
    await _seed_channels()
    from app.server import app
    from app.widget_channel_scope import remember_channel_identity

    await remember_channel_identity("alpha-renamed", "100")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        old_url = await client.get("/widget/goals?channel=alpha&lang=en")
        id_url = await client.get("/widget/goals?channel=100")
        new_url = await client.get("/widget/goals?channel=alpha-renamed")
    assert "data-widget-channel-warning='renamed'" in old_url.text
    assert "Update the Browser Source URL" in old_url.text
    assert "alpha-renamed" in old_url.text
    assert 'id="box"' in old_url.text
    assert "data-widget-diagnostic" not in id_url.text
    assert "data-widget-diagnostic" not in new_url.text


async def test_twitch_id_data_scope_never_falls_back_to_legacy_global(disable_auth):
    await _seed_channels()
    from app.server import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        by_id = await client.get("/api/widgets/public/goals?account_id=1&channel=100")
        channel_only = await client.get("/api/widgets/public/goals?channel=alpha")

    assert [item["text"] for item in by_id.json()["items"]] == ["alpha-only"]
    assert channel_only.status_code == 400
    assert channel_only.json() == {"ok": False, "error": {"code": "bad_request", "params": {}}}


async def test_explicit_empty_websocket_scope_fails_closed(disable_auth):
    from starlette.datastructures import Headers, QueryParams
    from app.routes import websocket_endpoint

    class Socket:
        headers = Headers()
        query_params = QueryParams("channel=")
        client = type("Client", (), {"host": "127.0.0.1"})()

        def __init__(self):
            self.closed = None

        async def close(self, code):
            self.closed = code

    socket = Socket()
    await websocket_endpoint(socket)
    assert socket.closed == 4404


async def test_two_channel_websocket_fanout_and_panel_observer(disable_auth):
    await _seed_channels()
    from app import routes

    class Socket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    alpha, beta, panel = Socket(), Socket(), Socket()
    routes.ws_connections[:] = [alpha, beta, panel]
    routes.ws_channel_scopes.clear()
    routes.ws_channel_scopes.update({id(alpha): "100", id(beta): "200"})
    try:
        await routes.broadcast_log({"type": "tts", "channel": "alpha", "text": "one"})
        await routes.broadcast_log({"type": "tts", "channel": "beta", "text": "two"})
    finally:
        routes.ws_connections.clear()
        routes.ws_channel_scopes.clear()

    assert [item["text"] for item in alpha.messages] == ["one"]
    assert [item["text"] for item in beta.messages] == ["two"]
    assert [item["text"] for item in panel.messages] == ["one", "two"]
    assert alpha.messages[0]["channel_id"] == "100"


async def test_channel_ducks_and_stable_ids_are_isolated():
    from app import widget_bus

    widget_bus._reset_for_tests()
    # 10 с окно: duck_start синхронно рассылает broadcast (resolve_channel может
    # упереться в DNS-таймаут на офлайн-машине) — окно должно пережить задержку.
    await widget_bus.duck_start("donation", channel="alpha", duration_ms=10000)
    assert widget_bus.is_ducked("alpha") is not None
    assert widget_bus.is_ducked("beta") is None
    assert widget_bus.claim_event("alpha", "event-1") is True
    assert widget_bus.claim_event("alpha", "event-1") is False
    assert widget_bus.claim_event("beta", "event-1") is True
    first_delivery = {
        "broadcaster_user_id": "100", "user_id": "viewer", "tier": "1000",
        "_event_id": "delivery-a", "_event_timestamp": "2026-09-09T12:34:51Z",
    }
    second_delivery = {**first_delivery, "_event_id": "delivery-b"}
    assert widget_bus.event_projection_id("channel.subscribe", first_delivery) == \
        widget_bus.event_projection_id("channel.subscribe", second_delivery)


async def test_same_event_from_two_bot_subscriptions_projects_once(
    disable_auth, monkeypatch,
):
    await _seed_channels()
    from app import server, widget_bus, widgets

    projected = []

    async def no_ai_log(*args, **kwargs):
        return None

    async def no_duck(_kind):
        return 0

    async def project(*args, **kwargs):
        projected.append((args, kwargs))

    def discard(coro, **kwargs):
        coro.close()
        return None

    monkeypatch.setattr(server, "ai_log", no_ai_log)
    monkeypatch.setattr(server, "_resolve_duck_duration", no_duck)
    monkeypatch.setattr(server, "_spawn_event_task", discard)
    monkeypatch.setattr(widgets, "on_stream_event", project)
    widget_bus._reset_for_tests()
    event = {
        "broadcaster_user_id": "100", "broadcaster_user_login": "alpha",
        "user_id": "viewer", "user_login": "viewer", "followed_at": "2026-09-09T12:34:50Z",
        "_event_timestamp": "2026-09-09T12:34:51Z",
    }
    await server.on_eventsub_event(1, "channel.follow", "alpha", {**event, "_event_id": "delivery-a"})
    await server.on_eventsub_event(2, "channel.follow", "alpha", {**event, "_event_id": "delivery-b"})

    assert len(projected) == 1


async def test_manual_sound_requires_selected_channel(disable_auth):
    await _seed_channels()
    from app.server import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        play = await client.post("/api/widgets/soundboard/play/1")
        stop = await client.post("/api/widgets/soundboard/stop")
        reward_tts = await client.post(
            "/api/channel-points-tts/1/test", json={"text": "test", "channel": ""}
        )
    assert play.status_code == 400
    assert play.json() == {"ok": False, "error": {"code": "bad_request", "params": {}}}
    assert stop.status_code == 400
    assert reward_tts.json() == {"ok": False, "error": "channel_required"}
