"""v10.4.7 Wave 4.2 — Conversation threads (запоминать «темы» в чате).

Сейчас memory — это просто список фактов о viewer.
Здесь делаем threads: «тема про Elden Ring длилась 20 минут, в ней были user_a,
user_b, бот вмешался 3 раза».

При новом сообщении в этой теме — бот вспоминает контекст ВСЕЙ темы.

Дизайн:
- Пер-канал ThreadTracker хранит активные треды (TF-IDF центроид + участники).
- При новом сообщении считаем similarity с активными тредами; если cos > порога →
  присоединяемся, иначе открываем новый тред.
- Stale-тред (без активности >N минут) закрывается и архивируется в БД.
- `format_thread_context(thread)` → строка для prompt.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+", re.UNICODE)

# Стоп-слова: очень частые, не несут темы.
STOPWORDS = {
    "и", "в", "на", "что", "это", "не", "так", "как", "по", "из", "от", "до", "у",
    "о", "за", "же", "то", "бы", "the", "a", "an", "and", "or", "but", "is", "are",
    "to", "in", "of", "for", "with", "on", "at",
}


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    toks = [t.lower() for t in WORD_RE.findall(text) if len(t) > 1]
    return [t for t in toks if t not in STOPWORDS]


def _tf(tokens: Iterable[str]) -> dict[str, float]:
    c = Counter(tokens)
    if not c:
        return {}
    n = float(sum(c.values()))
    return {t: cnt / n for t, cnt in c.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class ConversationThread:
    """Активная тема обсуждения."""

    thread_id: str
    started_at: float
    last_at: float
    centroid: dict[str, float] = field(default_factory=dict)
    participants: set[str] = field(default_factory=set)
    bot_interventions: int = 0
    messages: list[tuple[float, str, str]] = field(default_factory=list)  # (ts, author, text)
    n_messages: int = 0
    top_keywords: list[str] = field(default_factory=list)

    def duration_sec(self) -> float:
        return max(0.0, self.last_at - self.started_at)

    def to_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "started_at": self.started_at,
            "last_at": self.last_at,
            "duration_sec": round(self.duration_sec(), 1),
            "participants": sorted(self.participants),
            "bot_interventions": self.bot_interventions,
            "n_messages": self.n_messages,
            "top_keywords": self.top_keywords,
        }


@dataclass
class ThreadTracker:
    """Per-channel state менеджера тредов."""

    similarity_threshold: float = 0.18
    stale_after_sec: float = 600.0  # 10 минут без активности — закрываем
    max_active_threads: int = 4
    threads: dict[str, ConversationThread] = field(default_factory=dict)
    archived: list[ConversationThread] = field(default_factory=list)
    _counter: int = 0

    def _new_id(self, now: float) -> str:
        self._counter += 1
        return f"thr_{int(now)}_{self._counter}"

    def _gc(self, now: float) -> None:
        """Закрываем stale-треды."""
        dead = [tid for tid, t in self.threads.items() if (now - t.last_at) > self.stale_after_sec]
        for tid in dead:
            self.archived.append(self.threads.pop(tid))
        if len(self.archived) > 50:
            self.archived = self.archived[-50:]

    def feed(self, author: str, text: str, now: float | None = None, is_bot_response: bool = False) -> ConversationThread | None:
        """Добавляет сообщение в подходящий тред (или создаёт новый).

        Возвращает текущий тред или None для совсем пустых сообщений.
        """
        now = now if now is not None else time.time()
        self._gc(now)

        toks = _tokenize(text)
        if not toks:
            return None
        tf = _tf(toks)

        # Ищем лучший подходящий тред
        best_tid: str | None = None
        best_sim = 0.0
        for tid, thr in self.threads.items():
            sim = cosine(tf, thr.centroid)
            if sim > best_sim:
                best_sim = sim
                best_tid = tid

        if best_tid and best_sim >= self.similarity_threshold:
            thr = self.threads[best_tid]
            # обновляем centroid (EMA-стиль)
            a = 0.7
            new_centroid: dict[str, float] = {}
            for t in set(tf) | set(thr.centroid):
                new_centroid[t] = a * thr.centroid.get(t, 0.0) + (1 - a) * tf.get(t, 0.0)
            thr.centroid = new_centroid
        else:
            # новый тред
            thr = ConversationThread(
                thread_id=self._new_id(now),
                started_at=now,
                last_at=now,
                centroid=dict(tf),
            )
            self.threads[thr.thread_id] = thr
            # лимитируем активные
            if len(self.threads) > self.max_active_threads:
                oldest = min(self.threads.values(), key=lambda x: x.last_at)
                self.archived.append(self.threads.pop(oldest.thread_id))

        thr.last_at = now
        thr.n_messages += 1
        if not is_bot_response:
            thr.participants.add(author)
        else:
            thr.bot_interventions += 1
        thr.messages.append((now, author, text[:200]))
        if len(thr.messages) > 30:
            thr.messages = thr.messages[-30:]
        # топ-keywords
        thr.top_keywords = [w for w, _ in sorted(thr.centroid.items(), key=lambda kv: -kv[1])[:5]]
        return thr

    def find_thread_for(self, text: str, now: float | None = None) -> ConversationThread | None:
        """Найти активный тред наиболее похожий на text (без вставки)."""
        now = now if now is not None else time.time()
        self._gc(now)
        toks = _tokenize(text)
        if not toks:
            return None
        tf = _tf(toks)
        best: ConversationThread | None = None
        best_sim = 0.0
        for thr in self.threads.values():
            sim = cosine(tf, thr.centroid)
            if sim > best_sim:
                best_sim = sim
                best = thr
        if best and best_sim >= self.similarity_threshold:
            return best
        return None

    def snapshot(self) -> dict:
        return {
            "active": [t.to_dict() for t in self.threads.values()],
            "archived_count": len(self.archived),
        }


def format_thread_context(thread: ConversationThread, max_messages: int = 6) -> str:
    """Возвращает блок-инструкцию для system prompt."""
    if not thread or not thread.messages:
        return ""
    kws = ", ".join(thread.top_keywords[:5]) or "(нет ключевых слов)"
    dur = int(thread.duration_sec() // 60)
    parts = sorted(thread.participants)[:6]
    lines = [
        f"[Тема: {kws}]",
        f"Длится {dur} мин, участники: {', '.join(parts) if parts else '—'}, бот вмешался: {thread.bot_interventions}.",
        "Последние реплики в теме:",
    ]
    for ts, author, text in thread.messages[-max_messages:]:
        lines.append(f"  {author}: {text}")
    return "\n".join(lines)
