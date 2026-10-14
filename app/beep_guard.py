"""
Beep Guard — детектор запретных слов (матов) для Twitch AI Bot Panel.

Прогоняет транскрипты аудио (stream_audio_result из stream_vision) через
словарь запретных слов и генерирует события "beep" для перекрытия звука.

Интеграция:
    - app/widget_bus.py   — broadcast_log / duck_start / duck_end
    - app/bot_logs.py     — log_per_bot(account_id, channel, category, message)
    - app/database.py     — get_db() -> aiosqlite connection
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("beep_guard")

# --------------------------------------------------------------------------- #
# Опциональные зависимости — модуль должен импортироваться в тестах без панели
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - зависит от окружения
    from app.database import get_db  # type: ignore
except Exception:  # pragma: no cover
    get_db = None  # type: ignore

try:  # pragma: no cover
    from app.bot_logs import log_per_bot  # type: ignore
except Exception:  # pragma: no cover
    async def log_per_bot(account_id, channel, category, message):  # type: ignore
        logger.info("[log_per_bot fallback] %s/%s [%s] %s",
                    account_id, channel, category, message)

try:  # pragma: no cover
    from app import widget_bus  # type: ignore
except Exception:  # pragma: no cover
    widget_bus = None  # type: ignore


# --------------------------------------------------------------------------- #
# Словарь запретных слов по умолчанию (маты RU/UA)
# --------------------------------------------------------------------------- #
DEFAULT_BAD_WORDS: Dict[str, str] = {
    # русский
    "хуй": "profanity",
    "хуе": "profanity",
    "хуё": "profanity",
    "хуи": "profanity",
    "пизд": "profanity",
    "ебал": "profanity",
    "ебан": "profanity",
    "ебат": "profanity",
    "ебло": "profanity",
    "выеб": "profanity",
    "заеб": "profanity",
    "уеб": "profanity",
    "наеб": "profanity",
    "разъеб": "profanity",
    "долбоеб": "insult",
    "мудак": "insult",
    "мудил": "insult",
    "гандон": "insult",
    "гондон": "insult",
    "сука": "profanity",
    "суки": "profanity",
    "блядь": "profanity",
    "бляд": "profanity",
    "блять": "profanity",
    "бля": "profanity",
    "хер": "profanity",
    "херн": "profanity",
    "залуп": "profanity",
    "манда": "profanity",
    "пидор": "insult",
    "пидар": "insult",
    "педик": "insult",
    "гнида": "insult",
    "уебок": "insult",
    "чмо": "insult",
    # украинский
    "хуйн": "profanity",
    "підор": "insult",
    "підар": "insult",
    "курва": "profanity",
    "блядо": "profanity",
    "довбойоб": "insult",
    "йобан": "profanity",
    "їбан": "profanity",
    "піздець": "profanity",
    "піздец": "profanity",
}

# Замены визуально/фонетически похожих символов (обход фильтра)
_LEET_MAP = str.maketrans({
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х",
    "y": "у", "b": "в", "h": "н", "k": "к", "m": "м", "t": "т",
    "0": "о", "3": "з", "@": "а", "6": "б",
})

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": True,
    "sensitivity": "normal",   # loose | normal | strict
    "custom_words": {},        # {"слово": "category"}
    "channels": {},            # {"channel": True/False}  per-канал флаг
}


# --------------------------------------------------------------------------- #
# Нормализация текста
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    """Приводит текст к нижнему регистру, снимает диакритику и leet-замены."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.translate(_LEET_MAP)
    # схлопываем повторяющиеся символы: хуууй -> хуй
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    return text


