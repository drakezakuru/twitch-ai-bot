"""Единый источник Twitch Client ID / Secret.

Раньше TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET читались только из переменных
окружения (см. README — "TWITCH_CLIENT_ID нужен для…"). Теперь приоритет такой:

  1. Значения, заданные через UI и сохранённые в таблице ``settings``
     (ключи ``twitch_client_id`` / ``twitch_client_secret``).
  2. Переменные окружения ``TWITCH_CLIENT_ID`` / ``TWITCH_CLIENT_SECRET``.

Это позволяет:
  - вводить Client ID прямо со страницы настроек, не редактируя ``.env``;
  - менять его на лету (без рестарта сервера) — изменения сразу подхватывают
    Helix, Device Code Flow и EventSub;
  - оставаться обратно совместимым: если БД пуста, всё работает как раньше.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from app.database import get_db, get_setting, set_setting
from app.security import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

# Ключи в таблице settings
KEY_CLIENT_ID = "twitch_client_id"
KEY_CLIENT_SECRET = "twitch_client_secret"

# Runtime-кэш. None означает "не задано через UI" — используем env как fallback.
_runtime: dict[str, Optional[str]] = {
    "client_id": None,
    "client_secret": None,
}


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def get_client_id() -> str:
    """Текущий Client ID: сначала UI/DB override, потом env."""
    override = _runtime.get("client_id")
    if override:
        return override
    return os.getenv("TWITCH_CLIENT_ID", "").strip()


def get_client_secret() -> str:
    """Текущий Client Secret: сначала UI/DB override, потом env."""
    override = _runtime.get("client_secret")
    if override:
        return override
    return os.getenv("TWITCH_CLIENT_SECRET", "").strip()


def is_helix_configured() -> bool:
    """И Client ID и Secret заданы — значит Helix-фичи (refresh, EventSub) работают."""
    return bool(get_client_id()) and bool(get_client_secret())


def is_device_flow_configured() -> bool:
    """Для Device Code Flow достаточно одного Client ID (public app)."""
    return bool(get_client_id())


def get_status() -> dict:
    """Что отдаём в UI для индикаторов."""
    cid = _runtime.get("client_id")
    csec = _runtime.get("client_secret")
    env_cid = os.getenv("TWITCH_CLIENT_ID", "").strip()
    env_csec = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
    if cid:
        client_id_source = "db"
    elif env_cid:
        client_id_source = "env"
    else:
        client_id_source = "none"
    if csec:
        client_secret_source = "db"
    elif env_csec:
        client_secret_source = "env"
    else:
        client_secret_source = "none"
    return {
        # client_id публичен — отдавать его UI безопасно (он уходит в браузер пользователя при OAuth).
        "client_id": get_client_id(),
        # secret — никогда не отдаём наружу. Только флаг "задан/не задан".
        "client_secret_set": bool(get_client_secret()),
        "client_id_source": client_id_source,
        "client_secret_source": client_secret_source,
        "helix_configured": is_helix_configured(),
        "device_flow_configured": is_device_flow_configured(),
    }


def set_runtime_credentials(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> None:
    """Применить значения только в памяти (без записи в БД)."""
    if client_id is not None:
        _runtime["client_id"] = _normalize(client_id)
    if client_secret is not None:
        _runtime["client_secret"] = _normalize(client_secret)


async def load_from_db() -> None:
    """Прогреть runtime-кэш из таблицы settings.

    Вызывается один раз при старте сервера (см. ``app/server.py`` lifespan).
    """
    try:
        cid = await get_setting(KEY_CLIENT_ID, "")
        csec = decrypt_token(await get_setting(KEY_CLIENT_SECRET, ""))
        set_runtime_credentials(cid, csec)
        if cid or csec:
            logger.info(
                "Twitch credentials: client_id=%s, secret=%s (from DB)",
                "set" if cid else "<unset>",
                "set" if csec else "<unset>",
            )
        else:
            logger.info("Twitch credentials: используются значения из .env (БД пуста)")
    except Exception as exc:
        logger.warning("Не удалось загрузить twitch_credentials из БД: %s", exc)


async def save_to_db(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> None:
    """Записать значения в БД и применить runtime.

    Передавайте только те поля, что нужно изменить. Пустая строка означает
    "очистить override и снова использовать env".
    """
    if client_id is not None:
        await set_setting(KEY_CLIENT_ID, client_id.strip())
    if client_secret is not None:
        await set_setting(KEY_CLIENT_SECRET, encrypt_token(client_secret.strip()))
    set_runtime_credentials(client_id=client_id, client_secret=client_secret)
