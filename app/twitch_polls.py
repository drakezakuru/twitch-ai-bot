"""WIDGETS_PLAN v2 (решение владельца 28.08.2026): нативные Twitch Polls.

Интеграция с Helix API (`/helix/polls`) для poll-overlay виджета:
    * ``get_active_poll``   — активное голосование канала (кэш 3с);
    * ``create_poll``       — создать голосование (channel:manage:polls);
    * ``end_poll``          — принудительно завершить.

Токен берётся аккаунтный (как у Stream Vision / Helix-хелперов), поэтому у
приложения Twitch должны быть скоупы ``channel:read:polls`` /
``channel:manage:polls``. Перед каждым вызовом Helix токен проверяется как
токен самого broadcaster'а выбранного exact account/channel scope.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_POLL_CACHE: dict[tuple[int, str], tuple[float, dict | None]] = {}
_POLL_CACHE_TTL = 3.0  # сек — Helix-лимиты щадим


def _helix_headers(token: str) -> dict:
    from app.twitch_helix import _client_id, _strip_oauth
    return {"Authorization": f"Bearer {_strip_oauth(token)}",
            "Client-Id": _client_id()}


def _normalize_channel(channel: str) -> str:
    return str(channel or "").strip().lower().lstrip("#")


async def _broadcaster_and_headers(
    account_id: int, channel: str, required_scopes: set[str],
) -> tuple[str | None, dict | None, str | None, str]:
    """Authorize the exact DB scope and broadcaster-owned user token.

    A bot token may be allowed in a channel but cannot create or end its
    broadcaster's poll. Do not resolve a user ID through Helix before the
    local scope, identity, and OAuth-scope checks have all passed.
    """
    channel = _normalize_channel(channel)
    if not account_id or not channel:
        return None, None, None, "account_and_channel_required"

    from app.database import get_db
    db = await get_db()
    try:
        account = await (await db.execute(
            "SELECT enabled FROM accounts WHERE id = ?", (account_id,),
        )).fetchone()
        if not account:
            return None, None, None, "account_not_found"
        if not account["enabled"]:
            return None, None, None, "account_disabled"
        channel_row = await (await db.execute(
            "SELECT 1 FROM channels WHERE account_id = ? AND enabled = 1 "
            "AND lower(ltrim(trim(channel_name), '#')) = ?",
            (account_id, channel),
        )).fetchone()
        if not channel_row:
            return None, None, None, "account_channel_mismatch"
    finally:
        await db.close()

    token = await _account_token(account_id)
    if not token:
        return None, None, None, "no_token"

    from app.twitch_helix import _client_id, validate_token
    if not _client_id():
        return None, None, None, "helix_not_configured"
    identity = await validate_token(token)
    if not identity:
        return None, None, None, "invalid_token"
    if str(identity.get("login") or "").strip().lower() != channel:
        return None, None, None, "broadcaster_token_required"
    broadcaster_id = str(identity.get("user_id") or "").strip()
    if not broadcaster_id:
        return None, None, None, "invalid_token"
    if not required_scopes.issubset(set(identity.get("scopes") or [])):
        return None, None, None, "missing_scope"
    return broadcaster_id, _helix_headers(token), token, ""


async def _account_token(account_id: int) -> str | None:
    """Аккаунтный user-token (тот же паттерн, что Stream Vision в server.py)."""
    try:
        from app import chat_analyzer as ca
        getter = getattr(ca, "_account_token", None)
        if getter is not None:
            if hasattr(getter, "get"):
                return getter.get(account_id)
            res = getter(account_id)
            return await res if hasattr(res, "__await__") else res
    except Exception as exc:
        logger.debug("[twitch-polls] token lookup failed: %s", exc)
    return None


def _normalize_poll(data: dict) -> dict:
    return {
        "id": data.get("id"),
        "title": data.get("title", ""),
        "status": data.get("status", ""),
        "duration": data.get("duration_seconds", 0),
        "started_at": data.get("started_at", ""),
        "choices": [
            {"title": ch.get("title", ""), "votes": int(ch.get("votes") or 0)}
            for ch in (data.get("choices") or [])
        ],
    }


async def get_active_poll(account_id: int, channel: str, force: bool = False) -> dict | None:
    """Активное голосование exact account/channel или None; кэш 3 секунды."""
    key = (int(account_id or 0), _normalize_channel(channel))
    now = time.time()
    try:
        broadcaster_id, headers, _, error = await _broadcaster_and_headers(
            account_id, channel, {"channel:read:polls"},
        )
    except Exception as exc:
        logger.debug("[twitch-polls] active poll authorization failed: %s", exc)
        return None
    if not broadcaster_id or not headers:
        if error:
            logger.debug("[twitch-polls] active poll authorization failed: %s", error)
        return None
    if not force:
        cached = _POLL_CACHE.get(key)
        if cached and (now - cached[0]) < _POLL_CACHE_TTL:
            return cached[1]
    import httpx
    from app.twitch_helix import HELIX_BASE
    poll = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{HELIX_BASE}/polls",
                params={"broadcaster_id": broadcaster_id, "first": 1},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json().get("data") or []
                active = next((item for item in data if item.get("status") == "ACTIVE"), None)
                if active:
                    poll = _normalize_poll(active)
            else:
                logger.debug("[twitch-polls] active poll request failed: %s", resp.status_code)
    except Exception as exc:
        logger.debug("[twitch-polls] get_active_poll failed: %s", exc)
    _POLL_CACHE[key] = (now, poll)
    return poll


async def create_poll(
    account_id: int, channel: str, title: str, choices: list[str],
    duration_seconds: int = 120,
) -> dict:
    """Создать голосование. Требует скоуп channel:manage:polls."""
    import httpx
    from app.twitch_helix import HELIX_BASE
    title = (title or "").strip()[:60]
    choices = [str(c).strip()[:25] for c in (choices or []) if str(c).strip()]
    if not title or len(choices) < 2:
        return {"error": "title_and_2_choices_required"}
    if len(choices) > 5:
        choices = choices[:5]
    duration_seconds = max(15, min(1800, int(duration_seconds or 120)))
    broadcaster_id, headers, _, error = await _broadcaster_and_headers(
        account_id, channel, {"channel:manage:polls"},
    )
    if not broadcaster_id:
        return {"error": error}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{HELIX_BASE}/polls",
                headers=headers,
                json={
                    "broadcaster_id": broadcaster_id,
                    "title": title,
                    "choices": [{"title": c} for c in choices],
                    "duration_seconds": duration_seconds,
                },
            )
            if resp.status_code == 200:
                data = resp.json().get("data") or [{}]
                _POLL_CACHE.pop((account_id, _normalize_channel(channel)), None)
                return {"ok": True, "poll": _normalize_poll(data[0])}
            detail = ""
            try:
                detail = resp.json().get("message", "")
            except Exception:
                pass
            if resp.status_code == 401:
                return {"error": "invalid_token"}
            if resp.status_code == 403:
                return {"error": "helix_forbidden"}
            if resp.status_code == 429:
                return {"error": "rate_limited"}
            return {"error": f"helix_{resp.status_code}", "detail": detail[:200]}
    except Exception as exc:
        return {"error": f"request_failed: {exc}"}


async def end_poll(account_id: int, channel: str) -> dict:
    """Досрочное завершение активного голосования."""
    import httpx
    from app.twitch_helix import HELIX_BASE
    broadcaster_id, headers, _, error = await _broadcaster_and_headers(
        account_id, channel, {"channel:read:polls", "channel:manage:polls"},
    )
    if not broadcaster_id:
        return {"error": error}
    poll = await get_active_poll(account_id, channel, force=True)
    if not poll or not poll.get("id"):
        return {"error": "no_active_poll"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                f"{HELIX_BASE}/polls",
                headers=headers,
                json={"broadcaster_id": broadcaster_id, "id": poll["id"],
                      "status": "TERMINATED"},
            )
            if resp.status_code == 200:
                _POLL_CACHE.pop((account_id, _normalize_channel(channel)), None)
                data = resp.json().get("data") or []
                return {"ok": True, "poll": _normalize_poll(data[0]) if data else None}
            if resp.status_code == 401:
                return {"error": "invalid_token"}
            if resp.status_code == 403:
                return {"error": "helix_forbidden"}
            if resp.status_code == 429:
                return {"error": "rate_limited"}
            return {"error": f"helix_{resp.status_code}"}
    except Exception as exc:
        return {"error": f"request_failed: {exc}"}
