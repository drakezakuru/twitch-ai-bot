"""Vision prompt construction + reasoning-leak post-processing.

v10.4.8: reasoning-модели (например ``nvidia/nemotron-...-reasoning``,
``deepseek-r1``, ``openai/o1``) часто сливают chain-of-thought в финальный
ответ — длинный английский монолог «We need to..., Let's parse..., So
answer: "<actual answer>"». Этот модуль:

  * собирает vision-промпт с учётом контекста стрима (Helix: игра, название);
  * пост-обрабатывает ответ модели: вырезает английский reasoning, оставляя
    только осмысленное описание на русском.

Все настройки опциональны — если что-то выключено, ведёт себя как раньше.
"""

from __future__ import annotations

import re
from typing import Optional

# Короткий «basic» промпт — поведение как до v10.4.8 (для обратной совместимости).
_PROMPT_BASIC = (
    "Кратко опиши что происходит на стриме на русском (1-2 предложения). "
    "Что видно: игра, сцена, действия стримера. Без вступлений. "
    "Если происходит что-то яркое (килл, смерть, победа, смешной момент) — "
    "выдели это в первую очередь."
)

# «detailed» промпт — описывает PiP/split-screen и реакцию стримера отдельно.
_PROMPT_DETAILED = (
    "Опиши кадр стрима на русском, 1-2 коротких предложения. "
    "Если на экране несколько окон (split-screen, PiP, встроенный плеер с "
    "видео которое смотрит стример, веб-камера в углу) — опиши и контент "
    "окон, и реакцию стримера, чётко разделяя «на видео: ...» и «стример: ...». "
    "Если что-то яркое (килл, победа, смешной момент, неожиданность) — "
    "выдели в первую очередь. "
    "Только финальное описание. Без вступлений, без рассуждений, без "
    "повторения вопроса, без английского — пиши сразу по делу на русском."
)


def build_vision_prompt(
    *,
    style: str = "detailed",
    override: str = "",
    channel_info: Optional[dict] = None,
    include_stream_info: bool = True,
) -> str:
    """Собирает промпт для vision-модели.

    Args:
        style: ``basic`` или ``detailed``. ``detailed`` явно просит описывать
            PiP/split-screen и подавляет reasoning.
        override: полная перебивка дефолтного промпта (env ``VISION_PROMPT_OVERRIDE``).
            Если задан — channel_info всё равно подмешивается префиксом, если
            ``include_stream_info=True``.
        channel_info: словарь из ``twitch_helix.get_channel_info()`` — title,
            game_name, viewer_count, is_live. Может быть None.
        include_stream_info: подмешать ли «играет в X, название стрима 'Y'»
            в начало промпта.

    Returns:
        Готовая строка промпта.
    """
    base = (override or "").strip()
    if not base:
        base = _PROMPT_DETAILED if style == "detailed" else _PROMPT_BASIC

    if include_stream_info and channel_info:
        prefix_parts: list[str] = []
        game = (channel_info.get("game_name") or "").strip()
        title = (channel_info.get("title") or "").strip()
        if game:
            prefix_parts.append(f"Категория стрима: {game}.")
        if title:
            # Обрезаем title до разумной длины — vision-модели не любят
            # длинные prefix-простыни.
            short_title = title if len(title) <= 120 else title[:117] + "..."
            prefix_parts.append(f"Название стрима: «{short_title}».")
        if prefix_parts:
            return " ".join(prefix_parts) + " " + base
    return base


# --- Reasoning-leak parser ---------------------------------------------------

# Тэги, в которые часто оборачивают chain-of-thought.
_THINK_TAG_RE = re.compile(
    r"<\s*(think|thinking|reasoning|reflection|scratch|scratchpad)\s*>.*?"
    r"<\s*/\s*\1\s*>",
    flags=re.DOTALL | re.IGNORECASE,
)

# Незакрытые версии (`<think>...` без закрывающего тэга — встречается у мелких
# моделей которые «отрубаются» по лимиту токенов).
_UNCLOSED_THINK_RE = re.compile(
    r"<\s*(think|thinking|reasoning|reflection|scratch|scratchpad)\s*>.*?$",
    flags=re.DOTALL | re.IGNORECASE,
)

# «Final answer:» / «Answer:» / «So answer:» / «Ответ:» — после такого
# маркера обычно идёт чистый ответ. Если он процитирован — извлекаем quote.
_ANSWER_MARKER_RE = re.compile(
    r"(?:so\s+answer|final\s+answer|the\s+answer|answer|итак|ответ|финальный\s+ответ)"
    r"\s*[:\-—]+\s*",
    flags=re.IGNORECASE,
)

# Кавычки которыми модели обрамляют финальный ответ.
_QUOTED_BLOCK_RE = re.compile(
    r"[\"«“„](.{30,2000}?)[\"»”]",
    flags=re.DOTALL,
)

