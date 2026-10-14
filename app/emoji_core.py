"""Общее ядро распознавания эмодзи для emoji-семейства виджетов.

Wave 7 (owner survey Q34/Q35: М) — «общее ядро распознавания, оба вида
сохранить». Виджеты остаются разными:

* ``emoji-leaderboard`` — рейтинг по количеству эмодзи за день;
* ``emoji-chat`` — живая лента сообщений с эмодзи и emote-картинками.

Но «что считается эмодзи» описано здесь один раз: и подсчёт, и токенизация
для рендера, чтобы лента и рейтинг не расходились в трактовке одного и того
же сообщения.
"""
from __future__ import annotations

import re

# Unicode-диапазоны эмодзи: пиктограммы/эмотиконы (не-BMP), символы Misc/Dingbats
# и вариационный селектор. Грубая, но стабильная оценка — точная таблица Unicode
# здесь не нужна и потянула бы внешнюю зависимость.
EMOJI_PATTERN = "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\ufe0f]"

_EMOJI_RE = re.compile(EMOJI_PATTERN)


def extract_emojis(text: str) -> list[str]:
    """Все unicode-эмодзи сообщения в порядке появления."""
    if not text:
        return []
    return _EMOJI_RE.findall(text)


def count_emojis(text: str) -> int:
    """Сколько unicode-эмодзи в сообщении (0 для пустого/без эмодзи)."""
    return len(extract_emojis(text))


def has_emoji(text: str) -> bool:
    """Есть ли в сообщении хоть один эмодзи — фильтр emoji-only ленты."""
    return bool(text) and _EMOJI_RE.search(text) is not None


def tokenize(text: str, emote_codes: tuple[str, ...] | list[str] = ()) -> list[tuple[str, str]]:
    """Разложить сообщение на токены ``(kind, value)``.

    ``kind`` — ``emote`` (известный код BTTV/7TV/Twitch), ``emoji`` (unicode)
    или ``text``. Длинные emote-коды матчатся раньше коротких, чтобы
    ``KEKW`` не съедался частью другого кода.
    """
    if not text:
        return []
    codes = sorted({c for c in emote_codes if c}, key=len, reverse=True)
    pattern = EMOJI_PATTERN
    if codes:
        pattern = "|".join(re.escape(c) for c in codes) + "|" + pattern
    tokens: list[tuple[str, str]] = []
    pos = 0
    for match in re.finditer(pattern, text):
        if match.start() > pos:
            tokens.append(("text", text[pos:match.start()]))
        value = match.group()
        tokens.append(("emoji" if _EMOJI_RE.fullmatch(value) else "emote", value))
        pos = match.end()
    if pos < len(text):
        tokens.append(("text", text[pos:]))
    return tokens