def _build_word_map(custom_words: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Объединяет дефолтный словарь с кастомными словами из БД."""
    word_map = dict(DEFAULT_BAD_WORDS)
    if custom_words:
        for w, cat in custom_words.items():
            nw = _normalize(w)
            if nw:
                word_map[nw] = cat or "custom"
    return word_map


# --------------------------------------------------------------------------- #
# ЧИСТАЯ функция для тестов (без БД)
# --------------------------------------------------------------------------- #
def check_transcript(
    text: str,
    custom_words: Optional[Dict[str, str]] = None,
    sensitivity: str = "normal",
) -> List[Dict[str, Any]]:
    """
    Проверяет текст на запретные слова.

    Возвращает список словарей: [{"word": str, "category": str, "position": int}].

    sensitivity:
        strict — совпадение как подстрока (агрессивно ловит склонения)
        normal — совпадение по границе основы слова
        loose  — только целые слова
    """
    if not text:
        return []

    normalized = _normalize(text)
    word_map = _build_word_map(custom_words)
    results: List[Dict[str, Any]] = []
    seen: set = set()

    if sensitivity == "loose":
        # только целые слова
        tokens = re.finditer(r"[\wёіїєґ]+", normalized, flags=re.UNICODE)
        for m in tokens:
            token = m.group(0)
            if token in word_map:
                key = (token, m.start())
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "word": token,
                        "category": word_map[token],
                        "position": m.start(),
                    })
        return results

    for stem, category in word_map.items():
        if not stem:
            continue
        if sensitivity == "strict":
            pattern = re.escape(stem)
        else:  # normal — основа в начале слова
            pattern = r"(?<![\wёіїєґ])" + re.escape(stem)

        for m in re.finditer(pattern, normalized, flags=re.UNICODE):
            pos = m.start()
            key = (stem, pos)
            if key not in seen:
                seen.add(key)
                results.append({
                    "word": stem,
                    "category": category,
                    "position": pos,
                })

    results.sort(key=lambda r: r["position"])
    return results


# --------------------------------------------------------------------------- #
# Схема БД
# --------------------------------------------------------------------------- #
async def ensure_schema() -> None:
    """Создаёт таблицы beep_settings и beep_events, если их нет."""
    if get_db is None:
        logger.warning("beep_guard: get_db недоступен, схема не создана")
        return

    db = await get_db()
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS beep_settings (
                account_id   TEXT PRIMARY KEY,
                enabled      INTEGER NOT NULL DEFAULT 1,
                sensitivity  TEXT    NOT NULL DEFAULT 'normal',
                custom_words TEXT    NOT NULL DEFAULT '{}',
                channels     TEXT    NOT NULL DEFAULT '{}',
                updated_at   TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS beep_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                channel    TEXT NOT NULL,
                word       TEXT NOT NULL,
                category   TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_beep_events_acc "
            "ON beep_events(account_id, channel, created_at)"
        )
        await db.commit()
    finally:
        await db.close()
    logger.info("beep_guard: схема БД готова")


# --------------------------------------------------------------------------- #
# CRUD настроек
# --------------------------------------------------------------------------- #
def _parse_json(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


async def get_settings(account_id: str) -> Dict[str, Any]:
    """Возвращает настройки аккаунта (или дефолтные)."""
    if get_db is None:
        return dict(DEFAULT_SETTINGS)

    db = await get_db()
    try:
        db.row_factory = None
        cur = await db.execute(
            "SELECT enabled, sensitivity, custom_words, channels "
            "FROM beep_settings WHERE account_id = ?",
            (account_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()

    if not row:
        return dict(DEFAULT_SETTINGS)

    return {
        "enabled": bool(row[0]),
        "sensitivity": row[1] or "normal",
        "custom_words": _parse_json(row[2], {}),
        "channels": _parse_json(row[3], {}),
    }


async def update_settings(account_id: str, **fields: Any) -> Dict[str, Any]:
    """
    Обновляет (или создаёт) настройки аккаунта.

    Допустимые поля: enabled, sensitivity, custom_words (dict), channels (dict).
    """
    if get_db is None:
        raise RuntimeError("get_db недоступен — обновление настроек невозможно")

    current = await get_settings(account_id)

    if "enabled" in fields:
        current["enabled"] = bool(fields["enabled"])
    if "sensitivity" in fields and fields["sensitivity"] in ("loose", "normal", "strict"):
        current["sensitivity"] = fields["sensitivity"]
    if "custom_words" in fields and isinstance(fields["custom_words"], dict):
        current["custom_words"] = fields["custom_words"]
    if "channels" in fields and isinstance(fields["channels"], dict):
        current["channels"] = fields["channels"]

    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO beep_settings
                (account_id, enabled, sensitivity, custom_words, channels, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                enabled      = excluded.enabled,
                sensitivity  = excluded.sensitivity,
                custom_words = excluded.custom_words,
                channels     = excluded.channels,
                updated_at   = excluded.updated_at
            """,
            (
                account_id,
                1 if current["enabled"] else 0,
                current["sensitivity"],
                json.dumps(current["custom_words"], ensure_ascii=False),
                json.dumps(current["channels"], ensure_ascii=False),
                now,
            ),
        )
        await db.commit()
    finally:
        await db.close()

    logger.info("beep_guard: настройки обновлены для %s", account_id)
    return current


