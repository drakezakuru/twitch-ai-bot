"""Helix API клиент: refresh-токенов, информация о канале, валидация.

Используется для:
  - Feature 2: авто-обновление OAuth-токенов до истечения
  - Feature 3: получение user_id для подписок EventSub
  - Feature 4: текущая игра/название стрима в AI-промпте

Client ID / Secret берутся из ``app.twitch_credentials`` — сначала значения,
заданные в UI настроек (хранятся в таблице ``settings``), потом переменные
окружения. Если ничего не задано — Helix-фичи работают как no-op.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app import twitch_credentials

logger = logging.getLogger(__name__)

HELIX_BASE = "https://api.twitch.tv/helix"
OAUTH_BASE = "https://id.twitch.tv/oauth2"

_user_id_cache: dict[str, str] = {}
_channel_info_cache: dict[str, tuple[float, dict]] = {}
_CHANNEL_TTL = 60.0  # секунд


def is_helix_configured() -> bool:
    return twitch_credentials.is_helix_configured()


def _client_id() -> str:
    return twitch_credentials.get_client_id()


def _client_secret() -> str:
    return twitch_credentials.get_client_secret()


def _strip_oauth(token: str) -> str:
    return token[len("oauth:"):] if token.startswith("oauth:") else token


async def validate_token(token: str) -> dict | None:
    """Проверяет токен через /oauth2/validate. Возвращает {login, user_id, expires_in, scopes}."""
    bare = _strip_oauth(token)
    if not bare:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OAUTH_BASE}/validate", headers={"Authorization": f"OAuth {bare}"})
            if resp.status_code == 200:
                return resp.json()
            return None
    except Exception as exc:
        logger.warning("Validate token error: %s", exc)
        return None


async def validate_oauth_token_status(token: str) -> dict:
    """Validate an access token without conflating provider failures with expiry."""
    bare = _strip_oauth(token)
    if not bare:
        return {"status": "unknown"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OAUTH_BASE}/validate", headers={"Authorization": f"OAuth {bare}"})
        if resp.status_code == 200:
            data = resp.json()
            return {"status": "valid", "expires_in": int(data.get("expires_in", 0) or 0)}
        if resp.status_code == 401:
            return {"status": "expired"}
        logger.warning("Validate token returned HTTP %d", resp.status_code)
        return {"status": "unknown"}
    except Exception as exc:
        logger.warning("Validate token status error: %s", exc)
        return {"status": "unknown"}


async def refresh_oauth_token(refresh_token: str) -> dict | None:
    """Обновляет токен. Возвращает dict с access_token / refresh_token / expires_in или None."""
    if not is_helix_configured() or not refresh_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{OAUTH_BASE}/token",
                data={
                    "client_id": _client_id(),
                    "client_secret": _client_secret(),
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            if resp.status_code != 200:
                logger.warning("Refresh failed (%d): %s", resp.status_code, resp.text[:200])
                return None
            return resp.json()
    except Exception as exc:
        logger.error("Refresh exception: %s", exc)
        return None


async def get_user_id(login: str, token: str) -> str | None:
    """Получает Twitch user_id по логину (с кэшем)."""
    login = login.lower().strip()
    if login in _user_id_cache:
        return _user_id_cache[login]
    if not is_helix_configured():
        return None
    bare = _strip_oauth(token)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{HELIX_BASE}/users",
                params={"login": login},
                headers={"Authorization": f"Bearer {bare}", "Client-Id": _client_id()},
            )
            if resp.status_code != 200:
                return None
            data = resp.json().get("data", [])
            if not data:
                return None
            uid = data[0]["id"]
            _user_id_cache[login] = uid
            return uid
    except Exception as exc:
        logger.warning("get_user_id error: %s", exc)
        return None


async def get_channel_role_logins(token: str, channel: str, role: str) -> tuple[list[str], str]:
    """Return broadcaster-managed moderator or VIP logins without exposing OAuth details."""
    if role not in {"moderators", "vips"}:
        return [], "unsupported_role"
    if not _client_id():
        return [], "helix_not_configured"
    bare = _strip_oauth(token)
    validation = await validate_token(bare)
    if not validation:
        return [], "invalid_token_or_channel"
    normalized_channel = channel.strip().lower().lstrip("#")
    if str(validation.get("login") or "").lower() != normalized_channel:
        return [], "broadcaster_token_required"
    broadcaster_id = str(validation.get("user_id") or "")
    if not broadcaster_id:
        return [], "invalid_token_or_channel"

    required_scope = "moderation:read" if role == "moderators" else "channel:read:vips"
    if required_scope not in set(validation.get("scopes") or []):
        return [], "missing_scope"

    path = "/moderation/moderators" if role == "moderators" else "/channels/vips"
    headers = {"Authorization": f"Bearer {bare}", "Client-Id": _client_id()}
    params: dict[str, Any] = {"broadcaster_id": broadcaster_id, "first": 100}
    logins: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            while len(logins) < 500:
                response = await client.get(f"{HELIX_BASE}{path}", params=params, headers=headers)
                if response.status_code != 200:
                    return [], f"helix_{response.status_code}"
                payload = response.json()
                logins.extend(
                    str(item.get("user_login") or "").strip().lower()
                    for item in payload.get("data", [])
                    if item.get("user_login")
                )
                cursor = (payload.get("pagination") or {}).get("cursor")
                if not cursor:
                    break
                params["after"] = cursor
    except Exception as exc:
        logger.warning("get_channel_role_logins error: %s", exc)
        return [], "request_failed"
    return logins[:500], ""


async def get_channel_info(channel: str, token: str) -> dict | None:
    """Возвращает {title, game_name, broadcaster_language, viewer_count, is_live}.
    Кэшируется на 60 секунд.
    """
    channel = channel.lower().strip().lstrip("#")
    now = time.time()
    cached = _channel_info_cache.get(channel)
    if cached and (now - cached[0]) < _CHANNEL_TTL:
        return cached[1]
    if not is_helix_configured():
        return None
    bare = _strip_oauth(token)
    try:
        broadcaster_id = await get_user_id(channel, token)
        if not broadcaster_id:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {bare}", "Client-Id": _client_id()}
            ch_resp = await client.get(
                f"{HELIX_BASE}/channels",
                params={"broadcaster_id": broadcaster_id},
                headers=headers,
            )
            stream_resp = await client.get(
                f"{HELIX_BASE}/streams",
                params={"user_id": broadcaster_id},
                headers=headers,
            )

            info: dict[str, Any] = {"channel": channel, "is_live": False}
            if ch_resp.status_code == 200:
                ch_data = ch_resp.json().get("data", [])
                if ch_data:
                    info["title"] = ch_data[0].get("title", "")
                    info["game_name"] = ch_data[0].get("game_name", "")
                    info["broadcaster_language"] = ch_data[0].get("broadcaster_language", "")
            if stream_resp.status_code == 200:
                stream_data = stream_resp.json().get("data", [])
                if stream_data:
                    info["is_live"] = True
                    info["viewer_count"] = stream_data[0].get("viewer_count", 0)
                    info["started_at"] = stream_data[0].get("started_at", "")
            _channel_info_cache[channel] = (now, info)
            return info
    except Exception as exc:
        logger.warning("get_channel_info error: %s", exc)
        return None


def format_channel_context(info: dict) -> str:
    """Форматирует инфу о канале для system-prompt."""
    if not info:
        return ""
    parts = []
    if info.get("game_name"):
        parts.append(f"играет в '{info['game_name']}'")
    if info.get("title"):
        parts.append(f"название стрима: '{info['title']}'")
    if info.get("is_live"):
        if info.get("viewer_count"):
            parts.append(f"{info['viewer_count']} зрителей онлайн")
    else:
        parts.append("стрим оффлайн")
    if not parts:
        return ""
    return f"Контекст канала #{info.get('channel', '')}: " + ", ".join(parts) + "."


BAN_SCOPE = "moderator:manage:banned_users"
BAN_MIN_DURATION = 1
BAN_MAX_DURATION = 1209600  # 2 недели — потолок Twitch для таймаута


async def _resolve_ban_ids(
    token: str, channel: str, moderator_login: str, username: str
) -> tuple[str | None, str | None, str | None, str]:
    """Общая подготовка IDs для /moderation/bans. Возвращает (broadcaster, moderator, target, error)."""
    bare = _strip_oauth(token)
    if not bare:
        return None, None, None, "no_token"
    broadcaster_id = await get_user_id(channel, token)
    if not broadcaster_id:
        return None, None, None, "broadcaster_not_found"
    moderator_id = await get_user_id(moderator_login, token) if moderator_login else None
    if not moderator_id:
        return None, None, None, "moderator_not_found"
    target_id = await get_user_id(username, token)
    if not target_id:
        return None, None, None, "target_not_found"
    return broadcaster_id, moderator_id, target_id, ""


async def _post_ban(
    token: str,
    channel: str,
    moderator_login: str,
    username: str,
    *,
    duration_sec: int | None,
    reason: str = "",
) -> tuple[bool, str]:
    """POST /moderation/bans: с `duration` — таймаут, без `duration` — бан навсегда."""
    if not is_helix_configured():
        return False, "helix_not_configured"
    if duration_sec is not None and not (BAN_MIN_DURATION <= int(duration_sec) <= BAN_MAX_DURATION):
        return False, f"duration_out_of_range:{duration_sec}"
    broadcaster_id, moderator_id, target_id, err = await _resolve_ban_ids(
        token, channel, moderator_login, username
    )
    if err:
        return False, err
    data: dict = {"user_id": target_id, "reason": reason[:500]}
    if duration_sec is not None:
        data["duration"] = int(duration_sec)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{HELIX_BASE}/moderation/bans",
                params={"broadcaster_id": broadcaster_id, "moderator_id": moderator_id},
                headers={"Authorization": f"Bearer {_strip_oauth(token)}", "Client-Id": _client_id()},
                json={"data": data},
            )
            if resp.status_code in (200, 201):
                return True, ""
            return False, f"helix_{resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        logger.warning("moderation ban request error: %s", exc)
        return False, f"exception: {exc}"


async def timeout_user(
    token: str,
    channel: str,
    moderator_login: str,
    username: str,
    duration_sec: int = 600,
    reason: str = "",
) -> tuple[bool, str]:
    """MODERATION_PLAN §3.4: таймаут зрителя через POST /moderation/bans.

    Требует: TWITCH_CLIENT_ID/SECRET, токен бота со скоупом
    moderator:manage:banned_users и права модератора у бота на канале.
    Возвращает (ok, error) — error '' при успехе.
    """
    try:
        return await _post_ban(
            token, channel, moderator_login, username, duration_sec=duration_sec, reason=reason
        )
    except Exception as exc:
        logger.warning("timeout_user error: %s", exc)
        return False, f"exception: {exc}"


async def ban_user(
    token: str,
    channel: str,
    moderator_login: str,
    username: str,
    reason: str = "",
) -> tuple[bool, str]:
    """Q01: бан навсегда — тот же POST /moderation/bans, но без поля `duration`.

    Скоуп тот же, что у таймаута: moderator:manage:banned_users (`DEC-OWNER-015`).
    Helix при бане возвращает `end_time: null`. Ошибки, которые может вернуть Twitch:
    400 «user is already banned», 401 (moderator_id ≠ владелец токена),
    403 (moderator_id не модератор канала), 409 (конфликт — повторить запрос),
    429 (лимит на канал в минуту).
    """
    return await _post_ban(token, channel, moderator_login, username, duration_sec=None, reason=reason)


async def unban_user(
    token: str,
    channel: str,
    moderator_login: str,
    username: str,
) -> tuple[bool, str]:
    """Q26: снять бан/таймаут — DELETE /moderation/bans (официальный «Unban User»).

    Все три ID передаются query-параметрами, тела нет. Успех = 204 No Content.
    400 «user is not banned» возвращается как (False, "user_not_banned") — UI трактует
    это как «уже не забанен», а не как сбой.
    """
    if not is_helix_configured():
        return False, "helix_not_configured"
    broadcaster_id, moderator_id, target_id, err = await _resolve_ban_ids(
        token, channel, moderator_login, username
    )
    if err:
        return False, err
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(
                "DELETE",
                f"{HELIX_BASE}/moderation/bans",
                params={
                    "broadcaster_id": broadcaster_id,
                    "moderator_id": moderator_id,
                    "user_id": target_id,
                },
                headers={"Authorization": f"Bearer {_strip_oauth(token)}", "Client-Id": _client_id()},
            )
            if resp.status_code == 204:
                return True, ""
            if resp.status_code == 400 and "not banned" in resp.text.lower():
                return False, "user_not_banned"
            return False, f"helix_{resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        logger.warning("unban_user error: %s", exc)
        return False, f"exception: {exc}"


async def update_chat_settings(
    token: str,
    channel: str,
    moderator_login: str,
    *,
    slow_mode: bool | None = None,
    slow_mode_wait_time: int | None = None,
    emote_mode: bool | None = None,
    unique_chat_mode: bool | None = None,
    follower_mode: bool | None = None,
    follower_mode_duration: int | None = None,
) -> tuple[bool, str]:
    """PLAN_SESSION_ROLES §R5: режимы чата через PATCH /chat_settings.

    slow_mode / emote / unique / follower — вкл/выкл; None = не менять.
    Возвращает (ok, error).
    """
    if not is_helix_configured():
        return False, "helix_not_configured"
    bare = _strip_oauth(token)
    if not bare:
        return False, "no_token"
    broadcaster_id = await get_user_id(channel.lower().strip().lstrip("#"), token)
    if not broadcaster_id:
        return False, "broadcaster_not_found"
    moderator_id = await get_user_id(moderator_login, token) if moderator_login else None
    if not moderator_id:
        return False, "moderator_not_found"
    body: dict = {}
    if slow_mode is not None:
        body["slow_mode"] = bool(slow_mode)
    if slow_mode_wait_time is not None:
        body["slow_mode_wait_time"] = max(1, min(1800, int(slow_mode_wait_time)))
    if emote_mode is not None:
        body["emote_mode"] = bool(emote_mode)
    if unique_chat_mode is not None:
        body["unique_chat_mode"] = bool(unique_chat_mode)
    if follower_mode is not None:
        body["follower_mode"] = bool(follower_mode)
    if follower_mode_duration is not None:
        body["follower_mode_duration"] = max(0, min(129600, int(follower_mode_duration)))
    if not body:
        return False, "nothing_to_update"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                f"{HELIX_BASE}/chat/settings",
                params={"broadcaster_id": broadcaster_id, "moderator_id": moderator_id},
                headers={"Authorization": f"Bearer {bare}", "Client-Id": _client_id()},
                json=body,
            )
            if resp.status_code == 200:
                return True, ""
            return False, f"helix_{resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        logger.warning("update_chat_settings error: %s", exc)
        return False, f"exception: {exc}"


async def clear_chat_messages(token: str, channel: str, moderator_login: str) -> tuple[bool, str]:
    """PLAN_SESSION_ROLES §R5: «очистить чат» — DELETE /moderation/chat."""
    if not is_helix_configured():
        return False, "helix_not_configured"
    bare = _strip_oauth(token)
    if not bare:
        return False, "no_token"
    broadcaster_id = await get_user_id(channel.lower().strip().lstrip("#"), token)
    if not broadcaster_id:
        return False, "broadcaster_not_found"
    moderator_id = await get_user_id(moderator_login, token) if moderator_login else None
    if not moderator_id:
        return False, "moderator_not_found"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{HELIX_BASE}/moderation/chat",
                params={"broadcaster_id": broadcaster_id, "moderator_id": moderator_id},
                headers={"Authorization": f"Bearer {bare}", "Client-Id": _client_id()},
            )
            if resp.status_code == 204:
                return True, ""
            return False, f"helix_{resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        logger.warning("clear_chat error: %s", exc)
        return False, f"exception: {exc}"
