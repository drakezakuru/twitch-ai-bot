"""v9 AP — Lexicon-based sentiment analysis (RU+EN+CIS-сленг + emotes).

Чистый Python, без внешних зависимостей. Возвращает -1/0/+1.
Логика:
  positive = сумма весов положительных слов / эмоутов
  negative = сумма весов отрицательных слов
  если positive - negative >= POS_THRESHOLD → +1
  если negative - positive >= NEG_THRESHOLD → -1
  иначе                                    →  0
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

POS_THRESHOLD = 1.0
NEG_THRESHOLD = 1.0

# ----- Лексиконы (нормализованные lowercase) ------------------------------

POSITIVE_WORDS: Dict[str, float] = {
    # RU базовый
    "круто": 1.5, "класс": 1.4, "офигенно": 1.6, "охуенно": 1.8, "пушка": 1.5,
    "топ": 1.3, "топчик": 1.4, "красава": 1.4, "красавчик": 1.4, "молодец": 1.3,
    "хорошо": 1.0, "отлично": 1.4, "супер": 1.4, "шикарно": 1.5, "годно": 1.3,
    "годнота": 1.4, "лайк": 1.2, "плюсую": 1.2, "поддержу": 1.0, "согласен": 0.8,
    "люблю": 1.5, "обожаю": 1.7, "нравится": 1.2, "приятно": 1.0, "красиво": 1.2,
    "харош": 1.4, "харошо": 1.0, "норм": 0.7, "нормас": 1.0, "нормально": 0.8,
    "побед": 1.3, "выиграл": 1.4, "победил": 1.4, "забрал": 1.0, "затащил": 1.6,
    "имба": 1.5, "имбища": 1.7, "мощно": 1.4, "сильно": 1.0, "красиво": 1.3,
    "ура": 1.5, "ого": 1.0, "вау": 1.2, "крч": 0.0,
    "спасибо": 1.2, "благодарю": 1.3, "благодарен": 1.2,
    "поздравляю": 1.4, "поздравления": 1.3, "удачи": 1.0,
    "согл": 0.7, "база": 1.0, "базированно": 1.2, "факт": 0.8, "верно": 0.8,

    # CIS-сленг
    "ору": 1.3, "ору с этого": 1.5, "лол": 1.0, "лоол": 1.1,
    "кек": 0.8, "кеки": 0.9, "ржу": 1.3, "ржака": 1.3, "хыхы": 0.8,
    "топчанский": 1.4, "годнятина": 1.4,

    # EN базовый
    "good": 1.0, "great": 1.4, "awesome": 1.6, "nice": 1.0, "best": 1.5,
    "amazing": 1.6, "perfect": 1.5, "love": 1.4, "loved": 1.3, "lovely": 1.3,
    "happy": 1.2, "yay": 1.3, "yes": 0.6, "yeah": 0.6, "ggwp": 1.2, "gg": 0.9,
    "win": 1.0, "wins": 1.0, "winner": 1.2, "won": 1.0, "victory": 1.4,
    "thanks": 1.0, "thank": 1.0, "ty": 0.8, "thx": 0.8, "tysm": 1.2,
    "cool": 1.1, "wonderful": 1.4, "fantastic": 1.5, "epic": 1.4,
    "based": 1.0, "true": 0.6, "fact": 0.5, "facts": 0.6,
    "cute": 1.1, "adorable": 1.3,
    "wp": 1.0,

    # Эмоуты (Twitch + общие)
    "kekw": 1.4, "lul": 1.2, "lulw": 1.2, "pog": 1.5, "pogchamp": 1.6,
    "pogu": 1.4, "poggers": 1.5, "pogo": 1.3, "kekleo": 1.3,
    "omegalul": 1.4, "5head": 1.0, "ezclap": 1.2, "ezpz": 1.0,
    "katsmile": 1.0, "letsgooo": 1.5, "letsgo": 1.4, "letsgooooo": 1.6,
    "<3": 1.5, "❤️": 1.5, "❤": 1.5, "💖": 1.5, "💗": 1.4, "💕": 1.4,
    "🔥": 1.2, "👍": 1.2, "👏": 1.1, "🎉": 1.4, "🥳": 1.4, "✨": 1.0,
    "🤩": 1.5, "😍": 1.5, "😻": 1.4, "😘": 1.4, "🥰": 1.5,
    "😀": 1.0, "😁": 1.1, "😄": 1.2, "😆": 1.2, "😎": 1.0, "😊": 1.0, "🙂": 0.6,
    "😂": 1.2, "🤣": 1.3, "😹": 1.2, "💪": 1.0, "💯": 1.2, "👌": 1.0,
}

NEGATIVE_WORDS: Dict[str, float] = {
    # RU базовый
    "плохо": 1.2, "ужасно": 1.6, "отстой": 1.5, "хрень": 1.3, "херня": 1.4,
    "хуйня": 1.7, "говно": 1.7, "дерьмо": 1.6, "стыдно": 1.2, "позор": 1.4,
    "ненавижу": 1.7, "бесит": 1.5, "достал": 1.3, "достало": 1.3,
    "тупо": 1.0, "тупой": 1.2, "глупо": 1.0, "идиот": 1.4, "дебил": 1.5,
    "уныло": 1.3, "скучно": 1.0, "лагает": 1.2, "лаги": 1.0, "тильт": 1.3,
    "тильтит": 1.4, "тильтую": 1.4, "проиграл": 1.2, "слил": 1.3, "сливает": 1.3,
    "печаль": 1.2, "грустно": 1.2, "печально": 1.2, "обидно": 1.2,
    "пиздец": 1.5, "ппц": 1.3, "звиздец": 1.3, "капец": 1.0,
    "минус": 0.8, "минусую": 1.0, "не нравится": 1.0, "не согласен": 0.8,
    "криндж": 1.3, "кринж": 1.3, "ху": 0.0, "плакса": 0.8,
    "гавно": 1.6, "вонь": 1.0, "ужас": 1.4, "кошмар": 1.5,
    "болит": 1.0, "больно": 1.0, "нет": 0.4, "нету": 0.4,

    # EN базовый
    "bad": 1.0, "worst": 1.4, "terrible": 1.5, "awful": 1.5, "horrible": 1.5,
    "hate": 1.5, "hated": 1.4, "trash": 1.4, "garbage": 1.4, "shit": 1.3,
    "fuck": 1.0, "fucking": 0.7, "wtf": 0.8, "wth": 0.6, "ffs": 1.0,
    "boring": 1.2, "bored": 1.0, "sad": 1.1, "sucks": 1.3, "suck": 1.0,
    "lag": 1.0, "laggy": 1.2, "laggin": 1.2, "lagging": 1.2,
    "broken": 1.0, "bug": 0.8, "bugged": 1.0, "buggy": 1.0,
    "lose": 1.0, "lost": 1.0, "loser": 1.2, "lol no": 0.8,
    "noob": 0.8, "trash player": 1.4, "throw": 1.0, "throwing": 1.2,
    "tilted": 1.3, "tilt": 1.2, "ragequit": 1.3, "cringe": 1.4,
    "scam": 1.3, "scammer": 1.4, "rigged": 1.2, "fail": 1.0, "fails": 1.0, "failed": 1.0,
    "no": 0.3, "nope": 0.5, "nah": 0.4,
    "salty": 1.1, "toxic": 1.3, "report": 0.6,

    # Эмоуты
    "monkas": 0.9, "monkasx": 1.0, "sadge": 1.4, "sadcat": 1.3, "feelsbadman": 1.5,
    "pepehands": 1.4, "pepeloosing": 1.4, "feelsragemane": 1.4,
    "ragey": 1.2, "ragies": 1.2, "ezfail": 1.3,
    "💩": 1.4, "👎": 1.2, "😡": 1.5, "🤬": 1.6, "😠": 1.3,
    "😢": 1.3, "😭": 1.4, "😞": 1.2, "😔": 1.1, "😩": 1.2, "😫": 1.2,
    "💀": 0.5,  # неоднозначно (часто ироничный смех), но скорее негатив
    "🤮": 1.5, "🤢": 1.4, "🥵": 0.6,
}

# Усилители («очень», «реально», «прям»)
INTENSIFIERS = {
    "очень": 1.4, "реально": 1.3, "прям": 1.2, "просто": 1.1, "супер": 1.5,
    "ужасно": 1.5, "охренеть": 1.6, "охуенно": 1.6, "крайне": 1.4,
    "very": 1.4, "really": 1.3, "super": 1.5, "extremely": 1.5,
    "absolutely": 1.4, "totally": 1.3, "fucking": 1.5, "damn": 1.3,
}

# Отрицания инвертируют знак следующего слова в окне 2 токенов
NEGATIONS = {
    "не", "нет", "нету", "ни", "никогда", "никак",
    "not", "no", "never", "nothing", "none", "nope",
}

# Регулярка для удаления эмодзи и юникода (символьная)
_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F02F]",
)


# ---------- Tokenization --------------------------------------------------

_WORD_RE = re.compile(r"[a-zа-яёії0-9_<3>]+", re.IGNORECASE)


def _emoji_tokens(text: str) -> List[str]:
    return _EMOJI_RE.findall(text)


def _word_tokens(text: str) -> List[str]:
    s = text.lower().replace("<3", " <3 ")
    return _WORD_RE.findall(s)


def tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase words + emoji tokens."""
    if not text:
        return []
    return _word_tokens(text) + _emoji_tokens(text)