def is_channel_enabled(settings: Dict[str, Any], channel: str) -> bool:
    """Глобальный флаг + per-канал флаг beep_enabled."""
    if not settings.get("enabled", True):
        return False
    channels = settings.get("channels") or {}
    # если канал явно указан — используем его значение, иначе включён по умолчанию
    return bool(channels.get(channel, True))


# --------------------------------------------------------------------------- #
# События виджетов
# --------------------------------------------------------------------------- #
async def emit_alert(account_id: str, channel: str, word: str) -> None:
    """Отправляет событие детекта через widget_bus + duck аудио."""
    if widget_bus is None:
        logger.debug("beep_guard: widget_bus недоступен, alert пропущен")
        return

    payload = {
        "type": "beep_guard",
        "kind": "beep_detected",
        "account_id": account_id,
        "channel": channel,
        "word": word,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    try:
        broadcast = getattr(widget_bus, "broadcast_log", None)
        if broadcast is not None:
            await broadcast(payload)

        duck_start = getattr(widget_bus, "duck_start", None)
        duck_end = getattr(widget_bus, "duck_end", None)
        if duck_start is not None:
            await duck_start(source="beep", channel=channel, reason=f"beep:{channel}")
        if duck_end is not None:
            await duck_end(source="beep", channel=channel)
    except Exception:  # pragma: no cover
        logger.exception("beep_guard: ошибка при отправке alert")


async def _store_event(
    account_id: str, channel: str, word: str, category: str
) -> None:
    if get_db is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO beep_events "
                "(account_id, channel, word, category, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (account_id, channel, word, category, now),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception:  # pragma: no cover
        logger.exception("beep_guard: не удалось сохранить beep_event")


# --------------------------------------------------------------------------- #
# Основной хэндлер транскрипта
# --------------------------------------------------------------------------- #
async def on_stream_audio_result(
    account_id: str, channel: str, transcript: str
) -> List[Dict[str, Any]]:
    """
    Вызывается на каждый stream_audio_result.

    Прогоняет транскрипт через check_transcript, при обнаружении матов:
      - пишет в beep_events (БД)
      - пишет в log_per_bot (категория beep_event)
      - шлёт alert через widget_bus
    Возвращает список найденных нарушений.
    """
    if not transcript or not transcript.strip():
        return []

    try:
        settings = await get_settings(account_id)
    except Exception:  # pragma: no cover
        logger.exception("beep_guard: не удалось получить настройки, использую дефолт")
        settings = dict(DEFAULT_SETTINGS)

    if not is_channel_enabled(settings, channel):
        return []

    hits = check_transcript(
        transcript,
        custom_words=settings.get("custom_words"),
        sensitivity=settings.get("sensitivity", "normal"),
    )

    if not hits:
        return []

    for hit in hits:
        word = hit["word"]
        category = hit["category"]
        await _store_event(account_id, channel, word, category)
        try:
            await log_per_bot(
                account_id,
                channel,
                "beep_event",
                f"Обнаружено запретное слово '{word}' ({category}) "
                f"pos={hit['position']}",
            )
        except Exception:  # pragma: no cover
            logger.exception("beep_guard: ошибка log_per_bot")
        await emit_alert(account_id, channel, word)

    logger.info(
        "beep_guard: %s/%s — найдено %d нарушений",
        account_id, channel, len(hits),
    )
    return hits