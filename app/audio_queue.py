"""§7 WIDGETS_PLAN: общая аудио-очередь.

Все источники звука, які «говорять у OBS», проходять через одну чергу з
пріоритетами. Зараз джерела:

* ``alert``     — звук донату/сабу/рейду (через widget_bus.duck_start
                  подія EventSub). Може бути просто broadcast кастом-звуку
                  в майбутньому (поки що — заглушка).
* ``tts_streamer`` — відповідь TTS-бота з ``cfg.priority=streamer`` (як у
                  ``app/tts_engine.py:TTSEngine.speak`` priority=0).
* ``tts_chat_reader`` — озвучка чату з §6.1 (``read_chat_message``).
* ``tts_normal`` — звичайна TTS-відповідь без пріоритету.

Усі ці види делегують у ``TTSEngine.speak()`` (а в майбутньому — в alert
sound player). Числові пріоритети: менше = важливіше (як у heapq).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# Числові пріоритети (нижче = вище в черзі).
PRIORITY_ALERT = 0
PRIORITY_TTS_STREAMER = 5
PRIORITY_TTS_CHAT_READER = 15
PRIORITY_TTS_NORMAL = 20

_KIND_TO_PRIORITY = {
    "alert": PRIORITY_ALERT,
    "tts_streamer": PRIORITY_TTS_STREAMER,
    "tts_chat_reader": PRIORITY_TTS_CHAT_READER,
    "tts_normal": PRIORITY_TTS_NORMAL,
}


@dataclass
class AudioItem:
    kind: str
    priority: int
    payload: dict
    seq: int = 0
    enqueued_at: float = 0.0


class AudioQueue:
    """Єдина черга аудіо-подій (in-memory).

    Поки що не є «справжньою» FIFO-чергою з реальним програванням — це
    лише **диспетчер**, що:

    1. Обчислює пріоритет за ``kind``.
    2. Делегує в ``TTSEngine.speak()`` (для TTS-видів) або
       ``_alert_sound_player()`` (для алертів, заглушка).
    3. Віддає ``snapshot()`` для адмін-форми/UI.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._items: list[AudioItem] = []
        self._seq = itertools.count()
        self._max_size = 200  # обмеження на backlog (старе викидається)

    async def enqueue(
        self,
        kind: str,
        account_id: int,
        channel: str,
        text: str,
        **payload: Any,
    ) -> AudioItem:
        """Додати аудіо в чергу. Повертає ``AudioItem`` (без очікування програвання)."""
        priority = _KIND_TO_PRIORITY.get(kind, PRIORITY_TTS_NORMAL)
        item = AudioItem(
            kind=kind,
            priority=priority,
            payload={
                "account_id": account_id,
                "channel": channel,
                "text": text,
                **payload,
            },
            seq=next(self._seq),
            enqueued_at=asyncio.get_event_loop().time(),
        )
        async with self._lock:
            # Обмежуємо backlog.
            if len(self._items) >= self._max_size:
                # Видаляємо найстаріший елемент з найнижчим пріоритетом.
                self._items.sort(key=lambda x: (x.priority, x.seq))
                self._items.pop(0)
            self._items.append(item)
        # Делегуємо в TTS-двигун (для TTS-видів).
        if kind.startswith("tts_"):
            try:
                from app.tts_engine import get_tts_engine
                engine = get_tts_engine()
                # priority=streamer (0) → ``PRIORITY_TTS_STREAMER``, інакше normal.
                # TTSEngine.speak сам управляє своєю локальною чергою, тож тут
                # ``audio_queue`` — лише облік/дисплей, а не дублююча черга.
                if kind == "tts_streamer":
                    # Позначаємо пріоритет через payload priority — TTSEngine.speak
                    # читає ``cfg.get("priority")`` з tts_bot_config, тому тут
                    # просто передаємо без змін.
                    pass
                await engine.speak(account_id, channel, text,
                                   emotion=payload.get("emotion", "neutral"),
                                   speaker=payload.get("speaker", ""),
                                   speaker_kind=payload.get("speaker_kind", "bot"),
                                   display_text=payload.get("display_text", ""),
                                   provider_override=payload.get("provider_override", ""),
                                   voice_override=payload.get("voice_override", ""))
            except Exception as exc:
                logger.debug("AudioQueue: TTS delegate failed (non-fatal): %s", exc)
        # Alert — заглушка, доки §10.4 не реалізує звукові алерти.
        elif kind == "alert":
            # Тут у майбутньому буде звуковий alert-плеєр.
            logger.debug("AudioQueue: alert %s (no audio player yet)", payload)
        # Очищуємо item з нашої облікової черги після делегування.
        async with self._lock:
            self._items = [x for x in self._items if x.seq != item.seq]
        return item

    def snapshot(self) -> list[dict]:
        """Знімок черги (для UI/дебагу)."""
        return [
            {
                "kind": it.kind,
                "priority": it.priority,
                "account_id": it.payload.get("account_id"),
                "channel": it.payload.get("channel"),
                "text": (it.payload.get("text") or "")[:80],
                "seq": it.seq,
                "age_ms": int((asyncio.get_event_loop().time() - it.enqueued_at) * 1000),
            }
            for it in sorted(self._items, key=lambda x: (x.priority, x.seq))
        ]

    def size(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()

    def _reset_for_tests(self) -> None:
        """Скидає singleton-стан. Тільки для тестів."""
        self._items.clear()
        self._seq = itertools.count()


# ── Singleton ──────────────────────────────────────────────

_queue: AudioQueue | None = None


def get_audio_queue() -> AudioQueue:
    global _queue
    if _queue is None:
        _queue = AudioQueue()
    return _queue


__all__ = [
    "AudioQueue",
    "AudioItem",
    "get_audio_queue",
    "PRIORITY_ALERT",
    "PRIORITY_TTS_STREAMER",
    "PRIORITY_TTS_CHAT_READER",
    "PRIORITY_TTS_NORMAL",
]
