"""Track 6.6: scoped grants and Twitch-verified moderator sessions."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _seed() -> None:
    from app.database import get_db, init_db
    await init_db()
    db = await get_db()
    try:
        await db.executemany("INSERT INTO accounts (id, nickname, token) VALUES (?, ?, 'tok')", [(1, "one"), (2, "two")])
        await db.executemany("INSERT INTO channels (account_id, channel_name) VALUES (?, ?)", [(1, "#Shared"), (2, "shared")])
        await db.commit()
    finally:
        await db.close()


async def test_invite_exchange_is_identity_bound_one_time_and_exact_scoped(monkeypatch):
    from app.moderator_console_routes import authenticate_session, create_invite, exchange_invite, save_grant
    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    grant = await save_grant(1, "#SHARED", {
        "twitch_user_id": "42", "twitch_login": "trusted", "permissions": ["send_tts"], "enabled": True,
    })
    invite = await create_invite(1, "shared", "42", 10)
    async def valid(_token):
        return {"user_id": "42", "login": "trusted", "scopes": [], "expires_in": 3600}
    monkeypatch.setattr("app.twitch_helix.validate_token", valid)
    session = await exchange_invite(invite["invite_token"], "oauth-token-never-stored")
    reused = await exchange_invite(invite["invite_token"], "oauth-token-never-stored")
    assert grant["permissions"] == ["send_tts"]
    assert session["ok"] is True and session["account_id"] == 1 and session["channel"] == "shared"
    assert reused == {"ok": False, "error": "invalid_or_expired_invite"}
    assert await authenticate_session(session["session_token"], "send_tts")
    assert await authenticate_session(session["session_token"], "play_sound") is None
    from app.database import get_db
    db = await get_db()
    try:
        stored_invite = await (await db.execute("SELECT token_hash FROM moderator_console_invites")).fetchone()
        stored_session = await (await db.execute("SELECT token_hash FROM moderator_console_sessions")).fetchone()
        dumped = " ".join((stored_invite["token_hash"], stored_session["token_hash"]))
        assert invite["invite_token"] not in dumped
        assert session["session_token"] not in dumped
        assert "oauth-token-never-stored" not in dumped
    finally:
        await db.close()


async def test_identity_mismatch_and_cross_scope_grant_fail_closed(monkeypatch):
    from app.moderator_console_routes import create_invite, exchange_invite, save_grant
    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    await save_grant(1, "shared", {"twitch_user_id": "42", "permissions": ["send_tts"], "enabled": True})
    invite = await create_invite(1, "shared", "42")
    async def wrong(_token): return {"user_id": "99", "login": "wrong"}
    monkeypatch.setattr("app.twitch_helix.validate_token", wrong)
    assert await exchange_invite(invite["invite_token"], "wrong-token") == {"ok": False, "error": "identity_mismatch"}
    missing = await save_grant(1, "other", {"twitch_user_id": "42", "permissions": ["send_tts"], "enabled": True})
    assert missing == {"ok": False, "error": "scope_not_found"}


async def test_revoke_immediately_invalidates_existing_sessions(monkeypatch):
    from app.moderator_console_routes import authenticate_session, create_invite, exchange_invite, save_grant
    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    await save_grant(1, "shared", {"twitch_user_id": "42", "permissions": ["send_tts"], "enabled": True})
    invite = await create_invite(1, "shared", "42")
    async def valid(_token): return {"user_id": "42", "login": "trusted"}
    monkeypatch.setattr("app.twitch_helix.validate_token", valid)
    session = await exchange_invite(invite["invite_token"], "token")
    await save_grant(1, "shared", {"twitch_user_id": "42", "permissions": [], "enabled": False})
    assert await authenticate_session(session["session_token"]) is None


async def test_invalid_user_ids_and_disabled_defaults_fail_closed(monkeypatch):
    from app.moderator_console_routes import create_invite, save_grant
    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    assert await save_grant(1, "shared", {"twitch_user_id": "login-not-id"}) == {
        "ok": False, "error": "invalid_grant",
    }
    enabled = await save_grant(1, "shared", {"twitch_user_id": "42", "permissions": []})
    assert enabled["enabled"] is True
    assert (await create_invite(1, "shared", "not-numeric"))["error"] == "invalid_grant"
    invalid_permission = await save_grant(1, "shared", {
        "twitch_user_id": "43", "permissions": ["send_tts", "owner_settings"],
    })
    assert invalid_permission == {"ok": False, "error": "invalid_permissions"}


async def test_owner_grant_list_is_exact_scoped_and_contains_no_tokens(monkeypatch):
    from app.moderator_console_routes import list_grants, save_grant
    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    await save_grant(1, "shared", {"twitch_user_id": "42", "twitch_login": "one", "permissions": ["send_tts"]})
    await save_grant(2, "shared", {"twitch_user_id": "99", "twitch_login": "two", "permissions": ["play_sound"]})
    listed = await list_grants(1, "#SHARED")
    assert [row["twitch_user_id"] for row in listed["grants"]] == ["42"]
    assert listed["grants"][0]["permissions"] == ["send_tts"]
    assert "token" not in str(listed).lower()


async def test_moderator_tts_requires_permission_and_explicit_policy(monkeypatch):
    from app.moderator_console_routes import send_moderator_tts
    await _seed()
    session = {"account_id": 1, "channel": "shared", "twitch_user_id": "42",
               "twitch_login": "trusted", "permissions": []}
    assert await send_moderator_tts(session, {"text": "hello"}) == {
        "ok": False, "error": "permission_denied",
    }
    session["permissions"] = ["send_tts"]
    audits = []
    async def audit(action, detail): audits.append((action, detail))
    monkeypatch.setattr("app.moderator_console_routes._audit", audit)
    missing = await send_moderator_tts(session, {"text": "hello", "idempotency_key": "missing-0001"})
    assert missing["ok"] is False and missing["error"] == "policy_missing"
    assert "result=policy_missing" in audits[-1][1]


async def test_moderator_tts_uses_scoped_alias_without_exposing_voice_id(monkeypatch):
    from app.database import get_db
    from app.moderator_console_routes import get_moderator_context, list_moderator_tts_commands, send_moderator_tts
    from app.tts_voice_policy import api_put_alias, api_put_source_policy, reset_runtime_state
    await _seed()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tts_voice_presets (provider, voice_id, label) VALUES ('piper', 'secret-id', 'Warm voice')"
        )
        await db.commit()
    finally:
        await db.close()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.tts_voice_policy._audit", no_audit)
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    assert (await api_put_alias(1, "shared", "warm", {"provider": "piper", "voice_id": "secret-id"}))["ok"]
    assert (await api_put_source_policy(1, "shared", "twitch_moderator_message", {
        "allowed_role": "moderator", "default_alias": "warm", "allow_voice_choice": True,
        "cooldown_sec": 0, "max_per_minute": 5, "max_length": 80, "enabled": True,
    }))["ok"]
    captured = []
    class Queue:
        async def enqueue(self, *args, **kwargs): captured.append((args, kwargs))
    monkeypatch.setattr("app.audio_queue.get_audio_queue", lambda: Queue())
    reset_runtime_state()
    session = {"account_id": 1, "channel": "shared", "twitch_user_id": "42",
               "twitch_login": "trusted", "permissions": ["send_tts"]}
    data = {"text": "hello", "voice_alias": "warm", "idempotency_key": "command-0001"}
    result = await send_moderator_tts(session, data)
    duplicate = await send_moderator_tts(session, data)
    context = await get_moderator_context(session)
    commands = await list_moderator_tts_commands(session)
    assert result["ok"] is True and result["status"] == "accepted" and result["voice_alias"] == "warm"
    assert duplicate == {**result, "duplicate": True}
    assert len(captured) == 1
    assert captured[0][1]["provider_override"] == "piper"
    assert captured[0][1]["voice_override"] == "secret-id"
    assert context["voices"] == [{"alias": "warm", "label": "Warm voice"}]
    assert "secret-id" not in str(context) and "piper" not in str(context)
    assert commands["commands"][0]["text"] == "hello"


async def test_command_history_is_private_to_actor_and_scope(monkeypatch):
    from app.database import get_db
    from app.moderator_console_routes import list_moderator_tts_commands
    await _seed()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO moderator_console_tts_commands "
            "(account_id, channel, twitch_user_id, idempotency_key, text, status) "
            "VALUES (1, 'shared', '42', 'private-0001', 'private text', 'accepted')"
        )
        await db.commit()
    finally:
        await db.close()
    own = {"account_id": 1, "channel": "shared", "twitch_user_id": "42", "permissions": ["send_tts"]}
    other_user = {**own, "twitch_user_id": "99"}
    other_account = {**own, "account_id": 2}
    assert len((await list_moderator_tts_commands(own))["commands"]) == 1
    assert (await list_moderator_tts_commands(other_user))["commands"] == []
    assert (await list_moderator_tts_commands(other_account))["commands"] == []


async def test_chat_tts_requires_exact_command_stable_id_and_explicit_grant(monkeypatch):
    from app.moderator_console_routes import handle_chat_tts_command, save_chat_tts_config, save_grant
    await _seed()
    audits = []
    async def audit(action, detail): audits.append((action, detail))
    monkeypatch.setattr("app.moderator_console_routes._audit", audit)
    assert (await save_chat_tts_config(1, "#SHARED", {"command_alias": "!speak", "enabled": True}))["ok"]
    ignored = await handle_chat_tts_command(
        1, "shared", twitch_user_id="42", twitch_login="user", message_id="m1", message="hello !speak no",
    )
    missing_id = await handle_chat_tts_command(
        1, "shared", twitch_user_id="", twitch_login="mod", message_id="m2", message="!speak hello",
    )
    denied = await handle_chat_tts_command(
        1, "shared", twitch_user_id="42", twitch_login="mod", message_id="m3", message="!speak hello",
    )
    await save_grant(2, "shared", {"twitch_user_id": "42", "permissions": ["send_tts"]})
    still_denied = await handle_chat_tts_command(
        1, "shared", twitch_user_id="42", twitch_login="mod", message_id="m4", message="!speak hello",
    )
    assert ignored == {"handled": False}
    assert missing_id["error"] == "stable_user_id_required"
    assert denied["error"] == "permission_denied" and still_denied["error"] == "permission_denied"
    assert any("user_id=42 result=permission_denied" in detail for _, detail in audits)


async def test_chat_tts_ignores_badges_and_forwards_granted_user(monkeypatch):
    from app.moderator_console_routes import handle_chat_tts_command, save_chat_tts_config, save_grant
    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    await save_chat_tts_config(1, "shared", {"command_alias": "!tts", "enabled": True})
    await save_grant(1, "shared", {"twitch_user_id": "42", "permissions": ["send_tts"]})
    captured = []
    async def send(session, data):
        captured.append((session, data))
        return {"ok": True, "status": "accepted", "command_id": 7, "voice_alias": ""}
    monkeypatch.setattr("app.moderator_console_routes.send_moderator_tts", send)
    result = await handle_chat_tts_command(
        1, "#SHARED", twitch_user_id="42", twitch_login="plainviewer",
        message_id="abc-123", message="!TTS exact text",
    )
    assert result["ok"] is True
    assert captured[0][0]["twitch_user_id"] == "42"
    assert captured[0][1] == {"text": "exact text", "idempotency_key": "chat:abc-123"}


async def test_device_login_exchanges_token_server_side(monkeypatch):
    from app.moderator_console_routes import (
        api_poll_twitch_device,
        api_start_twitch_device,
        create_invite,
        save_grant,
    )
    from app import twitch_oauth

    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    await save_grant(1, "shared", {"twitch_user_id": "42", "permissions": ["send_tts"]})
    invite = await create_invite(1, "shared", "42")

    async def start(scopes=None):
        assert scopes == []
        return {"ok": True, "device_code": "device-secret", "user_code": "ABCD",
                "verification_uri": "https://www.twitch.tv/activate", "expires_in": 600, "interval": 1}
    async def poll(device_code):
        assert device_code == "device-secret"
        return {"ok": True, "access_token": "server-only-access-token"}
    async def validate(token):
        assert token == "server-only-access-token"
        return {"user_id": "42", "login": "trusted"}
    monkeypatch.setattr(twitch_oauth, "start_device_flow", start)
    monkeypatch.setattr(twitch_oauth, "poll_device_token", poll)
    monkeypatch.setattr("app.twitch_helix.validate_token", validate)
    clock = iter((100.0, 100.0, 100.0, 102.0, 102.0, 102.0))
    monkeypatch.setattr("app.moderator_console_routes._device_now", lambda: next(clock))

    started = await api_start_twitch_device({"invite_token": invite["invite_token"]})
    exchanged = await api_poll_twitch_device({
        "invite_token": invite["invite_token"], "device_code": started["device_code"],
    })
    assert exchanged["ok"] is True and exchanged["channel"] == "shared"
    assert "access_token" not in exchanged and "server-only-access-token" not in str(exchanged)
    assert not twitch_oauth.is_known_session("device-secret")


async def test_device_login_is_bound_to_invite_and_owner_admin_accepts_local_owner(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.moderator_console_routes import _owner_auth_dependency, api_poll_twitch_device

    monkeypatch.setenv("PANEL_BIND_HOST", "127.0.0.1")
    monkeypatch.delenv("PANEL_AUTH_USER", raising=False)
    monkeypatch.delenv("PANEL_AUTH_PASS", raising=False)
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    await _owner_auth_dependency(request)
    with pytest.raises(HTTPException) as error:
        await api_poll_twitch_device({"invite_token": "another-invite", "device_code": "device-secret"})
    assert error.value.status_code == 401


async def test_moderator_console_ui_is_separate_scoped_and_secret_safe():
    from pathlib import Path

    root = Path(__file__).parent.parent
    html = (root / "templates" / "moderator_console.html").read_text(encoding="utf-8")
    js = (root / "static" / "moderator-console.js").read_text(encoding="utf-8")
    # Q16 F4: консоль переехала из Настроек в карточку бота-модератора
    owner = (root / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    assert 'id="moderatorTTSAdminCard"' in owner
    assert 'id="moderatorTTSAdminCard"' not in (root / "templates" / "partials" / "settings.html").read_text(encoding="utf-8")
    assert 'id="mcConsole"' in html and '/widget/' not in html
    assert "sessionStorage" in js and "localStorage.setItem('moderator-console-session'" not in js
    assert "history.replaceState(null, '', location.pathname)" in js
    assert "/api/moderator-console/context" in js
    assert "voice_id" not in html and "provider_override" not in js


async def test_moderator_console_rejects_enabled_policy_without_approved_voice(monkeypatch):
    from app.moderator_console_routes import send_moderator_tts
    from app.tts_voice_policy import api_put_source_policy, reset_runtime_state

    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_console_routes._audit", no_audit)
    monkeypatch.setattr("app.tts_voice_policy._audit", no_audit)
    policy = await api_put_source_policy(1, "shared", "twitch_moderator_message", {
        "allowed_role": "moderator", "default_alias": "", "allow_voice_choice": False,
        "cooldown_sec": 0, "max_per_minute": 5, "max_length": 80, "enabled": True,
    })
    reset_runtime_state()
    session = {"account_id": 1, "channel": "shared", "twitch_user_id": "42",
               "twitch_login": "trusted", "permissions": ["send_tts"]}
    result = await send_moderator_tts(session, {
        "text": "must not inherit", "idempotency_key": "approved-voice-0001",
    })
    assert policy["ok"] is True
    assert result["ok"] is False and result["error"] == "approved_voice_required"
