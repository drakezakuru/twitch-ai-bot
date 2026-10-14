"""Track 6.6: exact-scoped moderator commands reuse the OBS soundboard."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _seed() -> None:
    from app.database import get_db, init_db
    from app.moderator_sound_routes import ensure_schema, reset_runtime_state

    reset_runtime_state()
    await init_db()
    db = await get_db()
    try:
        await db.executemany("INSERT INTO accounts (id,nickname,token) VALUES (?,?,'tok')", [(1, "one"), (2, "two")])
        await db.executemany("INSERT INTO channels (account_id,channel_name) VALUES (?,?)", [(1, "#Shared"), (2, "shared")])
        await db.executemany("INSERT INTO soundboard_tracks (name,filename,mime) VALUES (?,?,'audio/mpeg')", [("Airhorn", "one.mp3"), ("Bell", "two.mp3")])
        await ensure_schema(db)
        await db.commit()
    finally:
        await db.close()


def _session(account_id=1, user_id="42", permissions=None):
    return {"account_id": account_id, "channel": "#SHARED", "twitch_user_id": user_id,
            "permissions": permissions if permissions is not None else ["play_sound"]}


async def test_only_owner_approved_sound_is_visible_and_playable(monkeypatch):
    from app.moderator_sound_routes import list_approved_sounds, play_moderator_sound, save_sound_approval

    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_sound_routes._audit", no_audit)
    assert (await save_sound_approval(1, "shared", 1, enabled=True))["ok"]
    assert [item["id"] for item in (await list_approved_sounds(_session()))["items"]] == [1]
    assert (await play_moderator_sound(_session(), {"track_id": 2, "idempotency_key": "sound-unapproved-001"}))["error"] == "unapproved_track"


async def test_sound_command_is_exact_scope_idempotent_and_audited(monkeypatch):
    import importlib

    from app.moderator_sound_routes import play_moderator_sound, save_sound_approval

    await _seed()
    events, audits = [], []
    async def broadcast(event): events.append(event)
    async def audit(action, detail): audits.append((action, detail))
    monkeypatch.setattr("app.moderator_sound_routes._audit", audit)
    monkeypatch.setattr(importlib.import_module("app.server"), "broadcast_log", broadcast)
    await save_sound_approval(1, "#SHARED", 1, enabled=True)
    accepted = await play_moderator_sound(_session(), {"track_id": 1, "idempotency_key": "sound-accepted-001"})
    duplicate = await play_moderator_sound(_session(), {"track_id": 1, "idempotency_key": "sound-accepted-001"})
    other_scope = await play_moderator_sound(_session(2), {"track_id": 1, "idempotency_key": "sound-other-scope-01"})
    assert accepted == duplicate
    assert accepted["status"] == "accepted" and len(events) == 1
    assert events[0]["account_id"] == 1 and events[0]["channel"] == "shared"
    assert other_scope["error"] == "unapproved_track"
    assert any("user_id=42 track_id=1 result=accepted" in detail for _, detail in audits)


async def test_sound_permission_and_limits_fail_closed(monkeypatch):
    from app.moderator_sound_routes import play_moderator_sound, save_sound_approval, save_sound_policy

    await _seed()
    async def no_audit(*args): pass
    monkeypatch.setattr("app.moderator_sound_routes._audit", no_audit)
    await save_sound_approval(1, "shared", 1, enabled=True)
    assert (await play_moderator_sound(_session(permissions=[]), {"track_id": 1, "idempotency_key": "sound-no-permission"}))["error"] == "permission_denied"
    await save_sound_policy(1, "shared", {"cooldown_sec": 60, "max_per_minute": 1, "enabled": True})
    assert (await play_moderator_sound(_session(), {"track_id": 1, "idempotency_key": "sound-limits-first"}))["ok"]
    assert (await play_moderator_sound(_session(), {"track_id": 1, "idempotency_key": "sound-limits-second"}))["error"] == "cooldown"
    assert (await play_moderator_sound(_session(), {"track_id": 1}))["error"] == "idempotency_key_required"


async def test_moderator_stop_is_permissioned_scoped_and_audited(monkeypatch):
    from app.moderator_sound_routes import stop_moderator_sound

    await _seed()
    events, audits = [], []

    async def broadcast(event):
        events.append(event)

    async def audit(action, detail):
        audits.append((action, detail))

    monkeypatch.setattr("app.soundboard_library._broadcast", broadcast)
    monkeypatch.setattr("app.moderator_sound_routes._audit", audit)
    denied = await stop_moderator_sound(_session(permissions=[]))
    accepted = await stop_moderator_sound(_session())
    assert denied == {"ok": False, "error": "permission_denied"}
    assert accepted["status"] == "accepted" and accepted["telemetry"] == "unverified"
    assert events == [{
        "type": "soundboard", "kind": "stop", "source": "moderator_console",
        "at": events[0]["at"], "account_id": 1, "channel": "shared",
    }]
    assert audits[0][0] == "moderator_sound_stop"


async def test_soundboard_obs_token_is_scoped_hashed_and_rotating(monkeypatch):
    from app.database import get_db
    from app.moderator_sound_routes import rotate_obs_token, valid_obs_token

    await _seed()

    async def no_audit(*args):
        pass

    monkeypatch.setattr("app.moderator_sound_routes._audit", no_audit)
    first = await rotate_obs_token(1, "#SHARED")
    first_token = first["widget_url"].split("token=", 1)[1]
    assert await valid_obs_token(1, "shared", first_token)
    assert not await valid_obs_token(2, "shared", first_token)
    second = await rotate_obs_token(1, "shared")
    second_token = second["widget_url"].split("token=", 1)[1]
    assert second_token != first_token
    assert not await valid_obs_token(1, "shared", first_token)
    assert await valid_obs_token(1, "shared", second_token)

    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT obs_token_hash FROM moderator_console_sound_policy "
            "WHERE account_id=1 AND channel='shared'"
        )).fetchone()
    finally:
        await db.close()
    assert row["obs_token_hash"] not in {first_token, second_token}

    from app.widgets import widget_soundboard
    from fastapi import HTTPException
    assert "Soundboard" in await widget_soundboard()
    with pytest.raises(HTTPException) as denied:
        await widget_soundboard(account_id=1, channel="shared", token="wrong")
    assert denied.value.status_code == 403
    assert "Soundboard" in await widget_soundboard(
        account_id=1, channel="shared", token=second_token,
    )


async def test_soundboard_has_one_player_with_scoped_event_filter():
    from pathlib import Path

    html = Path("widgets/soundboard/index.html").read_text(encoding="utf-8")
    assert "_scope.account_id?(!d.account_id" in html
    assert "new URL(`/api/widgets/public/soundboard/tracks/${d.track_id}`,base)" in html
    assert "new URL(_WIDGET_API_BASE,location.href)" in html
    assert "['account_id','channel','token']" in html


async def test_console_has_permission_gated_media_and_sound_tabs():
    from pathlib import Path

    html = Path("templates/moderator_console.html").read_text(encoding="utf-8")
    js = Path("static/moderator-console.js").read_text(encoding="utf-8")
    assert 'data-mc-tab="media"' in html and 'data-mc-tab="sounds"' in html
    assert "permissions.includes('play_media')" in js
    assert "permissions.includes('play_sound')" in js
    assert "/api/moderator-media/library" in js
    assert "/api/moderator-console/sounds/play" in js
    assert "/api/moderator-console/sounds/stop" in js
    assert 'data-mc-stop="sounds"' in html


async def test_owner_sound_obs_token_ui_has_three_locales():
    from pathlib import Path

    # Q16 F4 (DEC-OWNER-016): консоль модератора звука переехала из Настроек
    # в карточку бота-модератора (botTab-moderation).
    template = Path("templates/partials/bots.html").read_text(encoding="utf-8")
    script = Path("static/app/04_chat_settings.js").read_text(encoding="utf-8")
    i18n = Path("static/app.js").read_text(encoding="utf-8")
    assert "rotateModeratorSoundObsToken()" in template
    assert "async function rotateModeratorSoundObsToken()" in script
    assert "/obs-token" in script
    for key in (
        "settings.mod_sound_obs", "settings.mod_sound_obs_configured",
        "settings.mod_sound_obs_missing",
    ):
        assert i18n.count(f"'{key}'") == 3
