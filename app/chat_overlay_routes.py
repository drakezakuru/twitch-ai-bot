"""Settings and public data for chat-message OBS overlays."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.database import get_db, get_setting, set_setting
from app.security import auth_dependency, decrypt_token


admin_router = APIRouter(dependencies=[Depends(auth_dependency)])
public_router = APIRouter()

_LOGIN_RE = re.compile(r"^[a-z0-9_]{1,25}$")
_TRUSTED_KEY = "chat_overlay_trusted_users"
_DISPLAY_KEY_PREFIX = "chat_overlay_display_"

CHAT_DISPLAY_DEFAULTS: dict[str, dict[str, Any]] = {
    "selected-chat": {
        "max_messages": 8,
        "lifetime_sec": 30,
        "font_size": 24,
        "emote_size": 32,
        "show_badges": 1,
        "history_limit": 8,
        "history_minutes": 30,
    },
}


def normalize_login(value: Any) -> str:
    login = str(value or "").strip().lower().lstrip("@#")
    return login if _LOGIN_RE.fullmatch(login) else ""


def normalize_trusted_users(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({login for value in values if (login := normalize_login(value))})[:500]


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def normalize_display_settings(slug: str, values: Any) -> dict[str, Any]:
    defaults = CHAT_DISPLAY_DEFAULTS.get(slug)
    if defaults is None:
        raise KeyError(slug)
    source = values if isinstance(values, dict) else {}
    return {
        "max_messages": _bounded_int(source.get("max_messages"), defaults["max_messages"], 1, 50),
        "lifetime_sec": _bounded_int(source.get("lifetime_sec"), defaults["lifetime_sec"], 0, 300),
        "font_size": _bounded_int(source.get("font_size"), defaults["font_size"], 10, 72),
        "emote_size": _bounded_int(source.get("emote_size"), defaults["emote_size"], 12, 128),
        "show_badges": 1 if source.get("show_badges", defaults["show_badges"]) in (1, True, "1", "true") else 0,
        "history_limit": _bounded_int(source.get("history_limit"), defaults["history_limit"], 0, 50),
        "history_minutes": _bounded_int(source.get("history_minutes"), defaults["history_minutes"], 1, 1440),
    }


async def get_trusted_users() -> list[str]:
    raw = await get_setting(_TRUSTED_KEY, "[]")
    try:
        return normalize_trusted_users(json.loads(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


async def is_trusted_author(author: str) -> bool:
    login = normalize_login(author)
    return bool(login and login in set(await get_trusted_users()))


async def chat_event_payload(
    *, account_id: int, channel: str, author: str, message: str, is_bot: bool,
    badges: list[str] | None = None, message_id: str = "",
) -> dict[str, Any]:
    """Build the compatibility chat event with overlay-safe metadata."""
    return {
        "type": "chat",
        "account_id": account_id,
        "channel": channel,
        "author": author,
        "message": message,
        "is_bot": is_bot,
        "trusted": await is_trusted_author(author),
        "badges": [str(item)[:24] for item in (badges or [])[:5]],
        "message_id": str(message_id or "")[:128],
    }


async def get_display_settings(slug: str) -> dict[str, Any]:
    if slug not in CHAT_DISPLAY_DEFAULTS:
        raise KeyError(slug)
    raw = await get_setting(_DISPLAY_KEY_PREFIX + slug, "{}")
    try:
        values = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        values = {}
    return normalize_display_settings(slug, values)


@admin_router.get("/api/widgets/chat/trusted-users")
async def trusted_users_get() -> dict[str, Any]:
    return {"users": await get_trusted_users()}


@admin_router.put("/api/widgets/chat/trusted-users")
async def trusted_users_put(data: dict[str, Any]) -> dict[str, Any]:
    users = normalize_trusted_users(data.get("users"))
    await set_setting(_TRUSTED_KEY, json.dumps(users, ensure_ascii=False))
    return {"ok": True, "users": users}


@admin_router.post("/api/widgets/chat/trusted-users/import")
async def trusted_users_import(data: dict[str, Any]) -> dict[str, Any]:
    role = str(data.get("role") or "")
    if role not in {"moderators", "vips"}:
        raise HTTPException(status_code=400, detail="unsupported_role")
    account_id = _bounded_int(data.get("account_id"), 0, 0, 2_147_483_647)
    channel = str(data.get("channel") or "").strip().lower().lstrip("#")
    if not account_id or not normalize_login(channel):
        raise HTTPException(status_code=400, detail="account_and_channel_required")

    db = await get_db()
    try:
        cursor = await db.execute("SELECT token FROM accounts WHERE id = ?", (account_id,))
        row = await cursor.fetchone()
        channel_cursor = await db.execute(
            "SELECT 1 FROM channels WHERE account_id = ? AND LOWER(LTRIM(channel_name, '#')) = ?",
            (account_id, channel),
        )
        channel_exists = await channel_cursor.fetchone()
    finally:
        await db.close()
    if not row or not channel_exists:
        raise HTTPException(status_code=404, detail="account_or_channel_not_found")

    from app.twitch_helix import get_channel_role_logins

    imported, error = await get_channel_role_logins(decrypt_token(row["token"] or ""), channel, role)
    if error:
        raise HTTPException(status_code=400, detail=error)
    existing = await get_trusted_users()
    normalized_imported = set(normalize_trusted_users(imported))
    users = normalize_trusted_users([*existing, *normalized_imported])
    await set_setting(_TRUSTED_KEY, json.dumps(users, ensure_ascii=False))
    return {"ok": True, "users": users, "imported": len(normalized_imported - set(existing))}


@admin_router.get("/api/widgets/chat/display/{slug}")
async def display_settings_get(slug: str) -> dict[str, Any]:
    try:
        return {"settings": await get_display_settings(slug)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown_chat_widget") from exc


@admin_router.put("/api/widgets/chat/display/{slug}")
async def display_settings_put(slug: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        settings = normalize_display_settings(slug, data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown_chat_widget") from exc
    await set_setting(_DISPLAY_KEY_PREFIX + slug, json.dumps(settings, ensure_ascii=False))
    return {"ok": True, "settings": settings}


@public_router.get("/api/widgets/public/chat/display/{slug}")
async def display_settings_public(slug: str) -> dict[str, Any]:
    try:
        return {"settings": await get_display_settings(slug)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown_chat_widget") from exc


@public_router.get("/api/widgets/public/chat/selected-history")
async def selected_chat_history(
    account_id: int = 0,
    channel: str = "",
    limit: int = 8,
    minutes: int = 30,
) -> dict[str, Any]:
    users = await get_trusted_users()
    if not users:
        return {"messages": []}
    safe_limit = max(1, min(50, int(limit)))
    safe_minutes = max(1, min(1440, int(minutes)))
    normalized_channel = str(channel or "").strip().lower().lstrip("#")
    where = [f"LOWER(author) IN ({','.join('?' for _ in users)})", "timestamp >= datetime('now', ?)"]
    params: list[Any] = [*users, f"-{safe_minutes} minutes"]
    if account_id > 0:
        where.append("account_id = ?")
        params.append(account_id)
    if normalized_channel:
        where.append("LOWER(LTRIM(channel, '#')) = ?")
        params.append(normalized_channel)
    params.append(min(safe_limit * 4, 200))
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT account_id, channel, author, message, is_bot, timestamp "
            f"FROM chat_log WHERE {' AND '.join(where)} ORDER BY timestamp DESC, id DESC LIMIT ?",
            tuple(params),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    messages: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (str(row["channel"]).lower(), str(row["author"]).lower(), row["message"], row["timestamp"])
        if key in seen:
            continue
        seen.add(key)
        messages.append({
            "account_id": row["account_id"],
            "channel": row["channel"],
            "author": row["author"],
            "message": row["message"],
            "is_bot": bool(row["is_bot"]),
            "timestamp": row["timestamp"],
            "trusted": True,
        })
        if len(messages) >= safe_limit:
            break
    messages.reverse()
    return {"messages": messages}


@public_router.get("/widget/selected-chat", response_class=HTMLResponse)
async def selected_chat_widget() -> str:
    from app.widgets import _widget_html

    return _widget_html("selected-chat")


__all__ = [
    "CHAT_DISPLAY_DEFAULTS",
    "admin_router",
    "chat_event_payload",
    "get_display_settings",
    "get_trusted_users",
    "is_trusted_author",
    "normalize_display_settings",
    "normalize_login",
    "normalize_trusted_users",
    "public_router",
]