# ---------- Scoring -------------------------------------------------------

def score(text: str) -> Tuple[float, float]:
    """Return (positive_score, negative_score) for a chat message.

    Учитываются: лексикон, intensifiers (множитель ×K), negations (инверсия знака
    следующего значимого токена в окне 2).
    """
    if not text or not text.strip():
        return 0.0, 0.0

    tokens = tokenize(text)
    pos_total = 0.0
    neg_total = 0.0

    pending_intensifier = 1.0
    pending_negation = False
    negation_remaining = 0

    for tok in tokens:
        if tok in NEGATIONS:
            pending_negation = True
            negation_remaining = 2
            continue
        if tok in INTENSIFIERS:
            pending_intensifier *= INTENSIFIERS[tok]
            negation_remaining = max(0, negation_remaining - 1)
            continue

        pos_w = POSITIVE_WORDS.get(tok, 0.0)
        neg_w = NEGATIVE_WORDS.get(tok, 0.0)

        if pos_w == 0.0 and neg_w == 0.0:
            if negation_remaining > 0:
                negation_remaining -= 1
                if negation_remaining == 0:
                    pending_negation = False
            continue

        if pending_negation and negation_remaining > 0:
            pos_w, neg_w = neg_w, pos_w
            pending_negation = False
            negation_remaining = 0

        pos_total += pos_w * pending_intensifier
        neg_total += neg_w * pending_intensifier
        pending_intensifier = 1.0

    return pos_total, neg_total


