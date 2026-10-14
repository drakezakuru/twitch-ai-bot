"""Selected-chat settings, trusted users, history, and safe widget contract."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


async def _client() -> AsyncClient:
    from app.chat_overlay_routes import admin_router, public_router
    from app.database import init_db
    from app.widgets import public_router as widgets_public

    await init_db()
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    app.include_router(widgets_public)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_trusted_users_are_global_normalized_and_safe(tmp_db, disable_auth):
    async with await _client() as client:
        response = await client.put("/api/widgets/chat/trusted-users", json={
            "users": ["@Friend", "friend", " MOD_User ", "bad-name", "<script>"],
        })
        loaded = await client.get("/api/widgets/chat/trusted-users")

    assert response.json()["users"] == ["friend", "mod_user"]
    assert loaded.json()["users"] == ["friend", "mod_user"]


async def test_trusted_users_import_merges_twitch_roles(tmp_db, disable_auth, monkeypatch):
    from app.database import get_db
    from app import twitch_helix

    async def fake_roles(token, channel, role):
        assert channel == "demo"
        assert role == "moderators"
        return ["New_Mod", "friend"], ""

    monkeypatch.setattr(twitch_helix, "get_channel_role_logins", fake_roles)
    async with await _client() as client:
        db = await get_db()
        try:
            cursor = await db.execute("INSERT INTO accounts (nickname, token) VALUES (?, ?)", ("owner", "token"))
            account_id = cursor.lastrowid
            await db.execute("INSERT INTO channels (account_id, channel_name) VALUES (?, ?)", (account_id, "demo"))
            await db.commit()
        finally:
            await db.close()
        await client.put("/api/widgets/chat/trusted-users", json={"users": ["friend"]})
        response = await client.post("/api/widgets/chat/trusted-users/import", json={
            "account_id": account_id, "channel": "#DEMO", "role": "moderators",
        })

    assert response.status_code == 200
    assert response.json()["users"] == ["friend", "new_mod"]
    assert response.json()["imported"] == 1


async def test_display_settings_are_per_widget_bounded_and_persisted(tmp_db, disable_auth):
    async with await _client() as client:
        response = await client.put("/api/widgets/chat/display/selected-chat", json={
            "max_messages": 999,
            "lifetime_sec": -1,
            "font_size": 200,
            "emote_size": 1,
            "show_badges": False,
            "history_limit": 999,
            "history_minutes": 0,
        })
        loaded = await client.get("/api/widgets/public/chat/display/selected-chat")
        unknown = await client.get("/api/widgets/chat/display/not-a-widget")

    assert response.json()["settings"] == {
        "max_messages": 50,
        "lifetime_sec": 0,
        "font_size": 72,
        "emote_size": 12,
        "show_badges": 0,
        "history_limit": 50,
        "history_minutes": 1,
    }
    assert loaded.json()["settings"] == response.json()["settings"]
    assert unknown.status_code == 404


async def test_display_settings_reject_widgets_without_shared_runtime(tmp_db, disable_auth):
    dead_slugs = (
        "emoji-chat", "tts-chat-overlay", "chat-reader",
        "tts-bot", "tts-raw", "chat-highlight",
    )
    async with await _client() as client:
        for slug in dead_slugs:
            saved = await client.put(
                f"/api/widgets/chat/display/{slug}",
                json={"font_size": 42},
            )
            public = await client.get(f"/api/widgets/public/chat/display/{slug}")
            assert saved.status_code == 404, slug
            assert public.status_code == 404, slug


async def test_live_chat_event_marks_only_trusted_authors(tmp_db, disable_auth):
    from app.chat_overlay_routes import chat_event_payload

    async with await _client() as client:
        await client.put("/api/widgets/chat/trusted-users", json={"users": ["friend"]})
        trusted = await chat_event_payload(
            account_id=1, channel="demo", author="Friend", message="hello", is_bot=False,
            badges=["moderator"], message_id="msg-1",
        )
        regular = await chat_event_payload(
            account_id=1, channel="demo", author="Other", message="hidden", is_bot=False,
        )

    assert trusted["trusted"] is True
    assert trusted["badges"] == ["moderator"]
    assert trusted["message_id"] == "msg-1"
    assert regular["trusted"] is False


async def test_selected_history_filters_trusted_users_and_deduplicates(tmp_db, disable_auth):
    from app.database import get_db

    async with await _client() as client:
        await client.put("/api/widgets/chat/trusted-users", json={"users": ["friend"]})
        db = await get_db()
        try:
            for account_id, channel, author, message in (
                (1, "demo", "Friend", "hello"),
                (2, "demo", "Friend", "hello"),
                (1, "demo", "Other", "hidden"),
                (1, "elsewhere", "Friend", "wrong channel"),
            ):
                await db.execute(
                    "INSERT INTO chat_log (account_id, channel, author, message) VALUES (?, ?, ?, ?)",
                    (account_id, channel, author, message),
                )
            await db.commit()
        finally:
            await db.close()
        response = await client.get(
            "/api/widgets/public/chat/selected-history",
            params={"channel": "#DEMO", "limit": 10, "minutes": 30},
        )

    assert [(item["author"], item["message"]) for item in response.json()["messages"]] == [
        ("Friend", "hello"),
    ]


async def test_selected_chat_widget_has_live_preview_and_safe_shared_renderer(tmp_db, disable_auth):
    async with await _client() as client:
        response = await client.get("/widget/selected-chat?preview=1")
        runtime = await client.get("/widget/_shared/chat-message-core.js")

    assert response.status_code == 200
    assert "#0f0f1a" in response.text
    assert "ChatMessageCore" in response.text
    assert "message.trusted!==true" in response.text
    assert "textContent" in runtime.text
    assert "innerHTML" not in runtime.text


async def test_selected_chat_panel_has_live_controls_and_three_language_labels():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/partials/widgets.html").read_text(encoding="utf-8")
    panel_js = (root / "static/app/07_widgets.js").read_text(encoding="utf-8")
    i18n = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'id="waChatOverlayPanel"' in template
    assert 'class="widget-preview"' in template[template.index('id="waChatOverlayPanel"'):]
    assert "waChatTrustedSave" in panel_js
    assert "waChatImport(role)" in panel_js
    assert "waChatDisplaySave" in panel_js
    # iframe-URL идёт через хелперы версионирования/scope (widgetOutputUrl / waWidgetStateUrl)
    assert "frame.src = waWidgetStateUrl(url.pathname + url.search)" in panel_js
    assert "frame.src = widgetOutputUrl(url.pathname + url.search)" in panel_js
    for key in ("widgets.chat_runtime_title", "widgets.chat_trusted_label", "widgets.chat_import_hint", "widgets.chat_display_hint"):
        assert i18n.count(f"'{key}'") == 3


async def test_twitch_role_import_requires_matching_broadcaster_and_scope(monkeypatch):
    from app import twitch_helix

    monkeypatch.setattr(twitch_helix, "_client_id", lambda: "client-id")

    async def wrong_broadcaster(_token):
        return {"login": "someone_else", "user_id": "1", "scopes": ["moderation:read"]}

    monkeypatch.setattr(twitch_helix, "validate_token", wrong_broadcaster)
    users, error = await twitch_helix.get_channel_role_logins("token", "owner", "moderators")
    assert users == []
    assert error == "broadcaster_token_required"

    async def missing_scope(_token):
        return {"login": "owner", "user_id": "1", "scopes": []}

    monkeypatch.setattr(twitch_helix, "validate_token", missing_scope)
    users, error = await twitch_helix.get_channel_role_logins("token", "owner", "vips")
    assert users == []
    assert error == "missing_scope"


async def test_device_flow_requests_chat_role_import_scopes():
    from app.twitch_oauth import DEFAULT_SCOPES

    assert "moderation:read" in DEFAULT_SCOPES
    assert "channel:read:vips" in DEFAULT_SCOPES
