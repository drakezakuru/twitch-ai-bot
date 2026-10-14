"""Разрешённые темы и поведение ботов per-канал + базовый пресет Twitch.

Хранение — settings-kv (схема БД не меняется):
- ``allowed_topics_preset`` — базовый пресет разрешённых тем и целей.
  Сид при первом чтении: стартовый набор из
  ``app/moderation_dicts/allowed_topics_twitch.json``.
- ``allowed_topics:<channel>`` — свой список канала; нет ключа или пусто →
  канал наследует пресет.

Формат текста: одно указание/тема на строку, строки с «#» — комментарии.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PRESET_KEY = "allowed_topics_preset"
CHANNEL_KEY_PREFIX = "allowed_topics:"
MAX_ALLOWED_CHARS = 8000

_STARTER_FILE = Path(__file__).resolve().parent / "moderation_dicts" / "allowed_topics_twitch.json"


def normalize_channel(channel: str) -> str:
    return str(channel or "").strip().lower().lstrip("#")


def channel_allowed_key(channel: str) -> str:
    return f"{CHANNEL_KEY_PREFIX}{normalize_channel(channel)}"


def count_rules(text: str) -> int:
    return sum(1 for ln in (text or "").splitlines() if ln.strip() and not ln.strip().startswith("#"))


def _starter_text() -> str:
    try:
        data = json.loads(_STARTER_FILE.read_text(encoding="utf-8"))
        topics = data.get("topics") or []
        return "\n".join(str(t) for t in topics)
    except Exception as exc:  # noqa: BLE001
        logger.warning("allowed topics starter read error: %s", exc)
        return ""


async def get_allowed_preset_text() -> str:
    """Текст пресета; при первом чтении сидируется из стартового набора Twitch."""
    from app.database import get_setting, set_setting

    existing = await get_setting(PRESET_KEY, "")
    if existing:
        return existing
    seeded = _starter_text()
    if seeded:
        await set_setting(PRESET_KEY, seeded)
    return seeded


async def set_allowed_preset_text(text: str) -> int:
    from app.database import set_setting

    text = str(text or "")
    if len(text) > MAX_ALLOWED_CHARS:
        raise ValueError("too_long")
    await set_setting(PRESET_KEY, text)
    return count_rules(text)


async def get_channel_allowed_text(channel: str) -> str:
    from app.database import get_setting

    return await get_setting(channel_allowed_key(channel), "") or ""


async def set_channel_allowed_text(channel: str, text: str) -> int:
    from app.database import set_setting

    ch = normalize_channel(channel)
    if not ch:
        raise ValueError("channel_required")
    text = str(text or "")
    if len(text) > MAX_ALLOWED_CHARS:
        raise ValueError("too_long")
    await set_setting(channel_allowed_key(ch), text)
    return count_rules(text)


async def resolve_channel_allowed(channel: str) -> tuple[str, str]:
    """(текст, источник): source='channel' — свой список, 'preset' — наследует пресет."""
    own = (await get_channel_allowed_text(channel)).strip()
    if own:
        return own, "channel"
    return (await get_allowed_preset_text()).strip(), "preset"
