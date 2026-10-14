"""Twitch Device Code Flow.

Позволяет добавлять аккаунты без ручной вставки OAuth-токена.
Юзер открывает twitch.tv/activate, вводит 6-значный код — панель сама получает токены.

Требуется Twitch Client ID. Его можно задать прямо в UI на вкладке
«Настройки» (предпочтительный способ) либо через переменную окружения
``TWITCH_CLIENT_ID`` в ``.env``. TWITCH_CLIENT_SECRET для device flow НЕ нужен.
"""
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

from app import twitch_credentials

DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"

# Скоупы по умолчанию: чат + основные события.
# chat:read/chat:edit — IRC; bits:read — cheers; channel:read:subscriptions — подписки;
# moderator:read:followers — фоллы (нужен mod на канале); moderation:read и
# channel:read:vips — импорт доверенных пользователей для выбранного чата;
# moderator:manage:banned_users — бан и таймаут через POST /helix/moderation/bans
# (DEC-OWNER-015; без него Helix отвечает 401/403). Существующие токены получают скоуп
# только после переавторизации — это шаг владельца, панель показывает честный статус прав.
DEFAULT_SCOPES = [
    "chat:read",
    "chat:edit",
    "bits:read",
    "channel:read:subscriptions",
    "moderator:read:followers",
    "moderation:read",
    "channel:read:vips",
    "user:read:chat",
    "user:write:chat",
    "moderator:manage:banned_users",
]


def get_client_id() -> Optional[str]:
    cid = twitch_credentials.get_client_id()
    return cid or None


def is_configured() -> bool:
    return bool(get_client_id())


async def start_device_flow(scopes: Optional[list] = None) -> dict:
    """Запросить device_code и user_code у Twitch.

    Возвращает: {device_code, user_code, verification_uri, expires_in, interval}
    """
    client_id = get_client_id()
    if not client_id:
        return {"ok": False, "error": "TWITCH_CLIENT_ID не задан в .env"}

    scopes = DEFAULT_SCOPES if scopes is None else scopes
    body = {
        "client_id": client_id,
        # ВАЖНО: Twitch ждёт `scopes`, а не `scope` (отличие от RFC 8628).
        "scopes": " ".join(scopes),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                DEVICE_URL,
                data=urlencode(body),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if r.status_code != 200:
            return {"ok": False, "error": f"Twitch вернул {r.status_code}: {r.text[:200]}"}
        data = r.json()
        return {
            "ok": True,
            "device_code": data.get("device_code"),
            "user_code": data.get("user_code"),
            "verification_uri": data.get("verification_uri", "https://www.twitch.tv/activate"),
            "expires_in": data.get("expires_in", 1800),
            "interval": max(int(data.get("interval", 5)), 1),
            "scopes": scopes,
        }
    except Exception as e:
        return {"ok": False, "error": f"network error: {e}"}


async def poll_device_token(device_code: str) -> dict:
    """Один запрос проверки: получил ли юзер токен.

    Возвращает один из:
      {ok: True, access_token, refresh_token, expires_in, scope}
      {ok: False, pending: True}                         — ждать ещё
      {ok: False, slow_down: True}                       — увеличить интервал
      {ok: False, expired: True}                         — device_code устарел
      {ok: False, error: "..."}                          — другая ошибка
    """
    client_id = get_client_id()
    if not client_id:
        return {"ok": False, "error": "TWITCH_CLIENT_ID не задан"}

    body = {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                TOKEN_URL,
                data=urlencode(body),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if r.status_code == 200:
            data = r.json()
            return {
                "ok": True,
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", ""),
                "expires_in": int(data.get("expires_in", 14400)),
                "scope": data.get("scope") or [],
            }
        # Ошибки device flow — идут как 400 с message в теле
        try:
            err = r.json()
            msg = (err.get("message") or err.get("error") or "").lower()
        except Exception:
            msg = r.text.lower()

        if "authorization_pending" in msg or "pending" in msg:
            return {"ok": False, "pending": True}
        if "slow_down" in msg:
            return {"ok": False, "slow_down": True}
        if "expired" in msg:
            return {"ok": False, "expired": True}
        if "access_denied" in msg or "denied" in msg:
            return {"ok": False, "denied": True}
        return {"ok": False, "error": f"twitch {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": f"network error: {e}"}


async def fetch_user_info(access_token: str) -> dict:
    """Получить login + user_id для свежего токена через /validate.

    Возвращает: {ok, login, user_id, scopes, expires_in}
    """
    client_id = get_client_id()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                VALIDATE_URL,
                headers={"Authorization": f"OAuth {access_token}"},
            )
        if r.status_code != 200:
            return {"ok": False, "error": f"validate {r.status_code}"}
        data = r.json()
        return {
            "ok": True,
            "login": data.get("login", ""),
            "user_id": data.get("user_id", ""),
            "scopes": data.get("scopes", []),
            "expires_in": int(data.get("expires_in", 0)),
            "client_id": data.get("client_id", client_id),
        }
    except Exception as e:
        return {"ok": False, "error": f"network error: {e}"}


# ============ In-memory pending sessions ============
# Хранятся, пока юзер не закончил процесс. Чистим по expires_at.

_pending: dict = {}


def remember_session(device_code: str, user_code: str, expires_in: int):
    _pending[device_code] = {
        "user_code": user_code,
        "expires_at": time.time() + expires_in,
        "created_at": time.time(),
    }


def forget_session(device_code: str):
    _pending.pop(device_code, None)


def gc_expired_sessions():
    now = time.time()
    dead = [k for k, v in _pending.items() if v["expires_at"] < now]
    for k in dead:
        _pending.pop(k, None)


def is_known_session(device_code: str) -> bool:
    return device_code in _pending
