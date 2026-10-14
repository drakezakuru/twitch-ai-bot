"""Управление временным глушением озвучки (Temporary TTS Mute / Cinematic Mute).

При активном глушении:
- Чат-боты продолжают работать, отвечать и писать в чат Twitch как обычно.
- Озвучка голосом (OBS TTS / Sound playback) временно глушится на заданное время (по умолч. 5 мин)
  или до ручного снятия.
"""
from __future__ import annotations

import time
from typing import Any

_global_mute_until: float = 0.0
_channel_mute_until: dict[str, float] = {}


def _norm_channel(channel: str) -> str:
    return str(channel or "").strip().lower().lstrip("#")


def is_tts_muted(channel: str = "") -> tuple[bool, int]:
    """Возвращает (is_muted, remaining_seconds).

    Проверяет сначала канал (если передан), затем глобальное глушение.
    """
    now = time.time()
    ch = _norm_channel(channel)
    if ch and ch in _channel_mute_until:
        until = _channel_mute_until[ch]
        if until > now:
            return True, int(until - now)
        else:
            _channel_mute_until.pop(ch, None)

    if _global_mute_until > now:
        return True, int(_global_mute_until - now)

    return False, 0


def set_tts_mute(channel: str = "", minutes: float = 5.0) -> dict[str, Any]:
    """Включает временное глушение озвучки на `minutes` минут."""
    dur_sec = max(1.0, float(minutes) * 60.0)
    until = time.time() + dur_sec
    ch = _norm_channel(channel)
    if ch:
        _channel_mute_until[ch] = until
    else:
        global _global_mute_until
        _global_mute_until = until

    return {
        "ok": True,
        "muted": True,
        "channel": ch or "all",
        "remaining_sec": int(dur_sec),
        "message": f"Озвучка (TTS) заглушена на {int(minutes)} мин" if minutes >= 1 else f"Озвучка (TTS) заглушена на {int(dur_sec)}с",
    }


def clear_tts_mute(channel: str = "") -> dict[str, Any]:
    """Снимает глушение озвучки."""
    ch = _norm_channel(channel)
    if ch:
        _channel_mute_until.pop(ch, None)
    else:
        global _global_mute_until
        _global_mute_until = 0.0
        _channel_mute_until.clear()

    return {
        "ok": True,
        "muted": False,
        "channel": ch or "all",
        "remaining_sec": 0,
        "message": "Глушение озвучки снято, TTS активен",
    }


def get_tts_mute_status(channel: str = "") -> dict[str, Any]:
    """Текущий статус глушения озвучки."""
    muted, remaining = is_tts_muted(channel)
    return {
        "ok": True,
        "muted": muted,
        "channel": _norm_channel(channel) or "all",
        "remaining_sec": remaining,
    }


def reset_state() -> None:
    """Сброс для тестов."""
    global _global_mute_until
    _global_mute_until = 0.0
    _channel_mute_until.clear()
