"""Feature W: Highlight / clip detector.

Анализирует чат-лог и находит «всплески реакции» — окна по 1 минуте,
где количество сообщений и/или специфических эмоутов значительно выше
скользящего baseline. Каждый всплеск может быть кандидатом на клип/хайлайт.

Полностью изолируемый модуль без I/O — работает с уже загруженными rows.
Предполагается, что вызывающий код передаёт список dict'ов с полями
``timestamp`` (ISO 8601), ``channel``, ``author``, ``message``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

# Ходовые твитч/CIS-реакции, которые обычно сигналят про «смешной/интересный момент».
# Регистр игнорируется. Совпадение по token-границе (см. _RE_TOKEN).
DEFAULT_REACTION_TOKENS: tuple[str, ...] = (
    # Англоязычные эмоуты
    "kekw", "kekl", "lul", "lulw", "omegalul", "pog", "pogchamp", "pogu",
    "kappa", "sadge", "monkas", "monkaw", "ezclap", "ez", "copium", "hopium",
    "pepelaugh", "peporun", "pepoclap", "5head", "widepeepohappy", "kkona",
    "pausechamp", "weirdchamp", "yep", "nopers", "icant",
    # Русско/CIS реакции
    "кек", "кекв", "ору", "ору_в_голос", "ору-в-голос",
    "лол", "лолкек", "ахах", "ахаха", "ахахаха", "ору_орел",
    "омг", "вау", "база", "збс", "топ",
    # Универсальные
    "lmao", "rofl", "lmaoo", "+1", "f", "respect",
)

# Токенизация: слово/эмоут — последовательность букв/цифр, возможно с цифрой в конце (KEKW1, Pog2).
_RE_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9_]*", re.UNICODE)
# Простые «emoji-like» эмоуты типа +1 / <3
_RE_EMOJI_LIKE = re.compile(r"\+1|<3|:\)|:\(|xD|XD")


@dataclass
class Highlight:
    """Один найденный хайлайт (диапазон смежных «горячих» минут)."""

    start_ts: datetime
    end_ts: datetime
    channel: str
    count: int
    reaction_count: int
    baseline: float
    spike_factor: float
    top_emotes: list[tuple[str, int]]
    sample_messages: list[dict]

    def to_dict(self) -> dict:
        return {
            "start_ts": self.start_ts.isoformat(timespec="seconds"),
            "end_ts": self.end_ts.isoformat(timespec="seconds"),
            "channel": self.channel,
            "count": self.count,
            "reaction_count": self.reaction_count,
            "baseline": round(self.baseline, 2),
            "spike_factor": round(self.spike_factor, 2),
            "top_emotes": [{"token": t, "count": c} for t, c in self.top_emotes],
            "sample_messages": self.sample_messages,
        }


# ---------- Парсинг входных строк ----------


def _parse_ts(ts: str | datetime) -> datetime | None:
    """SQLite TIMESTAMP DEFAULT CURRENT_TIMESTAMP даёт строку 'YYYY-MM-DD HH:MM:SS'."""
    if isinstance(ts, datetime):
        return ts
    if not ts:
        return None
    try:
        # SQLite формат: '2025-04-01 18:42:13' (UTC, без timezone)
        return datetime.fromisoformat(str(ts).replace("T", " "))
    except Exception:
        try:
            return datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


def _bucket_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def _count_reactions(text: str, reaction_set: set[str]) -> tuple[int, list[str]]:
    """Возвращает (общее_число_совпадений, список_токенов_по_порядку)."""
    found: list[str] = []
    for tok in _RE_TOKEN.findall(text):
        low = tok.lower()
        if low in reaction_set:
            found.append(low)
    for emoji_like in _RE_EMOJI_LIKE.findall(text):
        found.append(emoji_like.lower())
    return len(found), found


# ---------- Основная функция ----------


def detect_highlights(
    rows: Iterable[dict],
    *,
    window_sec: int = 60,
    min_count: int = 8,
    spike_factor: float = 2.0,
    baseline_window_min: int = 10,
    top_n: int = 20,
    sample_limit: int = 3,
    reaction_tokens: Sequence[str] | None = None,
) -> list[Highlight]:
    """Найти всплески реакции в чате.

    Алгоритм:
      1. Группируем сообщения в bucket'ы по ``window_sec`` (по умолчанию 1 минута)
         внутри каждого канала.
      2. Для каждого bucket'а считаем: общее число сообщений + число «реакций»
         (упоминаний токенов из ``reaction_tokens``).
      3. Скользящий baseline = медиана числа сообщений за предыдущие
         ``baseline_window_min`` минут (минимум — чтобы не делить на нули).
      4. Bucket помечается как «горячий», если ``count >= min_count`` и
         ``count >= baseline * spike_factor``.
      5. Смежные горячие bucket'ы (отстоящие < 2 минут) сливаются в один highlight.
      6. Для каждого highlight'а считаем top-эмоуты и берём 2-3 примерных
         сообщения с максимальной плотностью реакций.

    Параметры:
      window_sec: размер bucket'а в секундах (60 = 1 мин).
      min_count: минимальное абсолютное число сообщений в bucket'е.
      spike_factor: во сколько раз count должен быть выше baseline.
      baseline_window_min: окно для скользящей медианы (в минутах).
      top_n: сколько максимум highlight'ов вернуть.
      sample_limit: сколько примерных сообщений сохранять.
      reaction_tokens: список токенов-эмоутов (по умолчанию DEFAULT_REACTION_TOKENS).

    Возвращает список Highlight, отсортированный от самого «горячего» к холодному.
    """
    tokens = reaction_tokens or DEFAULT_REACTION_TOKENS
    reaction_set = {t.lower() for t in tokens}

    # ---- 1. Группировка ----
    by_channel: dict[str, dict[datetime, list[dict]]] = {}
    for row in rows:
        ts = _parse_ts(row.get("timestamp"))
        if ts is None:
            continue
        channel = (row.get("channel") or "").lstrip("#")
        if not channel:
            continue
        bucket = _bucket_minute(ts)
        # Округляем bucket до ближайшего window_sec (для нестандартных размеров)
        if window_sec != 60:
            sec_offset = (ts.minute * 60 + ts.second) - ((ts.minute * 60 + ts.second) % window_sec)
            bucket = ts.replace(minute=sec_offset // 60, second=sec_offset % 60, microsecond=0)
        by_channel.setdefault(channel, {}).setdefault(bucket, []).append(row)

    highlights: list[Highlight] = []
    for channel, buckets in by_channel.items():
        # Полный диапазон: от первого до последнего bucket'а с шагом 1 минута
        if not buckets:
            continue
        sorted_keys = sorted(buckets.keys())
        # Считаем counts только для существующих bucket'ов (отсутствующие — 0).
        counts: dict[datetime, int] = {k: len(v) for k, v in buckets.items()}

        # ---- 2/3. Поиск горячих bucket'ов ----
        hot_buckets: list[tuple[datetime, int, float]] = []
        for key in sorted_keys:
            cnt = counts[key]
            if cnt < min_count:
                continue
            # Baseline — медиана counts за предыдущие baseline_window_min минут
            window_start = key.timestamp() - baseline_window_min * 60
            prior = [
                counts[k] for k in sorted_keys
                if k < key and k.timestamp() >= window_start
            ]
            baseline = _median(prior) if prior else 1.0
            baseline = max(baseline, 1.0)
            if cnt >= baseline * spike_factor:
                hot_buckets.append((key, cnt, baseline))

        # ---- 4. Слияние смежных ----
        merged: list[list[tuple[datetime, int, float]]] = []
        for entry in hot_buckets:
            if merged and (entry[0] - merged[-1][-1][0]).total_seconds() <= 120:
                merged[-1].append(entry)
            else:
                merged.append([entry])

        # ---- 5/6. Финализация ----
        for group in merged:
            start_key = group[0][0]
            end_key = group[-1][0]
            total_count = sum(g[1] for g in group)
            avg_baseline = sum(g[2] for g in group) / len(group)
            spike = total_count / max(avg_baseline * len(group), 1.0)

            # Все сообщения внутри окна
            window_msgs: list[dict] = []
            for key, _cnt, _bl in group:
                window_msgs.extend(buckets[key])

            # top emotes
            emote_counter: Counter[str] = Counter()
            per_msg_score: list[tuple[int, dict]] = []
            for m in window_msgs:
                rcount, tokens_found = _count_reactions(m.get("message") or "", reaction_set)
                if tokens_found:
                    emote_counter.update(tokens_found)
                per_msg_score.append((rcount, m))

            top_emotes = emote_counter.most_common(5)
            reaction_total = sum(emote_counter.values())

            # 2-3 примера с максимальной плотностью реакций (или просто первые)
            per_msg_score.sort(key=lambda x: (-x[0], x[1].get("timestamp", "")))
            samples = []
            for _score, m in per_msg_score[:sample_limit]:
                samples.append({
                    "timestamp": str(m.get("timestamp", "")),
                    "author": m.get("author", ""),
                    "message": (m.get("message") or "")[:280],
                })

            highlights.append(Highlight(
                start_ts=start_key,
                end_ts=end_key,
                channel=channel,
                count=total_count,
                reaction_count=reaction_total,
                baseline=avg_baseline,
                spike_factor=spike,
                top_emotes=top_emotes,
                sample_messages=samples,
            ))

    # Сортируем по «горячести»: spike_factor * count
    highlights.sort(key=lambda h: (h.spike_factor * h.count, h.reaction_count), reverse=True)
    return highlights[:top_n]


# ---------- Утилиты ----------


def _median(values: Sequence[int | float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0
