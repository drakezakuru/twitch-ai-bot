"""v9 AQ — Word cloud + trending topics.

Pure functions: tokenize messages, compute top-N word counts, compare two
periods to find trending words. RU + EN stopwords + Twitch chat noise.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Tuple

# RU stopwords (минимальный список — расширить по мере необходимости)
RU_STOPWORDS = {
    "и", "в", "не", "на", "что", "я", "с", "так", "а", "то", "как", "это",
    "по", "у", "же", "его", "но", "она", "он", "оно", "они", "за", "от",
    "до", "из", "к", "о", "об", "для", "при", "над", "под", "без", "со",
    "ну", "вот", "там", "тут", "тогда", "потом", "тоже", "ещё", "еще", "уже",
    "был", "была", "было", "были", "быть", "есть", "буду", "будет", "будут",
    "тебя", "тебе", "меня", "мне", "себя", "себе", "наш", "ваш", "его", "её",
    "ее", "их", "мой", "моя", "моё", "мои", "твой", "твоя", "твоё", "твои",
    "если", "или", "чтобы", "когда", "где", "куда", "откуда", "почему",
    "зачем", "как", "что-то", "кто-то", "кто", "чей", "чья",
    "да", "нет", "нету", "ни", "ничего", "никто", "никогда",
    "вам", "вас", "вы", "ты", "мы", "нас", "нам",
    "может", "можно", "надо", "нужно", "должен", "должна",
    "очень", "просто", "конечно", "вообще", "всегда", "никогда",
    "только", "чем", "тем", "всё", "все", "вся", "весь",
    "это", "этот", "эта", "эти", "тот", "та", "те",
}

# EN stopwords
EN_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "for",
    "to", "of", "in", "on", "at", "by", "from", "with", "as", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "its", "our", "their",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    "when", "where", "why", "how", "not", "no", "yes", "yeah", "yep",
    "so", "too", "very", "just", "only", "really", "still", "also",
    "u", "ur", "im", "ive", "id", "thats", "dont", "doesnt", "didnt",
    "wont", "wouldnt", "couldnt", "shouldnt", "ll", "ve", "re", "s", "t",
    "all", "any", "some", "more", "most", "other", "another", "such",
    "than", "now", "then", "there", "here", "lol", "lmao",
}

# Twitch chat noise (часто встречаются, но малоинформативны)
CHAT_NOISE = {
    "kekw", "kekwait", "lul", "lulw", "pog", "pogchamp", "pogu", "poggers",
    "kappa", "monkas", "monkasx", "sadge", "pepega", "pepehands", "pepela",
    "5head", "ezclap", "omegalul", "katsmile", "letsgooo", "letsgo",
    "nyam", "icant", "icant_", "linkincant",
    "ggwp", "gg", "ez", "ezpz",
}

ALL_STOPWORDS = RU_STOPWORDS | EN_STOPWORDS | CHAT_NOISE

_WORD_RE = re.compile(r"[a-zа-яёії][a-zа-яёії0-9_]{2,}", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+\.(com|ru|net|org|io|tv|gg)\b", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w+")


def tokenize_for_stats(text: str) -> List[str]:
    """Tokenize a message → list of lowercase words (≥3 chars), excluding URLs/mentions."""
    if not text:
        return []
    s = _URL_RE.sub(" ", text)
    s = _MENTION_RE.sub(" ", s)
    s = s.lower()
    return _WORD_RE.findall(s)


def count_words(messages: Iterable[str], extra_stopwords: Iterable[str] = ()) -> Counter:
    """Tokenize + filter stopwords + return counter of word frequencies."""
    stops = ALL_STOPWORDS | {w.lower() for w in extra_stopwords}
    counter: Counter = Counter()
    for msg in messages:
        for tok in tokenize_for_stats(msg):
            if tok in stops:
                continue
            if tok.isdigit():
                continue
            counter[tok] += 1
    return counter


def top_n(counter: Counter, n: int = 50) -> List[Tuple[str, int]]:
    return counter.most_common(n)


def trending(
    current: Counter,
    baseline: Counter,
    min_current: int = 3,
    smoothing: float = 1.0,
) -> List[Dict]:
    """Compute trending words: words that grew most relative to baseline.

    Uses log-ratio with Laplace smoothing:
        score = log((current + smoothing) / (baseline_normalized + smoothing))
    where baseline_normalized = baseline_count * (sum(current) / sum(baseline)).

    Returns list of {word, current, baseline, score, delta} sorted by score desc.
    Only words with current >= min_current are included.
    """
    cur_total = sum(current.values()) or 1
    base_total = sum(baseline.values()) or 1
    ratio = cur_total / base_total

    rows: List[Dict] = []
    for word, cur_count in current.items():
        if cur_count < min_current:
            continue
        base_count = baseline.get(word, 0)
        base_norm = base_count * ratio
        score = math.log((cur_count + smoothing) / (base_norm + smoothing))
        rows.append({
            "word": word,
            "current": cur_count,
            "baseline": base_count,
            "score": round(score, 3),
            "delta": cur_count - round(base_norm, 1),
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def cooling(
    current: Counter,
    baseline: Counter,
    min_baseline: int = 3,
    smoothing: float = 1.0,
) -> List[Dict]:
    """Inverse of trending: words that dropped most. Useful for «остыло».

    Words must have baseline >= min_baseline to qualify.
    """
    cur_total = sum(current.values()) or 1
    base_total = sum(baseline.values()) or 1
    ratio = cur_total / base_total

    rows: List[Dict] = []
    for word, base_count in baseline.items():
        if base_count < min_baseline:
            continue
        cur_count = current.get(word, 0)
        base_norm = base_count * ratio
        score = math.log((cur_count + smoothing) / (base_norm + smoothing))
        rows.append({
            "word": word,
            "current": cur_count,
            "baseline": base_count,
            "score": round(score, 3),
            "delta": cur_count - round(base_norm, 1),
        })

    rows.sort(key=lambda r: r["score"])  # ascending = biggest drop first
    return rows