# Признаки английского «мета-рассуждения» в начале строки.
_ENGLISH_META_STARTERS = (
    "we need", "we should", "we have to", "let's", "let us", "okay,",
    "ok,", "alright", "first,", "so we", "so the", "so,",
    "the user", "the assistant", "i need", "i should", "i will",
    "i'll", "the question", "this is a", "hmm", "wait,", "now,",
    "looking at", "based on", "given that", "the image", "the picture",
    "the streamer", "the streamer's", "in the image", "from the image",
)


def _cyrillic_ratio(text: str) -> float:
    """Доля кириллических букв среди буквенных символов."""
    cyr = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    lat = sum(1 for c in text if c.isalpha() and not ("\u0400" <= c <= "\u04ff"))
    total = cyr + lat
    if total == 0:
        return 0.0
    return cyr / total


def _looks_like_english_meta(text: str) -> bool:
    """True если начало текста — английское мета-рассуждение."""
    head = text.lstrip().lower()[:60]
    return any(head.startswith(starter) for starter in _ENGLISH_META_STARTERS)


def strip_reasoning(text: str) -> str:
    """Удаляет из ответа модели chain-of-thought, оставляя финальное описание.

    Применяемые шаги (по приоритету):

    1. Удалить ``<think>...</think>`` и аналогичные тэги.
    2. Удалить незакрытые ``<think>...`` хвосты.
    3. Если есть маркер ``Answer:`` / ``So answer:`` / ``Ответ:`` — взять
       всё после маркера. Если за маркером цитата — взять цитату.
    4. Если в тексте >50% латиницы, поискать длинный (≥30 символов)
       процитированный блок преимущественно на русском — он, скорее всего,
       и есть финальный ответ.
    5. Если начало — английская мета-фраза («We need to...»), отрезать всё
       до первой кириллической буквы.
    6. Отрезать хвост вида ``That's 2 sentences. Let's...`` после русской части.

    Если ничего из эвристик не сработало — возвращает исходный текст.
    Функция консервативна: лучше оставить лишнее, чем стереть полезное.
    """
    if not text:
        return text
    original = text

    # 1+2. Удаляем <think>-блоки.
    text = _THINK_TAG_RE.sub("", text)
    if "<think" in text.lower() or "<reasoning" in text.lower():
        text = _UNCLOSED_THINK_RE.sub("", text)

    # 3. Маркер «Answer:» / «Ответ:».
    m = _ANSWER_MARKER_RE.search(text)
    if m:
        after = text[m.end():].strip()
        # Если сразу после маркера — кавычки, берём содержимое первой кавычки.
        q = _QUOTED_BLOCK_RE.match(after)
        if q and _cyrillic_ratio(q.group(1)) > 0.5:
            return _trim_trailing_english(q.group(1).strip())
        if after and _cyrillic_ratio(after) > 0.3:
            return _trim_trailing_english(after)

    # 4. Преимущественно английский текст — ищем длинную русскую цитату.
    if _cyrillic_ratio(text) < 0.5:
        candidates = list(_QUOTED_BLOCK_RE.finditer(text))
        # Берём самую длинную русскую цитату.
        ru_quotes = [
            q.group(1).strip()
            for q in candidates
            if _cyrillic_ratio(q.group(1)) > 0.7 and len(q.group(1).strip()) >= 30
        ]
        if ru_quotes:
            return _trim_trailing_english(max(ru_quotes, key=len))

    # 5. Английская мета в начале — отрезаем до первой русской буквы.
    if _looks_like_english_meta(text):
        m = re.search(r"[А-Яа-яЁё]", text)
        if m:
            tail = text[m.start():]
            if _cyrillic_ratio(tail) > 0.5:
                # Включаем символ перед русской буквой если это открывающая кавычка.
                start = m.start()
                if start > 0 and text[start - 1] in "«\"“":
                    start -= 1
                text = text[start:]

    text = _trim_trailing_english(text).strip()
    if not text:
        return original  # ничего не нашли — отдаём как есть
    return text


def _trim_trailing_english(text: str) -> str:
    """Срезает английские хвостовые мета-фразы после русского текста."""
    # Маркеры начала «постфикс-рассуждения».
    pattern = re.compile(
        r"\s*(?:"
        r"That's\b.*$"
        r"|That is\b.*$"
        r"|Let's\b.*$"
        r"|Let me\b.*$"
        r"|So we\b.*$"
        r"|We\s+(?:should|need|have)\b.*$"
        r"|I\s+(?:should|need|will|think|hope)\b.*$"
        r"|Now,\b.*$"
        r"|Hmm\b.*$"
        r")",
        flags=re.IGNORECASE | re.DOTALL,
    )
    out = pattern.sub("", text)
    # Закрывающую кавычку если открывающей нет — убираем.
    out = out.strip()
    if out and out[-1] in "»\"”" and out[0] not in "«\"“":
        out = out.rstrip("»\"”").strip()
    if out and out[0] in "«\"“" and out[-1] not in "»\"”":
        out = out.lstrip("«\"“").strip()
    return out
