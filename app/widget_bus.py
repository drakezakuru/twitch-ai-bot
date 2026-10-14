"""§1 WIDGETS_PLAN: Widget Audio Bus.

Единая шина для координации звука/видео между OBS-виджетами.

Зачем нужно: виджеты живут в разных Browser Source в OBS и не имеют прямого
доступа к DOM друг друга. Вместо того, чтобы каждый виджет «дёргал» соседа,
любой источник звука (TTS, alert, song-request) публикует в шину декларативный
сигнал («прошу всех утихнуть» / «прошу поставить видео на паузу»), а каждый
виджет-слушатель сам решает, как реагировать.

Протокол через существующий ``broadcast_log`` (app/server.py):

    {"type": "widget_bus", "kind": "duck_start", "source": "donation",
     "reason": "donation", "duration_ms": 8000, "at": 1693212345.123}

Виды сигналов:
    * ``duck_start`` / ``duck_end`` — «источник звука просит остальных утихнуть».
      В TTS-движке (``TTSEngine.speak``) проверяется активный ``duck_start`` —
      если есть, синтез откладывается в очередь до конца окна (``hard_mute=False``)
      или отбрасывается (``hard_mute=True``).
    * ``pause_media`` / ``resume_media`` — «прошу поставить медиа-виджет на паузу».
      Источник (обычно начало озвучки TTS) и приёмник (медиа-виджет) — оба
      подписаны на ``/ws``, обмен через ``widget_bus``-событие.

In-memory состояние: ``_active_ducks`` хранит время истечения каждого источника,
``is_ducked()`` отдаёт суммарный «факт молчания». Это синхронный in-memory
кэш, обнуляется при рестарте процесса (что нормально — стрим тоже перезапускается).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DuckState:
    channel: str
    source: str
    reason: str
    hard_mute: bool
    expires_at: float  # time.time() в секундах


# ── Активные «молчания» ───────────────────────────────────────
# Ключ: source ("donation", "subscribe", "cheer", "raid", "redemption", "manual").
# Значение: DuckState с абсолютным временем истечения (time.time()).
_active_ducks: dict[tuple[str, str], DuckState] = {}
_published_event_ids: dict[tuple[str, str], float] = {}
# asyncio.Lock привязывается к event loop первого использования; в тестах
# каждый тест — свежий loop, поэтому лок пересоздаётся при смене loop.
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


async def _get_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


async def duck_start(
    source: str,
    channel: str,
    reason: str = "",
    duration_ms: int = 8000,
    hard_mute: bool = False,
) -> None:
    """Поднять «молчание» от источника ``source`` на ``duration_ms`` мс.

    Повторный вызов для того же ``source`` **продлевает** окно, а не дублирует.
    """
    if duration_ms <= 0:
        return
    channel = str(channel or "").strip().lower().lstrip("#")
    if not channel:
        return
    expires_at = time.time() + duration_ms / 1000.0
    async with await _get_lock():
        _active_ducks[(channel, source)] = DuckState(
            channel=channel,
            source=source,
            reason=reason or source,
            hard_mute=hard_mute,
            expires_at=expires_at,
        )
    await _broadcast_bus("duck_start", channel=channel, source=source, reason=reason or source,
                         duration_ms=duration_ms, hard_mute=hard_mute)
    logger.debug("widget_bus.duck_start source=%s duration_ms=%d hard_mute=%s",
                 source, duration_ms, hard_mute)


async def duck_end(source: str, channel: str) -> None:
    """Снять «молчание» от источника ``source`` досрочно (раньше истечения окна)."""
    async with await _get_lock():
        removed = _active_ducks.pop((str(channel or "").strip().lower().lstrip("#"), source), None)
    if removed is not None:
        await _broadcast_bus("duck_end", channel=removed.channel, source=source, reason=removed.reason,
                             hard_mute=removed.hard_mute)
        logger.debug("widget_bus.duck_end source=%s", source)


def is_ducked(channel: str = "") -> DuckState | None:
    """Вернуть активный DuckState, если хоть один источник сейчас «глушит» звук.

    Возвращает ``None`` если молчания нет. Синхронная (без lock) — истечение
    окна проверяется по ``time.time()``, устаревшие записи чистятся лениво
    при следующем ``is_ducked()`` / ``purge_expired()``.
    """
    if not _active_ducks:
        return None
    now = time.time()
    active: DuckState | None = None
    normalized = str(channel or "").strip().lower().lstrip("#")
    for key, st in list(_active_ducks.items()):
        if st.expires_at <= now:
            _active_ducks.pop(key, None)
            continue
        if normalized and st.channel != normalized:
            continue
        if active is None or st.expires_at > active.expires_at:
            active = st
    return active


def is_hard_muted(channel: str = "") -> bool:
    """True, если активный duck имеет ``hard_mute=True`` (TTS должен пропустить)."""
    st = is_ducked(channel)
    return bool(st and st.hard_mute)


def remaining_ms(channel: str = "") -> int:
    """Сколько мс ещё осталось у активного duck-окна (0 если нет)."""
    st = is_ducked(channel)
    if not st:
        return 0
    return max(0, int((st.expires_at - time.time()) * 1000))


def purge_expired() -> int:
    """Убрать все истёкшие записи. Возвращает количество удалённых."""
    if not _active_ducks:
        return 0
    now = time.time()
    n = 0
    for key in [key for key, st in _active_ducks.items() if st.expires_at <= now]:
        _active_ducks.pop(key, None)
        n += 1
    return n


def get_active_ducks_snapshot() -> list[dict]:
    """Снимок активных duck-окон (для диагностики/UI)."""
    purge_expired()
    return [
        {
            "source": st.source,
            "channel": st.channel,
            "reason": st.reason,
            "hard_mute": st.hard_mute,
            "remaining_ms": max(0, int((st.expires_at - time.time()) * 1000)),
        }
        for st in _active_ducks.values()
    ]


# ── Media pause (для §4) ─────────────────────────────────────

async def request_pause_media(source: str, channel: str, reason: str = "") -> None:
    """Попросить подписчиков поставить медиа на паузу."""
    if channel:
        await _broadcast_bus("pause_media", channel=channel, source=source, reason=reason or source)


async def request_resume_media(source: str, channel: str, reason: str = "") -> None:
    """Попросить подписчиков возобновить медиа."""
    if channel:
        await _broadcast_bus("resume_media", channel=channel, source=source, reason=reason or source)


def claim_event(channel: str, event_id: str) -> bool:
    """Claim one channel event across bot accounts and reconnects."""
    normalized = str(channel or "").strip().lower().lstrip("#")
    stable_id = str(event_id or "").strip()
    if not normalized or not stable_id:
        return True
    now = time.monotonic()
    for key, seen_at in list(_published_event_ids.items()):
        if now - seen_at > 900:
            _published_event_ids.pop(key, None)
    key = (normalized, stable_id)
    if key in _published_event_ids:
        return False
    _published_event_ids[key] = now
    if len(_published_event_ids) > 4096:
        _published_event_ids.pop(next(iter(_published_event_ids)))
    return True


def event_projection_id(event_type: str, payload: dict[str, Any]) -> str:
    """Stable projection identity across separate EventSub subscriptions."""
    provider_id = str(payload.get("id") or "").strip()
    if provider_id:
        return f"{event_type}:{provider_id}"
    event = {key: value for key, value in payload.items() if not str(key).startswith("_")}
    timestamp = str(payload.get("_event_timestamp") or "").strip()
    if timestamp:
        event["event_time_bucket"] = timestamp[:18]
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{event_type}:{digest}"


# ── WS broadcast ─────────────────────────────────────────────

async def _broadcast_bus(kind: str, **payload: Any) -> None:
    """Шлёт ``{"type": "widget_bus", "kind": kind, ...}`` через ``broadcast_log``.

    Импорт внутри функции, чтобы избежать циркулярного импорта
    (``app.server`` уже импортирует ``app.tts_engine`` и т.п.).
    """
    try:
        from app.server import broadcast_log
        await broadcast_log({
            "type": "widget_bus",
            "kind": kind,
            "at": time.time(),
            **payload,
        })
    except Exception as exc:
        logger.debug("widget_bus broadcast failed: %s", exc)


# ── Тест-хелперы ─────────────────────────────────────────────

def _reset_for_tests() -> None:
    """Сбросить состояние шины. Только для тестов."""
    _active_ducks.clear()
    _published_event_ids.clear()


__all__ = [
    "duck_start",
    "duck_end",
    "is_ducked",
    "is_hard_muted",
    "remaining_ms",
    "purge_expired",
    "get_active_ducks_snapshot",
    "request_pause_media",
    "request_resume_media",
    "claim_event",
    "event_projection_id",
    "_reset_for_tests",
]
