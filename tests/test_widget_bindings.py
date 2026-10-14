"""§11.3 WIDGETS_PLAN: биндинги виджетов.

1. CRUD-роуты /api/widgets/bindings*.
2. run_binding — dispatcher над публичными функциями widgets.py
   (counter increment/reset, goals add_percent, sub_goal increment).
3. handle_chat_command — матчинг команды, проверка роли, плейсхолдеры.
4. handle_eventsub_event — channel.subscribe → sub-goal +1.
5. Пресеты: deaths / sub_goal / countdown_end (идемпотентно).
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio
SCOPE = {"account_id": 1, "channel": "chan"}
BINDINGS_URL = "/api/widgets/bindings?account_id=1&channel=chan"


async def _client(tmp_db):
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()
    from app.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token, bot_role) "
            "VALUES (1, 'binding_mod', 'fake', 'moderator')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token, bot_role) "
            "VALUES (2, 'binding_other', 'fake', 'moderator')"
        )
        await db.executemany(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
            ((1, "chan"), (1, "other"), (2, "chan")),
        )
        await db.commit()
    finally:
        await db.close()

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_bindings_crud(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        created = (await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "chat_command", "match": "!death", "widget": "counter",
            "widget_key": "death", "action": "increment", "value": "1",
            "role": "mod",
        })).json()
        assert created["ok"] is True and created["id"] > 0
        bid = created["id"]

        items = (await c.get(BINDINGS_URL)).json()["items"]
        assert len(items) == 1 and items[0]["match"] == "!death"

        # валидация
        bad = (await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "chat_command", "match": "x", "widget": "nope"})).json()
        assert bad["detail"] == "unknown_widget"

        upd = (await c.put(
            f"/api/widgets/bindings/{bid}",
            json={**SCOPE, "enabled": False, "role": "streamer"},
        )).json()
        assert upd["ok"] is True
        items = (await c.get(BINDINGS_URL)).json()["items"]
        assert items[0]["enabled"] in (0, False) and items[0]["role"] == "streamer"

        assert (await c.delete(
            f"/api/widgets/bindings/{bid}?account_id=1&channel=chan"
        )).json()["ok"] is True
        assert (await c.get(BINDINGS_URL)).json()["items"] == []


async def test_scoped_preset_api_is_reachable_idempotent_and_isolated(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        url = "/api/widgets/bindings/presets/countdown_end"
        first = await c.post(url, json=SCOPE)
        second = await c.post(url, json={"account_id": 1, "channel": "#CHAN"})
        assert first.status_code == 200
        assert first.json() == {"ok": True, "created": 2}
        assert second.json() == {"ok": True, "created": 0}

        scoped = (await c.get(BINDINGS_URL)).json()["items"]
        other_channel = (await c.get(
            "/api/widgets/bindings?account_id=1&channel=other"
        )).json()["items"]
        other_account = (await c.get(
            "/api/widgets/bindings?account_id=2&channel=chan"
        )).json()["items"]
        assert len(scoped) == 2
        assert other_channel == []
        assert other_account == []

        unknown = await c.post(
            "/api/widgets/bindings/presets/missing", json=SCOPE
        )
        missing_scope = await c.post(url, json={"account_id": 0, "channel": ""})
        assert unknown.status_code == 400
        assert unknown.json()["detail"] == "unknown_preset"
        assert missing_scope.status_code == 400
        assert missing_scope.json()["detail"] == "binding_scope_required"


async def test_run_binding_counter_and_goals(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        from app.widget_bindings import run_binding
        # counter: increment создаёт ключ и растит value
        r = await run_binding({"widget": "counter", "widget_key": "death",
                               "action": "increment", "value": "1"})
        assert r.get("ok") is True
        pub = (await c.get("/api/widgets/public/counter/death")).json()
        assert pub.get("value", 0) >= 1
        # reset
        r = await run_binding({"widget": "counter", "widget_key": "death", "action": "reset"})
        assert r.get("ok") is True
        # goals: add_percent
        gid = (await c.post("/api/widgets/goals", json={"text": "g", "percent": 50})).json()["id"]
        r = await run_binding({"widget": "goals", "widget_key": str(gid),
                               "action": "add_percent", "value": "10"})
        assert r.get("percent") == 60
        r = await run_binding({"widget": "goals", "widget_key": str(gid),
                               "action": "reset", "value": ""})
        assert r.get("percent") == 0
        # sub_goal: increment
        r = await run_binding({"widget": "sub_goal", "action": "increment", "value": "3"})
        assert r.get("current", 0) >= 3


async def test_chat_command_binding_roles(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "chat_command", "match": "!death", "widget": "counter",
            "widget_key": "death", "action": "increment", "value": "1", "role": "mod",
        })
        from app.widget_bindings import handle_chat_command
        # зритель не может
        res = await handle_chat_command("!death", "someviewer", 1, "chan", role="viewer")
        assert res == []
        pub = (await c.get("/api/widgets/public/counter/death")).json()
        assert pub.get("value", 0) == 0
        # модер может
        res = await handle_chat_command("!death", "mod1", 1, "chan", role="mod")
        assert len(res) == 1
        res = await handle_chat_command("!death", "twitchmod", 1, "chan", role="moderator")
        assert len(res) == 1
        pub = (await c.get(
            "/api/widgets/public/counter/death?account_id=1&channel=chan"
        )).json()
        assert pub.get("value", 0) >= 1


async def test_eventsub_binding_sub_goal(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "eventsub", "match": "channel.subscribe", "widget": "sub_goal",
            "action": "increment", "value": "1", "role": "any",
        })
        from app.widget_bindings import handle_eventsub_event
        res = await handle_eventsub_event(1, "channel.subscribe", "chan", "user1", 0)
        assert len(res) == 1
        # чужое событие не матчится
        res = await handle_eventsub_event(1, "channel.raid", "chan", "user2", 5)
        assert res == []
        sub = (await c.get(
            "/api/widgets/public/sub-goal?account_id=1&channel=chan"
        )).json()
        assert sub["current"] >= 1


async def test_semantic_actions_execute_real_widget_operations(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        from app.widget_bindings import run_binding

        await c.put("/api/widgets/countdown", json={"duration_sec": 60})
        timer = await run_binding({"widget": "countdown", "action": "add_time", "value": "300"})
        assert timer["duration_sec"] == 360
        await run_binding({"widget": "countdown", "action": "start"})
        paused = await run_binding({"widget": "countdown", "action": "pause"})
        assert paused["state"] == "stopped"

        await run_binding({"widget": "now_playing", "action": "set", "value": "Demo track"})
        cleared = await run_binding({"widget": "now_playing", "action": "clear"})
        assert cleared["text"] == ""

        shown = await run_binding({"widget": "lower_third", "action": "show", "value": "Streamer"})
        assert shown["visible"] is True and shown["name"] == "Streamer"
        hidden = await run_binding({"widget": "lower_third", "action": "hide", "value": ""})
        assert hidden["visible"] is False


async def test_chat_command_requires_token_boundary(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "chat_command", "match": "!goal", "widget": "sub_goal",
            "action": "increment", "value": "1", "role": "mod",
        })
        from app.widget_bindings import handle_chat_command
        assert await handle_chat_command("!goals", "viewer", 1, "chan") == []
        assert len(await handle_chat_command("!goal now", "mod", 1, "chan", "mod")) == 1
        assert len(await handle_chat_command("!goal\tmore", "mod", 1, "chan", "mod")) == 1


async def test_subscribe_binding_owns_only_one_sub_goal_increment(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "eventsub", "match": "channel.subscribe", "widget": "sub_goal",
            "action": "increment", "value": "1", "role": "any",
        })
        from app.widget_bindings import handle_eventsub_event, has_sub_goal_subscribe_binding
        from app.widgets import on_subscribe_event

        assert await has_sub_goal_subscribe_binding(1, "#CHAN") is True
        await on_subscribe_event(increment_sub_goal=False)
        await handle_eventsub_event(1, "channel.subscribe", "chan", "viewer")
        state = (await c.get(
            "/api/widgets/public/sub-goal?account_id=1&channel=chan"
        )).json()
        assert state["current"] == 1
        assert (await c.get("/api/widgets/public/sub-goal")).json()["current"] == 0
        assert (await c.get(
            "/api/widgets/public/sub-goal?account_id=1&channel=other"
        )).json()["current"] == 0


async def test_production_eventsub_handler_dispatches_binding_once(
    tmp_db, disable_auth, monkeypatch
):
    async with await _client(tmp_db) as c:
        await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "eventsub", "match": "channel.subscribe", "widget": "sub_goal",
            "action": "increment", "value": "1", "role": "any",
        })
        from app import server

        scheduled = []
        monkeypatch.setattr(
            server,
            "_spawn_event_task",
            lambda coro, *, name: scheduled.append(coro),
        )
        await server.on_eventsub_event(
            1, "channel.subscribe", "#CHAN", {"user_login": "fake-viewer"}
        )
        assert len(scheduled) == 1
        await asyncio.gather(*scheduled)

        state = (await c.get(
            "/api/widgets/public/sub-goal?account_id=1&channel=chan"
        )).json()
        assert state["current"] == 1


async def test_duplicate_active_sub_goal_subscription_binding_is_rejected(
    tmp_db, disable_auth
):
    async with await _client(tmp_db) as c:
        payload = {
            **SCOPE,
            "source": "eventsub", "match": "channel.subscribe", "widget": "sub_goal",
            "action": "increment", "value": "1", "role": "any",
        }
        first = await c.post("/api/widgets/bindings", json=payload)
        duplicate = await c.post(
            "/api/widgets/bindings", json={**payload, "channel": "#CHAN", "value": "2"}
        )

        assert first.status_code == 200
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "duplicate_binding"

        from app.widget_bindings import handle_eventsub_event
        results = await handle_eventsub_event(1, "channel.subscribe", "chan", "viewer")
        assert len(results) == 1
        state = (await c.get(
            "/api/widgets/public/sub-goal?account_id=1&channel=chan"
        )).json()
        assert state["current"] == 1


async def test_streamer_binding_rejects_moderator_roles(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        await c.post("/api/widgets/bindings", json={
            **SCOPE,
            "source": "chat_command", "match": "!owner", "widget": "counter",
            "widget_key": "owner", "action": "increment", "value": "1",
            "role": "streamer",
        })
        from app.widget_bindings import handle_chat_command

        assert await handle_chat_command("!owner", "mod", 1, "chan", "mod") == []
        assert await handle_chat_command(
            "!owner", "moderator", 1, "chan", "moderator"
        ) == []
        assert len(await handle_chat_command(
            "!owner", "owner", 1, "chan", "broadcaster"
        )) == 1


async def test_subscribe_deduplication_keeps_newer_active_binding(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        from app.database import get_db
        from app.widgets import ensure_widgets_schema

        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO widget_bindings "
                "(account_id, channel, enabled, source, match, widget, widget_key, action, value, role) "
                "VALUES (1, 'chan', 0, 'eventsub', 'channel.subscribe', 'sub_goal', '', "
                "'increment', '1', 'any')"
            )
            active = await db.execute(
                "INSERT INTO widget_bindings "
                "(account_id, channel, enabled, source, match, widget, widget_key, action, value, role) "
                "VALUES (1, 'chan', 1, 'eventsub', 'channel.subscribe', 'sub_goal', '', "
                "'increment', '1', 'any')"
            )
            await db.commit()
            active_id = active.lastrowid
        finally:
            await db.close()

        await ensure_widgets_schema()
        items = (await c.get(BINDINGS_URL)).json()["items"]
        assert next(item for item in items if item["id"] == active_id)["enabled"] == 1


async def test_binding_update_rejects_empty_match_and_viewer_moderation(
    tmp_db, disable_auth
):
    async with await _client(tmp_db) as c:
        created = await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "eventsub", "match": "channel.follow", "widget": "sub_goal",
            "action": "increment", "value": "1", "role": "any",
        })
        bid = created.json()["id"]
        empty = await c.put(
            f"/api/widgets/bindings/{bid}", json={**SCOPE, "match": ""}
        )
        assert empty.status_code == 400
        assert empty.json()["detail"] == "match_required"

        unsafe = await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "chat_command", "match": "!timeout", "widget": "moderation",
            "action": "timeout_last", "role": "any",
        })
        assert unsafe.status_code == 400
        assert unsafe.json()["detail"] == "role_not_allowed"


async def test_binding_contract_rejects_dead_sources_and_invalid_typed_values(
    tmp_db, disable_auth
):
    async with await _client(tmp_db) as c:
        async def create(**overrides):
            payload = {
                **SCOPE,
                "source": "chat_command", "match": "!goal", "widget": "goals",
                "widget_key": "1", "action": "add_percent", "value": "1", "role": "mod",
            }
            payload.update(overrides)
            return await c.post("/api/widgets/bindings", json=payload)

        bad_event = await create(source="eventsub", match="channel.fake", role="any")
        assert bad_event.status_code == 400
        assert bad_event.json()["detail"] == "bad_eventsub_match"

        event_role = await create(
            source="eventsub", match="channel.follow", role="mod"
        )
        assert event_role.status_code == 400
        assert event_role.json()["detail"] == "role_not_allowed"

        moderation_chat = await create(
            widget="moderation", widget_key="", action="slow_on",
            source="chat_command", match="!slow", role="streamer",
        )
        assert moderation_chat.status_code == 400
        assert moderation_chat.json()["detail"] == "role_not_allowed"

        missing_goal = await create(widget_key="")
        assert missing_goal.status_code == 400
        assert missing_goal.json()["detail"] == "widget_key_required"

        bad_number = await create(value="many")
        assert bad_number.status_code == 400
        assert bad_number.json()["detail"] == "bad_value"

        bad_source = await create(source="timer")
        assert bad_source.status_code == 400
        assert bad_source.json()["detail"] == "bad_source"

        amount_template = await create(
            source="eventsub", match="channel.cheer", value="{amount}", role="any"
        )
        assert amount_template.status_code == 200


async def test_binding_update_validates_proposed_source_and_role(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        created = await c.post("/api/widgets/bindings", json={**SCOPE,
            "source": "chat_command", "match": "!death", "widget": "counter",
            "widget_key": "death", "action": "increment", "value": "1", "role": "mod",
        })
        bid = created.json()["id"]

        invalid = await c.put(
            f"/api/widgets/bindings/{bid}",
            json={**SCOPE, "source": "eventsub", "match": "channel.follow", "role": "mod"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["detail"] == "role_not_allowed"

        valid = await c.put(
            f"/api/widgets/bindings/{bid}",
            json={**SCOPE, "source": "eventsub", "match": "channel.follow", "role": "any"},
        )
        assert valid.status_code == 200


async def test_mutating_bindings_reject_viewer_and_non_owner_hotkey_roles(
    tmp_db, disable_auth
):
    async with await _client(tmp_db) as c:
        viewer = await c.post("/api/widgets/bindings", json={
            **SCOPE, "source": "chat_command", "match": "!goal",
            "widget": "sub_goal", "action": "increment", "value": "1",
            "role": "any",
        })
        assert viewer.status_code == 400
        assert viewer.json()["detail"] == "role_not_allowed"

        moderator_hotkey = await c.post("/api/widgets/bindings", json={
            **SCOPE, "source": "hotkey", "match": "ctrl+g",
            "widget": "sub_goal", "action": "increment", "value": "1",
            "role": "mod",
        })
        assert moderator_hotkey.status_code == 400
        assert moderator_hotkey.json()["detail"] == "role_not_allowed"


async def test_runtime_rejects_legacy_viewer_binding(tmp_db, disable_auth):
    async with await _client(tmp_db):
        from app.widget_bindings import run_binding

        result = await run_binding({
            **SCOPE, "source": "chat_command", "match": "!goal",
            "widget": "sub_goal", "action": "increment", "value": "1",
            "role": "any",
        })
        assert result["error"] == "role_not_allowed"


async def test_runtime_rejects_unsafe_legacy_moderation_binding(tmp_db, disable_auth):
    async with await _client(tmp_db):
        from app.widget_bindings import run_binding

        result = await run_binding({
            "source": "chat_command", "match": "!slow", "widget": "moderation",
            "action": "slow_on", "value": "5", "role": "streamer",
        })
        assert result["error"] == "role_not_allowed"


async def test_binding_scope_isolates_chat_eventsub_hotkey_and_list(
    tmp_db, disable_auth
):
    async with await _client(tmp_db) as c:
        bindings = (
            ("chat_command", "!scoped", "death"),
            ("eventsub", "channel.cheer", "cheer"),
            ("hotkey", "ctrl+q", "hotkey"),
        )
        for source, match, key in bindings:
            response = await c.post("/api/widgets/bindings", json={
                **SCOPE, "source": source, "match": match, "widget": "counter",
                "widget_key": key, "action": "increment", "value": "1",
                "role": "any" if source == "eventsub" else (
                    "streamer" if source == "hotkey" else "mod"
                ),
            })
            assert response.status_code == 200

        assert len((await c.get(BINDINGS_URL)).json()["items"]) == 3
        assert (await c.get(
            "/api/widgets/bindings?account_id=1&channel=other"
        )).json()["items"] == []
        assert (await c.get(
            "/api/widgets/bindings?account_id=2&channel=chan"
        )).json()["items"] == []

        from app.widget_bindings import (
            handle_chat_command,
            handle_eventsub_event,
            handle_hotkey,
        )

        assert await handle_chat_command("!scoped", "u", 2, "chan", "broadcaster") == []
        assert await handle_chat_command("!scoped", "u", 1, "other", "broadcaster") == []
        assert len(await handle_chat_command(
            "!scoped", "u", 1, " #CHAN ", "broadcaster"
        )) == 1

        assert await handle_eventsub_event(2, "channel.cheer", "chan", "u", 1) == []
        assert await handle_eventsub_event(1, "channel.cheer", "other", "u", 1) == []
        assert len(await handle_eventsub_event(
            1, "channel.cheer", "#CHAN", "u", 1
        )) == 1

        assert (await handle_hotkey("ctrl+q", 2, "chan"))["executed"] == []
        assert (await handle_hotkey("ctrl+q", 1, "other"))["executed"] == []
        assert len((await handle_hotkey("ctrl+q", 1, "#CHAN"))["executed"]) == 1

        scoped = (await c.get(
            "/api/widgets/public/counter/death?account_id=1&channel=chan"
        )).json()
        other_account = (await c.get(
            "/api/widgets/public/counter/death?account_id=2&channel=chan"
        )).json()
        other_channel = (await c.get(
            "/api/widgets/public/counter/death?account_id=1&channel=other"
        )).json()
        compatibility = (await c.get("/api/widgets/public/counter/death")).json()
        assert scoped["value"] == 1
        assert other_account["value"] == 0
        assert other_channel["value"] == 0
        assert compatibility["value"] == 0


async def test_goal_binding_cannot_mutate_another_scope(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        goal_a = (await c.post(
            "/api/widgets/goals?account_id=1&channel=chan",
            json={"text": "A", "percent": 10},
        )).json()["id"]
        goal_b = (await c.post(
            "/api/widgets/goals?account_id=1&channel=other",
            json={"text": "B", "percent": 20},
        )).json()["id"]
        await c.post("/api/widgets/bindings", json={
            **SCOPE, "source": "chat_command", "match": "!goal",
            "widget": "goals", "widget_key": str(goal_a),
            "action": "add_percent", "value": "5", "role": "mod",
        })

        from app.widget_bindings import handle_chat_command
        await handle_chat_command("!goal", "moderator", 1, "chan", "mod")

        state_a = (await c.get(
            "/api/widgets/public/goals?account_id=1&channel=chan"
        )).json()["items"]
        state_b = (await c.get(
            "/api/widgets/public/goals?account_id=1&channel=other"
        )).json()["items"]
        legacy = (await c.get("/api/widgets/public/goals")).json()["items"]
        assert state_a == [{"id": goal_a, "text": "A", "done": 0, "percent": 15}]
        assert state_b == [{"id": goal_b, "text": "B", "done": 0, "percent": 20}]
        assert legacy == []


async def test_countdown_binding_mutates_only_its_scope(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        await c.put(
            "/api/widgets/countdown?account_id=1&channel=chan",
            json={"duration_sec": 120, "title": "A"},
        )
        await c.put(
            "/api/widgets/countdown?account_id=1&channel=other",
            json={"duration_sec": 240, "title": "B"},
        )
        from app.widget_bindings import run_binding
        await run_binding({
            **SCOPE, "widget": "countdown", "action": "start", "value": "",
        })
        await run_binding({
            **SCOPE, "widget": "countdown", "action": "add_time", "value": "30",
        })

        state_a = (await c.get(
            "/api/widgets/public/countdown?account_id=1&channel=chan"
        )).json()
        state_b = (await c.get(
            "/api/widgets/public/countdown?account_id=1&channel=other"
        )).json()
        legacy = (await c.get("/api/widgets/public/countdown")).json()
        assert (state_a["state"], state_a["duration_sec"]) == ("running", 150)
        assert (state_b["state"], state_b["duration_sec"]) == ("stopped", 240)
        assert (legacy["state"], legacy["duration_sec"]) == ("stopped", 300)


async def test_lower_third_binding_mutates_only_its_scope(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        from app.widget_bindings import run_binding
        await run_binding({
            **SCOPE, "widget": "lower_third", "action": "show", "value": "Scope A",
        })

        state_a = (await c.get(
            "/api/widgets/public/lower-third?account_id=1&channel=chan"
        )).json()
        state_b = (await c.get(
            "/api/widgets/public/lower-third?account_id=1&channel=other"
        )).json()
        legacy = (await c.get("/api/widgets/public/lower-third")).json()
        assert state_a["visible"] is True and state_a["name"] == "Scope A"
        assert state_b["visible"] is False and state_b["name"] == ""
        assert legacy["visible"] is False and legacy["name"] == ""


@pytest.mark.parametrize("path", [
    "/api/widgets/goals",
    "/api/widgets/public/goals",
    "/api/widgets/sub-goal",
    "/api/widgets/public/sub-goal",
    "/api/widgets/now-playing",
    "/api/widgets/public/now-playing",
    "/api/widgets/counters",
    "/api/widgets/public/counter/death",
    "/api/widgets/countdown",
    "/api/widgets/public/countdown",
    "/api/widgets/lower-third",
    "/api/widgets/public/lower-third",
])
async def test_state_endpoints_reject_invalid_or_unconfigured_scope(
    tmp_db, disable_auth, path,
):
    async with await _client(tmp_db) as c:
        from app.database import get_db
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'disabled', 0)"
            )
            await db.commit()
        finally:
            await db.close()

        cases = (
            ("account_id=1", "widget_scope_required"),
            ("account_id=0&channel=chan", "widget_scope_required"),
            ("account_id=999&channel=chan", "widget_scope_not_found"),
            ("account_id=1&channel=disabled", "widget_scope_not_found"),
        )
        for query, detail in cases:
            response = await c.get(f"{path}?{query}")
            assert response.status_code == 400, (path, query, response.text)
            assert response.json()["detail"] == detail


@pytest.mark.parametrize(("method", "path", "payload"), [
    ("post", "/api/widgets/goals", {"text": "blocked"}),
    ("put", "/api/widgets/goals/999", {"percent": 50}),
    ("delete", "/api/widgets/goals/999", None),
    ("post", "/api/widgets/goals/clear-done", None),
    ("post", "/api/widgets/goals/999/step", {"delta": 1}),
    ("put", "/api/widgets/sub-goal", {"current": 1}),
    ("post", "/api/widgets/sub-goal/increment", {"delta": 1}),
    ("post", "/api/widgets/sub-goal/reset", None),
    ("post", "/api/widgets/public/sub-goal/increment", {"delta": 1}),
    ("put", "/api/widgets/now-playing", {"text": "blocked"}),
    ("post", "/api/widgets/now-playing/clear", None),
    ("put", "/api/widgets/counters/death", {"value": 1}),
    ("post", "/api/widgets/counters/death/increment", {"delta": 1}),
    ("post", "/api/widgets/counters/death/reset", None),
    ("put", "/api/widgets/countdown", {"duration_sec": 60}),
    ("post", "/api/widgets/countdown/start", None),
    ("post", "/api/widgets/countdown/stop", None),
    ("post", "/api/widgets/countdown/reset", None),
    ("put", "/api/widgets/lower-third", {"visible": True}),
])
async def test_state_mutations_reject_unconfigured_scope(
    tmp_db, disable_auth, method, path, payload,
):
    async with await _client(tmp_db) as c:
        response = await c.request(
            method, f"{path}?account_id=999&channel=unknown", json=payload,
        )
        assert response.status_code == 400, (method, path, response.text)
        assert response.json()["detail"] == "widget_scope_not_found"


async def test_state_scope_normalizes_channel_aliases(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        updated = await c.put(
            "/api/widgets/countdown?account_id=1&channel=%20%23CHAN%20",
            json={"duration_sec": 75, "title": "Normalized"},
        )
        assert updated.status_code == 200

        canonical = (await c.get(
            "/api/widgets/public/countdown?account_id=1&channel=chan"
        )).json()
        assert canonical["duration_sec"] == 75
        assert canonical["title"] == "Normalized"


async def test_goal_crud_cannot_address_id_from_another_scope(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        foreign_id = (await c.post(
            "/api/widgets/goals?account_id=1&channel=other",
            json={"text": "Foreign", "percent": 20},
        )).json()["id"]
        base = f"/api/widgets/goals/{foreign_id}?account_id=1&channel=chan"

        updated = await c.put(base, json={"percent": 90})
        stepped = await c.post(base.replace("?", "/step?"), json={"delta": 5})
        deleted = await c.delete(base)
        assert updated.json() == {"error": "not_found"}
        assert stepped.json() == {"error": "not_found"}
        assert deleted.json() == {"error": "not_found"}

        foreign = (await c.get(
            "/api/widgets/public/goals?account_id=1&channel=other"
        )).json()["items"]
        assert foreign == [{
            "id": foreign_id, "text": "Foreign", "done": 0, "percent": 20,
        }]


async def test_bindings_api_requires_configured_exact_scope(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        base = {
            "source": "chat_command", "match": "!scope", "widget": "counter",
            "widget_key": "death", "action": "increment", "value": "1", "role": "mod",
        }
        missing = await c.post("/api/widgets/bindings", json=base)
        assert missing.status_code == 400
        assert missing.json()["detail"] == "binding_scope_required"

        malformed = await c.post(
            "/api/widgets/bindings", json={**base, "account_id": "bad", "channel": "chan"}
        )
        assert malformed.status_code == 400
        assert malformed.json()["detail"] == "binding_scope_required"

        unknown = await c.post(
            "/api/widgets/bindings", json={**base, "account_id": 1, "channel": "unknown"}
        )
        assert unknown.status_code == 400
        assert unknown.json()["detail"] == "binding_scope_not_found"


async def test_binding_update_and_delete_hide_other_scope(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        created = await c.post("/api/widgets/bindings", json={
            **SCOPE, "source": "chat_command", "match": "!private", "widget": "counter",
            "widget_key": "death", "action": "increment", "value": "1", "role": "mod",
        })
        bid = created.json()["id"]

        update = await c.put(
            f"/api/widgets/bindings/{bid}",
            json={"account_id": 2, "channel": "chan", "enabled": False},
        )
        assert update.status_code == 404
        assert update.json()["detail"] == "binding_not_found"

        delete = await c.delete(
            f"/api/widgets/bindings/{bid}?account_id=1&channel=other"
        )
        assert delete.status_code == 404
        assert delete.json()["detail"] == "binding_not_found"

        item = (await c.get(BINDINGS_URL)).json()["items"][0]
        assert item["id"] == bid
        assert item["enabled"] in (1, True)


async def test_legacy_global_binding_rows_are_deleted_during_migration(
    tmp_db, disable_auth
):
    from app.database import get_db, init_db
    from app.widgets import ensure_widgets_schema

    await init_db()
    db = await get_db()
    try:
        await db.execute("DROP TABLE widget_bindings")
        await db.execute("""
            CREATE TABLE widget_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                enabled INTEGER DEFAULT 1,
                source TEXT DEFAULT 'chat_command',
                match TEXT DEFAULT '',
                widget TEXT DEFAULT '',
                widget_key TEXT DEFAULT '',
                action TEXT DEFAULT 'increment',
                value TEXT DEFAULT '',
                role TEXT DEFAULT 'mod',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "INSERT INTO widget_bindings (match, widget, action) "
            "VALUES ('!legacy', 'counter', 'increment')"
        )
        await db.commit()
    finally:
        await db.close()

    await ensure_widgets_schema()
    db = await get_db()
    try:
        column_rows = await (await db.execute(
                "PRAGMA table_info(widget_bindings)"
            )).fetchall()
        columns = {row[1] for row in column_rows}
        count = (await (await db.execute(
            "SELECT COUNT(*) FROM widget_bindings"
        )).fetchone())[0]
        not_null = {row[1]: row[3] for row in column_rows}
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) "
            "VALUES (1, 'migration_test', 'fake')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) "
            "VALUES (1, 'chan', 1)"
        )
        await db.execute(
            "INSERT INTO widget_bindings "
            "(account_id, channel, source, match, widget, widget_key, action, value, role) "
            "VALUES (1, '#CHAN', 'chat_command', '!kept', 'counter', 'death', "
            "'increment', '1', 'mod')"
        )
        await db.commit()
    finally:
        await db.close()
    assert {"account_id", "channel"} <= columns
    assert not_null["account_id"] == 1
    assert not_null["channel"] == 1
    assert count == 0

    await ensure_widgets_schema()
    await ensure_widgets_schema()
    db = await get_db()
    try:
        kept = await (await db.execute(
            "SELECT account_id, channel, match FROM widget_bindings"
        )).fetchall()
        indexes = {
            row[1] for row in await (await db.execute(
                "PRAGMA index_list(widget_bindings)"
            )).fetchall()
        }
    finally:
        await db.close()
    assert [tuple(row) for row in kept] == [(1, "chan", "!kept")]
    assert {
        "idx_widget_bindings_scope_source", "idx_widget_bindings_scope_event",
        "idx_widget_bindings_one_sub_goal_subscribe",
    } <= indexes


