"""
Twitch Stream Tools routes (FastAPI).

Provides admin-only endpoints (§S5) to inspect and control a Twitch channel via
the Helix API: connection check, channel info (category/title), chat settings
(follower-only, slow mode) and OAuth scope verification.

The router is wired up in app/server.py with a single include_router call.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.twitch_helix import is_helix_configured, refresh_oauth_token
from app.twitch_credentials import load_from_db
from app.database import get_db
from app.security import auth_dependency
from app.routes import log_action
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/stream-tools",
    tags=["stream-tools"],
    dependencies=[Depends(auth_dependency)],
)

HELIX_BASE = "https://api.twitch.tv/helix"
DEV_CONSOLE_URL = "https://dev.twitch.tv/console"
HTTP_TIMEOUT = 15.0

# Scopes required for the various stream tools features.
REQUIRED_SCOPES: Dict[str, List[str]] = {
    "channel-info-read": ["channel:read:stream_key"],  # not strictly required for read
    "channel-info-write": ["channel:manage:broadcast"],
    "chat-settings-read": ["moderator:read:chat_settings"],
    "chat-settings-write": ["moderator:manage:chat_settings"],
}

# Flattened set of scopes we care about across all features.
ALL_REQUIRED_SCOPES: List[str] = sorted(
    {scope for scopes in REQUIRED_SCOPES.values() for scope in scopes}
)


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #
class ChannelInfoUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=140)
    game_id: Optional[str] = None
    game_name: Optional[str] = None
    broadcaster_language: Optional[str] = None
    tags: Optional[List[str]] = None


class ChatSettingsUpdate(BaseModel):
    emote_mode: Optional[bool] = None
    follower_mode: Optional[bool] = None
    follower_mode_duration: Optional[int] = Field(None, ge=0, le=129600)
    slow_mode: Optional[bool] = None
    slow_mode_wait_time: Optional[int] = Field(None, ge=3, le=120)
    subscriber_mode: Optional[bool] = None
    unique_chat_mode: Optional[bool] = None
    non_moderator_chat_delay: Optional[bool] = None
    non_moderator_chat_delay_duration: Optional[int] = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _not_configured_response() -> JSONResponse:
    """Standard payload when Twitch API is not configured (no Client ID)."""
    return JSONResponse(
        status_code=400,
        content={
            "ok": False,
            "error": "Twitch API не настроен",
            "reason": "no_client_id",
            "message": (
                "Не заданы Client ID/Secret для Twitch Helix API. "
                "Создайте приложение в консоли разработчика Twitch и укажите "
                "учётные данные в настройках."
            ),
            "help_url": DEV_CONSOLE_URL,
        },
    )


def _error_response(
    status_code: int,
    error: str,
    reason: str,
    *,
    message: Optional[str] = None,
    help_url: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    payload: Dict[str, Any] = {
        "ok": False,
        "error": error,
        "reason": reason,
    }
    if message:
        payload["message"] = message
    if help_url:
        payload["help_url"] = help_url
    if extra:
        payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)


async def _get_account_token(account_id: str) -> Optional[str]:
    """
    Resolve the current OAuth access token for the given account.

    Tries the in-memory chat_analyzer token cache first, then the DB.
    """
    from app.server import chat_analyzer as _ca
    token_entry = _ca._account_token.get(account_id)  # type: ignore[attr-defined]
    if isinstance(token_entry, dict):
        token = token_entry.get("access_token") or token_entry.get("token")
        if token:
            return token
    elif isinstance(token_entry, str) and token_entry:
        return token_entry

    # Fallback: try to load from DB.
    try:
        db = await get_db()
        try:
            db.row_factory = _dict_row_factory
            cursor = await db.execute(
                "SELECT access_token FROM twitch_accounts WHERE account_id = ? LIMIT 1",
                (account_id,),
            )
            row = await cursor.fetchone()
            if row and row.get("access_token"):
                return row["access_token"]
        finally:
            await db.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load token from DB for %s: %s", account_id, exc)

    return None


def _dict_row_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


async def _get_client_id() -> Optional[str]:
    try:
        creds = await load_from_db()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load Twitch credentials: %s", exc)
        return None

    if not creds:
        return None
    if isinstance(creds, dict):
        return creds.get("client_id")
    return getattr(creds, "client_id", None)


async def _helix_request(
    method: str,
    path: str,
    account_id: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    retry_on_401: bool = True,
) -> Dict[str, Any]:
    """
    Perform an authenticated Helix request.

    Returns a dict:
        {"status": int, "data": <parsed json | None>, "text": <raw text>}
    or raises no exceptions for HTTP errors (caller inspects status).
    """
    client_id = await _get_client_id()
    token = await _get_account_token(account_id)

    if not client_id or not token:
        return {"status": 0, "data": None, "text": "", "missing_auth": True}

    url = f"{HELIX_BASE}{path}"
    headers = {
        "Client-Id": client_id,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        try:
            resp = await client.request(
                method, url, headers=headers, params=params, json=json_body
            )
        except httpx.HTTPError as exc:
            # P8-A4: сеть — отдельный честный шаг (DNS/прокси/нет интернета),
            # раньше сюда прилетал неотловленный httpx.ConnectError → 500.
            logger.warning("Helix network error %s %s: %s", method, url, exc)
            return {"status": -1, "data": None, "text": f"network: {exc}"}

        # Attempt a token refresh once on 401.
        if resp.status_code == 401 and retry_on_401:
            try:
                refreshed = await refresh_oauth_token(account_id)
            except TypeError:
                # refresh_oauth_token may not take account_id in some versions.
                refreshed = await refresh_oauth_token()  # type: ignore[call-arg]
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Token refresh failed for %s: %s", account_id, exc)
                refreshed = None

            if refreshed:
                return await _helix_request(
                    method,
                    path,
                    account_id,
                    params=params,
                    json_body=json_body,
                    retry_on_401=False,
                )

        data: Optional[Any] = None
        text = resp.text
        try:
            if text:
                data = resp.json()
        except ValueError:
            data = None

        return {"status": resp.status_code, "data": data, "text": text}


async def _resolve_broadcaster(account_id: str) -> Dict[str, Any]:
    """
    Resolve broadcaster identity (user id/login) via GET /helix/users.

    Returns {"ok": True, "user": {...}} or {"ok": False, "response": JSONResponse}.
    """
    result = await _helix_request("GET", "/users", account_id)

    if result.get("missing_auth"):
        return {
            "ok": False,
            "response": _error_response(
                400,
                "Нет токена авторизации",
                "no_token",
                message="Для аккаунта не найден действующий OAuth токен Twitch.",
                help_url=DEV_CONSOLE_URL,
            ),
        }

    status = result["status"]
    if status == 200 and result["data"] and result["data"].get("data"):
        return {"ok": True, "user": result["data"]["data"][0]}

    if status == 401:
        return {
            "ok": False,
            "response": _error_response(
                401,
                "Токен недействителен или истёк",
                "invalid_token",
                message="Требуется повторная авторизация аккаунта в Twitch.",
                help_url=DEV_CONSOLE_URL,
            ),
        }

    return {
        "ok": False,
        "response": _error_response(
            502,
            "Ошибка запроса к Twitch",
            "helix_error",
            message=result.get("text") or "Не удалось получить данные пользователя.",
            extra={"twitch_status": status},
        ),
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/check-connection")
async def check_connection(
    account_id: str = Query(..., description="ID аккаунта Twitch"),
    _: Any = Depends(auth_dependency),
):
    """Проверка подключения к Twitch через GET /helix/users."""
    if not is_helix_configured():
        return _not_configured_response()

    result = await _helix_request("GET", "/users", account_id)

    if result.get("missing_auth"):
        return _error_response(
            400,
            "Нет токена авторизации",
            "no_token",
            message="Для аккаунта не найден действующий OAuth токен Twitch.",
            help_url=DEV_CONSOLE_URL,
        )

    status = result["status"]
    if status == 200 and result["data"] and result["data"].get("data"):
        user = result["data"]["data"][0]
        await log_action(
            "twitch_check",
            f"#{account_id}: ok ({user.get('login', '?')})",
        )
        return {
            "ok": True,
            "user_id": user.get("id"),
            "login": user.get("login"),
            "display_name": user.get("display_name"),
        }

    if status == -1:
        # P8-A4: сеть недоступна — не путать с 401/кредами
        await log_action("twitch_check", f"#{account_id}: network_error — {result.get('text', '')[:200]}")
        return _error_response(
            502,
            "Сеть недоступна",
            "network_error",
            message=(
                "Не удалось соединиться с api.twitch.tv — проверьте интернет/DNS/прокси "
                "и повторите. Client ID и токен тут ни при чём."
            ),
        )

    if status == 401:
        # P8-A4: различаем «неверный Client ID» и «невалидный токен» —
        # Twitch отдаёт оба как 401, но с разным message в теле.
        body_text = (result.get("text") or "").lower()
        if "client" in body_text:
            await log_action("twitch_check", f"#{account_id}: invalid_client_id")
            return _error_response(
                401,
                "Неверный Client ID приложения",
                "invalid_client_id",
                message=(
                    "Helix отклонил Client-ID — проверьте Client ID и Client Secret "
                    "в Настройках → Twitch-приложение."
                ),
                help_url=DEV_CONSOLE_URL,
            )
        await log_action("twitch_check", f"#{account_id}: invalid_token")
        return _error_response(
            401,
            "Токен недействителен или истёк",
            "invalid_token",
            message="Требуется повторная авторизация аккаунта в Twitch.",
            help_url=DEV_CONSOLE_URL,
        )

    await log_action(
        "twitch_check",
        f"#{account_id}: helix_error (status={status}) — {(result.get('text') or '')[:200]}",
    )
    return _error_response(
        502,
        "Ошибка подключения к Twitch",
        "helix_error",
        message=result.get("text") or "Не удалось выполнить запрос к Twitch.",
        extra={"twitch_status": status},
    )


@router.get("/channel-info")
async def get_channel_info(
    account_id: str = Query(...),
    _: Any = Depends(auth_dependency),
):
    """Текущая категория и название стрима (GET /helix/channels)."""
    if not is_helix_configured():
        return _not_configured_response()

    resolved = await _resolve_broadcaster(account_id)
    if not resolved["ok"]:
        return resolved["response"]

    broadcaster_id = resolved["user"]["id"]
    result = await _helix_request(
        "GET",
        "/channels",
        account_id,
        params={"broadcaster_id": broadcaster_id},
    )

    status = result["status"]
    if status == 200 and result["data"] and result["data"].get("data"):
        channel = result["data"]["data"][0]
        return {
            "ok": True,
            "broadcaster_id": channel.get("broadcaster_id"),
            "broadcaster_login": channel.get("broadcaster_login"),
            "broadcaster_name": channel.get("broadcaster_name"),
            "title": channel.get("title"),
            "game_id": channel.get("game_id"),
            "game_name": channel.get("game_name"),
            "broadcaster_language": channel.get("broadcaster_language"),
            "tags": channel.get("tags", []),
        }

    return _error_response(
        502,
        "Не удалось получить информацию о канале",
        "helix_error",
        message=result.get("text"),
        extra={"twitch_status": status},
    )


@router.put("/channel-info")
async def update_channel_info(
    account_id: str = Query(...),
    payload: ChannelInfoUpdate = Body(...),
    _: Any = Depends(auth_dependency),
):
    """Изменение категории/названия стрима (PATCH /helix/channels)."""
    if not is_helix_configured():
        return _not_configured_response()

    resolved = await _resolve_broadcaster(account_id)
    if not resolved["ok"]:
        return resolved["response"]

    broadcaster_id = resolved["user"]["id"]

    body: Dict[str, Any] = {}
    if payload.title is not None:
        body["title"] = payload.title
    if payload.game_id is not None:
        body["game_id"] = payload.game_id
    if payload.broadcaster_language is not None:
        body["broadcaster_language"] = payload.broadcaster_language
    if payload.tags is not None:
        body["tags"] = payload.tags

    # Resolve game_name -> game_id if only the name was provided.
    if not payload.game_id and payload.game_name:
        game_result = await _helix_request(
            "GET", "/games", account_id, params={"name": payload.game_name}
        )
        if (
            game_result["status"] == 200
            and game_result["data"]
            and game_result["data"].get("data")
        ):
            body["game_id"] = game_result["data"]["data"][0]["id"]
        else:
            return _error_response(
                400,
                "Категория не найдена",
                "game_not_found",
                message=f"Не удалось найти категорию '{payload.game_name}'.",
            )

    if not body:
        return _error_response(
            400,
            "Нечего обновлять",
            "empty_payload",
            message="Не переданы поля для обновления.",
        )

    result = await _helix_request(
        "PATCH",
        "/channels",
        account_id,
        params={"broadcaster_id": broadcaster_id},
        json_body=body,
    )

    status = result["status"]
    if status in (200, 204):
        return {"ok": True, "updated": body}

    if status == 401:
        return _error_response(
            401,
            "Недостаточно прав или токен истёк",
            "invalid_token",
            message="Требуется scope channel:manage:broadcast и валидный токен.",
            help_url=DEV_CONSOLE_URL,
        )

    return _error_response(
        502,
        "Не удалось обновить информацию о канале",
        "helix_error",
        message=result.get("text"),
        extra={"twitch_status": status},
    )


@router.get("/chat-settings")
async def get_chat_settings(
    account_id: str = Query(...),
    _: Any = Depends(auth_dependency),
):
    """Настройки чата (GET /helix/chat/settings)."""
    if not is_helix_configured():
        return _not_configured_response()

    resolved = await _resolve_broadcaster(account_id)
    if not resolved["ok"]:
        return resolved["response"]

    broadcaster_id = resolved["user"]["id"]
    result = await _helix_request(
        "GET",
        "/chat/settings",
        account_id,
        params={
            "broadcaster_id": broadcaster_id,
            "moderator_id": broadcaster_id,
        },
    )

    status = result["status"]
    if status == 200 and result["data"] and result["data"].get("data"):
        return {"ok": True, "settings": result["data"]["data"][0]}

    if status == 401:
        return _error_response(
            401,
            "Недостаточно прав или токен истёк",
            "invalid_token",
            message="Требуется scope moderator:read:chat_settings.",
            help_url=DEV_CONSOLE_URL,
        )

    return _error_response(
        502,
        "Не удалось получить настройки чата",
        "helix_error",
        message=result.get("text"),
        extra={"twitch_status": status},
    )


@router.put("/chat-settings")
async def update_chat_settings(
    account_id: str = Query(...),
    payload: ChatSettingsUpdate = Body(...),
    _: Any = Depends(auth_dependency),
):
    """Изменение настроек чата (PATCH /helix/chat/settings)."""
    if not is_helix_configured():
        return _not_configured_response()

    resolved = await _resolve_broadcaster(account_id)
    if not resolved["ok"]:
        return resolved["response"]

    broadcaster_id = resolved["user"]["id"]

    body = payload.model_dump(exclude_none=True)
    if not body:
        return _error_response(
            400,
            "Нечего обновлять",
            "empty_payload",
            message="Не переданы поля для обновления.",
        )

    result = await _helix_request(
        "PATCH",
        "/chat/settings",
        account_id,
        params={
            "broadcaster_id": broadcaster_id,
            "moderator_id": broadcaster_id,
        },
        json_body=body,
    )

    status = result["status"]
    if status == 200 and result["data"] and result["data"].get("data"):
        return {"ok": True, "settings": result["data"]["data"][0]}

    if status == 401:
        return _error_response(
            401,
            "Недостаточно прав или токен истёк",
            "invalid_token",
            message="Требуется scope moderator:manage:chat_settings.",
            help_url=DEV_CONSOLE_URL,
        )

    return _error_response(
        502,
        "Не удалось обновить настройки чата",
        "helix_error",
        message=result.get("text"),
        extra={"twitch_status": status},
    )


@router.get("/scope-check")
async def scope_check(
    account_id: str = Query(...),
    _: Any = Depends(auth_dependency),
):
    """Проверка каких OAuth scopes не хватает токену (GET /oauth2/validate)."""
    if not is_helix_configured():
        return _not_configured_response()

    token = await _get_account_token(account_id)
    if not token:
        return _error_response(
            400,
            "Нет токена авторизации",
            "no_token",
            message="Для аккаунта не найден действующий OAuth токен Twitch.",
            help_url=DEV_CONSOLE_URL,
        )

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": f"OAuth {token}"},
        )

    if resp.status_code != 200:
        return _error_response(
            401,
            "Токен недействителен",
            "invalid_token",
            message="Не удалось проверить токен, требуется повторная авторизация.",
            help_url=DEV_CONSOLE_URL,
            extra={"twitch_status": resp.status_code},
        )

    try:
        data = resp.json()
    except ValueError:
        data = {}

    granted = set(data.get("scopes") or [])
    missing = [s for s in ALL_REQUIRED_SCOPES if s not in granted]

    feature_status = {
        feature: {
            "granted": all(s in granted for s in scopes),
            "missing": [s for s in scopes if s not in granted],
        }
        for feature, scopes in REQUIRED_SCOPES.items()
    }

    return {
        "ok": len(missing) == 0,
        "granted_scopes": sorted(granted),
        "required_scopes": ALL_REQUIRED_SCOPES,
        "missing_scopes": missing,
        "features": feature_status,
        "help_url": DEV_CONSOLE_URL if missing else None,
    }