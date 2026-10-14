"""§7 BRAIN_PLAN: правила авто-привязанности по содержанию сообщений.

Расширяет базовый авто-прирост (+1 за сообщение) весами за события:
  - юмор (эмодзи-реакции, «ахах», «лол», ...)  → вверх
  - поддержка (спасибо, «лучший», ❤️, ...)     → вверх
  - конфликт (оскорбления, агрессия)           → вниз
Всё пишется через bot_affinity (изменение) + bot_affinity_history
(только событийные дельты, не рутинный +1).

Уважает auto_adjust=1 и manual_lock=0 — как прежний авто-прирост.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.database import get_db

logger = logging.getLogger(__name__)

# --- маркеры (без AI, детерминированно и дёшево) ---

_HUMOR_STRONG = (
    "😂", "🤣", "😆", "ахах", "ааах", "хахах", "хах", "лол", "lol", "lmao",
    "кек", "azaz", "азаз", "💀",
)
_HUMOR_SOFT = ("😄", "😅", "🙂", "🤡", "хаха", "хе", "кринжовно но смешно", "ржу")
_SUPPORT = (
    "спасибо", "спс", "пасиб", "благодар", "лучший", "топ", "круто",
    "огонь", "люблю", "❤", "💙", "💚", "🧡", "👍", "🔥", "+rep",
)
_CONFLICT = (
    "иди на", "пошел на", "пошёл на", "нахуй", "блять", "бля", "сука",
    "лох", "дурак", "дура", "тупой", "тупая", "дебил", "идиот", "кретин",
    "мудак", "заткнись", "hate", "stupid", "idiot", "fuck you",
)

# дельты за одно сообщение
DELTA_DEFAULT = 1
DELTA_HUMOR_STRONG = 3
DELTA_HUMOR_SOFT = 2
DELTA_SUPPORT = 2
DELTA_CONFLICT = -4
MIN_DELTA = -5
MAX_DELTA = 3

_word_re = re.compile(r"\w+", re.UNICODE)


def _contains(text_lower: str, markers: tuple[str, ...]) -> bool:
    return any(m in text_lower for m in markers)


def compute_affinity_delta(message: str) -> tuple[int, str]:
    """Правила → (delta, reason). reason: humor|support|conflict|default."""
    text = (message or "").strip()
    if not text:
        return DELTA_DEFAULT, "default"
    low = text.lower()
    has_conflict = _contains(low, _CONFLICT)
    has_humor_strong = _contains(low, _HUMOR_STRONG)
    has_humor_soft = _contains(low, _HUMOR_SOFT)
    has_support = _contains(low, _SUPPORT)

    # конфликт важнее — ссора гасит позитив
    if has_conflict:
        delta = DELTA_CONFLICT
        if has_support:
            delta = max(delta, -3)  # извинился/похвалил в том же сообщении
        return max(MIN_DELTA, min(MAX_DELTA, delta)), "conflict"
    if has_humor_strong:
        delta = DELTA_HUMOR_STRONG
        if has_support:
            delta += 1
        return max(MIN_DELTA, min(MAX_DELTA, delta)), "humor"
    if has_support:
        return max(MIN_DELTA, min(MAX_DELTA, DELTA_SUPPORT)), "support"
    if has_humor_soft:
        return max(MIN_DELTA, min(MAX_DELTA, DELTA_HUMOR_SOFT)), "humor"
    return DELTA_DEFAULT, "default"


# --- уровни привязанности (§7: пороги 0-20-40-60-80) ---

AFFINITY_LEVELS = (
    (80, "близкий"),
    (60, "постоянный"),
    (40, "знакомый"),
    (20, "зритель"),
    (0, "незнакомец"),
)


def affinity_level(value: int | float | None) -> str:
    try:
        v = int(value or 0)
    except (TypeError, ValueError):
        v = 0
    for threshold, label in AFFINITY_LEVELS:
        if v >= threshold:
            return label
    return "незнакомец"


def _normalize(channel: str, username: str) -> tuple[str, str]:
    return (
        (channel or "").strip().lower().lstrip("#"),
        (username or "").strip().lower().lstrip("@"),
    )


async def apply_message_affinity(
    account_id: int,
    channel: str,
    username: str,
    message: str,
) -> tuple[int, str]:
    """Применяет правило к bot_affinity (если row есть, auto_adjust=1, lock=0).

    Возвращает (delta, reason). Пишет history только для событийных дельт.
    """
    channel_n, user_n = _normalize(channel, username)
    if not user_n:
        return 0, "no_user"
    delta, reason = compute_affinity_delta(message)
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """UPDATE bot_affinity
                   SET chat_affinity = MAX(0, MIN(100, chat_affinity + ?)),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE account_id = ? AND channel = ? AND username = ?
                     AND auto_adjust = 1 AND manual_lock = 0""",
                (delta, account_id, channel_n, user_n),
            )
            await db.commit()
            if cursor.rowcount and reason != "default":
                cur2 = await db.execute(
                    """SELECT contact_level, chat_affinity, auto_adjust, manual_lock
                       FROM bot_affinity
                       WHERE account_id = ? AND channel = ? AND username = ?""",
                    (account_id, channel_n, user_n),
                )
                row = await cur2.fetchone()
                if row:
                    await db.execute(
                        """INSERT INTO bot_affinity_history
                           (account_id, channel, username, contact_level, chat_affinity,
                            auto_adjust, manual_lock, source)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (account_id, channel_n, user_n,
                         row["contact_level"], row["chat_affinity"],
                         row["auto_adjust"], row["manual_lock"],
                         f"auto_{reason}"[:32]),
                    )
                    await db.commit()
            return delta, reason
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("apply_message_affinity error: %s", exc)
        return 0, "error"


async def affinity_summary(account_id: int, channel: str, username: str) -> Optional[dict]:
    """Число + уровень (для UI/роботов)."""
    channel_n, user_n = _normalize(channel, username)
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """SELECT contact_level, chat_affinity, auto_adjust, manual_lock
                   FROM bot_affinity
                   WHERE account_id = ? AND channel = ? AND username = ?""",
                (account_id, channel_n, user_n),
            )
            row = await cursor.fetchone()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("affinity_summary error: %s", exc)
        return None
    if not row:
        return None
    d = dict(row)
    d["level"] = affinity_level(d.get("chat_affinity"))
    return d
