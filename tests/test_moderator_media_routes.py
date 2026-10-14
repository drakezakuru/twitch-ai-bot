"""Focused guards for Track 6.6 moderator media isolation and OBS access."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.datastructures import UploadFile

pytestmark = pytest.mark.asyncio


async def _seed() -> None:
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.executemany("INSERT INTO accounts (id,nickname,token) VALUES (?,?,'token')", [(1, "one"), (2, "two")])
        await db.executemany("INSERT INTO channels (account_id,channel_name) VALUES (?,?)", [(1, "#Shared"), (2, "shared")])
        await db.commit()
    finally:
        await db.close()


def _png_upload() -> UploadFile:
    raw = io.BytesIO()
    Image.new("RGBA", (16, 9), "purple").save(raw, "PNG")
    return UploadFile(filename="cue.png", file=io.BytesIO(raw.getvalue()))


def _request(host: str = "127.0.0.1", *, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({"type": "http", "headers": headers or [], "client": (host, 1234)})


async def test_owner_library_is_exact_scoped_and_moderator_queue_is_idempotent(monkeypatch, tmp_path):
    from app import moderator_media_routes as media

    await _seed()
    monkeypatch.setattr(media, "MODERATOR_MEDIA_ROOT", tmp_path / "moderator-media")
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    saved = await media.add_media(1, "#SHARED", _png_upload(), "owner", True)
    assert saved["ok"] and saved["item"]["approved"]
    session = {"account_id": 1, "channel": "shared", "twitch_user_id": "42", "permissions": ["play_media"]}
    first = await media.enqueue_media(session, saved["item"]["id"], "cue-click-0001")
    second = await media.enqueue_media(session, saved["item"]["id"], "cue-click-0001")
    other_scope = {**session, "account_id": 2}
    denied = await media.enqueue_media(other_scope, saved["item"]["id"], "cue-click-0002")
    assert first == {"ok": True, "command_id": first["command_id"], "status": "queued"}
    assert second["ok"] and second["idempotent"] is True and second["command_id"] == first["command_id"]
    assert denied == {"ok": False, "error": "media_not_approved"}
    cue = (await media._state(1, "shared"))["cue"]
    assert cue["media_id"] == saved["item"]["id"] and cue["command_id"] == first["command_id"]


async def test_pending_moderator_upload_and_invalid_payload_fail_closed(monkeypatch, tmp_path):
    from app import moderator_media_routes as media

    await _seed()
    monkeypatch.setattr(media, "MODERATOR_MEDIA_ROOT", tmp_path / "moderator-media")
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    pending = await media.add_media(1, "shared", _png_upload(), "42", False)
    invalid = await media.add_media(1, "shared", UploadFile(filename="bad.html", file=io.BytesIO(b"<script>x</script>")), "owner", True)
    session = {"account_id": 1, "channel": "shared", "twitch_user_id": "42", "permissions": ["play_media"]}
    assert pending["ok"] and pending["item"]["approved"] is False
    assert await media.enqueue_media(session, pending["item"]["id"], "pending-cue-0001") == {"ok": False, "error": "media_not_approved"}
    assert invalid == {"ok": False, "error": "unsupported_media"}


async def test_obs_token_is_scoped_and_kill_switch_stops_immediately(monkeypatch):
    from app import moderator_media_routes as media
    from app.database import get_db

    await _seed()
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    db = await get_db()
    try:
        await media.ensure_schema(db)
        await db.execute("INSERT INTO moderator_media_state(account_id,channel,obs_token_hash) VALUES (?,?,?)", (1, "shared", media._hash("obs-secret")))
        await db.commit()
    finally:
        await db.close()
    assert await media._valid_obs_token(1, "shared", "obs-secret")
    assert not await media._valid_obs_token(2, "shared", "obs-secret")
    result = await media.owner_control(1, "shared", {"action": "kill_switch", "enabled": True})
    assert result["state"]["kill_switch"] is True and result["state"]["cue"] is None


async def test_protected_widget_requires_rotated_scope_token(monkeypatch):
    from app import moderator_media_routes as media

    await _seed()
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    token_result = await media.rotate_obs_token(_request(), 1, "#SHARED")
    app = FastAPI()
    app.include_router(media.public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get(
            "/widget/moderator-media",
            params={"account_id": 1, "channel": "shared", "token": "wrong"},
        )
        allowed = await client.get(token_result["url"])

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert '<meta name="color-scheme" content="dark">' in allowed.text
    assert "/api/moderator-media/public" in allowed.text


async def test_hash_only_scope_stays_valid_but_requires_explicit_rotation(monkeypatch):
    from app import moderator_media_routes as media
    from app.database import get_db

    await _seed()
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    db = await get_db()
    try:
        await media.ensure_schema(db)
        await db.execute(
            "INSERT INTO moderator_media_state(account_id,channel,obs_token_hash) VALUES (?,?,?)",
            (1, "shared", media._hash("legacy-secret")),
        )
        await db.commit()
    finally:
        await db.close()

    status = await media.obs_token_status(1, "shared")
    assert status == {
        "ok": True,
        "configured": True,
        "reveal_available": False,
        "rotation_required": True,
        "masked_token": "••••••••",
    }
    assert await media._valid_obs_token(1, "shared", "legacy-secret")
    with pytest.raises(Exception) as error:
        await media.reveal_obs_token(_request(), 1, "shared")
    assert getattr(error.value, "status_code", None) == 409


async def test_hash_only_schema_migrates_additively_without_losing_rows():
    from app import moderator_media_routes as media
    from app.database import get_db

    await _seed()
    db = await get_db()
    try:
        await db.execute("DROP TABLE moderator_media_state")
        await db.execute(
            "CREATE TABLE moderator_media_state ("
            "account_id INTEGER NOT NULL, channel TEXT NOT NULL, "
            "obs_token_hash TEXT NOT NULL DEFAULT '', kill_switch INTEGER NOT NULL DEFAULT 0, "
            "queue_policy TEXT NOT NULL DEFAULT 'queue', position_json TEXT NOT NULL DEFAULT '{}', "
            "PRIMARY KEY(account_id, channel))"
        )
        await db.execute(
            "INSERT INTO moderator_media_state(account_id,channel,obs_token_hash) VALUES (1,'shared',?)",
            (media._hash("legacy-secret"),),
        )
        await db.commit()
        await media.ensure_schema(db)
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(moderator_media_state)")).fetchall()}
        row = await (await db.execute(
            "SELECT obs_token_hash,obs_token FROM moderator_media_state WHERE account_id=1 AND channel='shared'"
        )).fetchone()
    finally:
        await db.close()

    assert "obs_token" in columns
    assert row["obs_token_hash"] == media._hash("legacy-secret")
    assert row["obs_token"] == ""


async def test_rotation_persists_raw_token_and_revokes_previous_url(monkeypatch):
    from app import moderator_media_routes as media
    from app.database import get_db

    await _seed()
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    first = await media.rotate_obs_token(_request(), 1, "shared")
    second = await media.rotate_obs_token(_request(), 1, "shared")

    assert first["token"] != second["token"]
    assert not await media._valid_obs_token(1, "shared", first["token"])
    assert await media._valid_obs_token(1, "shared", second["token"])
    revealed = await media.reveal_obs_token(_request(), 1, "shared")
    assert revealed["url"] == second["url"]
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT obs_token,obs_token_hash FROM moderator_media_state WHERE account_id=1 AND channel='shared'"
        )).fetchone()
    finally:
        await db.close()
    assert row["obs_token"] == second["token"]
    assert row["obs_token_hash"] == media._hash(second["token"])


async def test_token_secret_actions_require_loopback_owner(monkeypatch):
    from app import moderator_media_routes as media

    await _seed()
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    with pytest.raises(Exception) as rotate_error:
        await media.rotate_obs_token(_request("198.51.100.4"), 1, "shared")
    assert getattr(rotate_error.value, "status_code", None) == 403

    await media.rotate_obs_token(_request(), 1, "shared")
    with pytest.raises(Exception) as reveal_error:
        await media.reveal_obs_token(_request("198.51.100.4"), 1, "shared")
    assert getattr(reveal_error.value, "status_code", None) == 403

    same_site = _request(headers=[(b"host", b"127.0.0.1:8000"), (b"origin", b"http://127.0.0.1:8000")])
    assert (await media.rotate_obs_token(same_site, 1, "shared"))["ok"] is True
    cross_site = _request(headers=[(b"host", b"127.0.0.1:8000"), (b"origin", b"https://example.invalid")])
    with pytest.raises(Exception) as csrf_error:
        await media.rotate_obs_token(cross_site, 1, "shared")
    assert getattr(csrf_error.value, "status_code", None) == 403


async def test_safe_preview_has_no_token_or_live_public_requests():
    from app import moderator_media_routes as media

    app = FastAPI()
    app.include_router(media.admin_router)
    app.include_router(media.public_router)
    transport = ASGITransport(app=app, client=("127.0.0.1", 1234))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.get("/api/moderator-media/admin/preview")
        denied = await client.get("/widget/moderator-media", params={"account_id": 1, "channel": "shared", "token": ""})

    assert preview.status_code == 200
    assert 'data-safe-preview="true"' in preview.text
    assert "/api/moderator-media/public" not in preview.text
    assert denied.status_code == 403


async def test_panel_has_masked_preview_controls_and_three_language_strings():
    root = Path(__file__).resolve().parents[1]
    # Q16 F4 (DEC-OWNER-016): консоль модератора медиа переехала из Настроек
    # в карточку бота-модератора (botTab-moderation).
    markup = (root / "templates/partials/bots.html").read_text(encoding="utf-8")
    script = (root / "static/app/04_chat_settings.js").read_text(encoding="utf-8")
    translations = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'class="widget-preview" src="/api/moderator-media/admin/preview"' in markup
    assert 'id="modMediaObsUrl" class="input flex-1" type="password"' in markup
    assert "setTimeout(() => hideModeratorMediaToken('settings.mod_media_hidden'), 30000)" in script
    assert "modMediaRevealedUrl = ''" in script
    for key in (
        "settings.mod_media_reveal",
        "settings.mod_media_rotate_confirm",
        "settings.mod_media_rotation_required",
        "settings.mod_media_reveal_error",
        "settings.mod_media_preview",
    ):
        assert translations.count(f"'{key}':") == 3


async def test_media_favorites_and_preview_are_exact_scoped(monkeypatch, tmp_path):
    from app import moderator_media_routes as media

    await _seed()
    monkeypatch.setattr(media, "MODERATOR_MEDIA_ROOT", tmp_path / "moderator-media")
    monkeypatch.setattr(media, "_audit", lambda *_: _done())
    saved = await media.add_media(1, "shared", _png_upload(), "owner", True)
    session = {"account_id": 1, "channel": "shared", "twitch_user_id": "42", "permissions": ["play_media"]}
    await media.moderator_media_favorites({"media_ids": [saved["item"]["id"]]}, session)
    listed = await media.moderator_library(session)
    assert listed["items"][0]["favorite"] == 1
    response = await media.moderator_media_preview(saved["item"]["id"], session)
    assert str(response.path).endswith(".png")
    assert await media.moderator_library({**session, "account_id": 2}) == {"ok": True, "items": []}


async def _done() -> None:
    return None