def classify(text: str) -> int:
    """Return -1 (negative), 0 (neutral), or +1 (positive)."""
    pos, neg = score(text)
    diff = pos - neg
    if diff >= POS_THRESHOLD:
        return 1
    if -diff >= NEG_THRESHOLD:
        return -1
    return 0


def classify_with_score(text: str) -> Tuple[int, float, float]:
    pos, neg = score(text)
    diff = pos - neg
    label = 0
    if diff >= POS_THRESHOLD:
        label = 1
    elif -diff >= NEG_THRESHOLD:
        label = -1
    return label, pos, neg


# ---------- Aggregation helpers (для timeline) ----------------------------

def aggregate_buckets(
    rows: List[Tuple[str, int]],
    bucket_size_sec: int = 300,
) -> List[dict]:
    """Сгруппировать [(timestamp_iso, sentiment), ...] в bucket-ряды.

    Возвращает [{ts, pos, neg, neu, total, net}], отсортировано по ts.
    """
    from datetime import datetime
    buckets: Dict[int, Dict[str, int]] = {}
    for ts_str, sent in rows:
        try:
            t = datetime.fromisoformat(ts_str.replace(" ", "T")).timestamp()
        except Exception:
            continue
        b = int(t // bucket_size_sec) * bucket_size_sec
        slot = buckets.setdefault(b, {"pos": 0, "neg": 0, "neu": 0, "total": 0})
        slot["total"] += 1
        if sent > 0:
            slot["pos"] += 1
        elif sent < 0:
            slot["neg"] += 1
        else:
            slot["neu"] += 1

    out: List[dict] = []
    from datetime import timezone
    for b in sorted(buckets):
        s = buckets[b]
        out.append({
            "ts": datetime.fromtimestamp(b, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "ts_unix": b,
            "pos": s["pos"],
            "neg": s["neg"],
            "neu": s["neu"],
            "total": s["total"],
            "net": s["pos"] - s["neg"],
        })
    return out
