"""v8: AI Quality — модули для улучшения качества чат-AI.

Шесть подмодулей, каждый pure-functional где возможно (для тестов):

- conversation_memory   — последние сообщения канала + user↔bot пары
- pre_classifier        — нужно ли вообще отвечать
- topic_extractor       — выделение темы для cooldown
- banned_topics_check   — проверка по списку запрещённых тем
- hallucination_guard   — regex-based чистка фраз про "ты сказал/делал"
- output_filter         — heuristic-фильтр (длина, caps, slurs)

Каждая функция чистая (берёт данные, возвращает данные) — без скрытого
обращения к БД. БД-обвязка живёт в `app/ai_quality_db.py`.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional

# ====== conversation_memory ======


@dataclass
class ChatMsg:
    author: str
    message: str
    is_bot: bool
    timestamp: str = ""

    def to_line(self) -> str:
        prefix = "🤖 " if self.is_bot else ""
        return f"{prefix}{self.author}: {self.message}"


def build_conversation_block(
    channel_msgs: Iterable[ChatMsg],
    user_pairs: Iterable[tuple[ChatMsg, ChatMsg]] = (),
    *,
    max_channel: int = 10,
    max_pairs: int = 3,
) -> str:
    """Формирует блок разговорного контекста для system_prompt.

    channel_msgs — обычные сообщения канала (включая прошлые ответы бота).
    user_pairs   — пары (user_msg, bot_msg) именно с текущим автором.
    """
    chan_list = list(channel_msgs)[-max_channel:]
    pair_list = list(user_pairs)[-max_pairs:]

    parts: list[str] = []
    if chan_list:
        parts.append("Последние сообщения чата:")
        parts.extend("  " + m.to_line() for m in chan_list)
    if pair_list:
        parts.append("")
        parts.append("История твоих ответов этому пользователю:")
        for u, b in pair_list:
            parts.append(f"  ↳ {u.to_line()}")
            parts.append(f"  ↳ {b.to_line()}")
    return "\n".join(parts).strip()


# ====== pre_classifier ======


@dataclass
class ClassifierDecision:
    should_reply: bool
    confidence: float
    reason: str


_QUESTION_RE = re.compile(r"[?\u2049\u061F]")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def classify_message(
    message: str,
    *,
    bot_nickname: str = "",
    trigger_keywords: Iterable[str] = (),
    seconds_since_last_chat_msg: float = 0.0,
    chat_gap_threshold: float = 30.0,
    min_confidence: float = 0.4,
    require_mention: bool = False,
) -> ClassifierDecision:
    """Эвристический pre-classifier.

    Возвращает решение «стоит ли отвечать» с confidence 0..1.
    Сигналы (баллы суммируются, потом нормализуются):
      - явное упоминание ника бота (+0.55)
      - сообщение оканчивается на ? и достаточно длинное (+0.25)
      - совпадает ключевое слово триггера (+0.30)
      - длинная пауза в чате (+0.15)
    Штрафы:
      - сообщение слишком короткое (1-2 символа) → -0.20
      - сообщение это просто URL → -0.30

    Если require_mention=True — отвечаем только если нашли упоминание.
    """
    if not message or not message.strip():
        return ClassifierDecision(False, 0.0, "empty_message")

    msg = message.strip()
    msg_lower = msg.lower()
    score = 0.0
    reasons: list[str] = []

    if bot_nickname and bot_nickname.lower() in msg_lower:
        score += 0.55
        reasons.append("mention")

    if require_mention and "mention" not in reasons:
        return ClassifierDecision(False, 0.0, "no_mention_required")

    if len(msg) >= 4 and _QUESTION_RE.search(msg):
        score += 0.25
        reasons.append("question")

    for kw in trigger_keywords:
        if kw and kw.lower() in msg_lower:
            score += 0.30
            reasons.append(f"trigger:{kw}")
            break

    if seconds_since_last_chat_msg >= chat_gap_threshold:
        score += 0.15
        reasons.append("chat_gap")

    if len(msg) <= 2:
        score -= 0.20
        reasons.append("too_short")

    if _URL_RE.fullmatch(msg):
        score -= 0.30
        reasons.append("only_url")

    score = max(0.0, min(1.0, score))
    decision = score >= min_confidence
    return ClassifierDecision(decision, round(score, 3), "+".join(reasons) or "no_signal")


# ====== topic_extractor / cooldown ======


_STOPWORDS_RU = {
    "и", "в", "на", "не", "что", "как", "это", "так", "но", "у", "да",
    "же", "ну", "ты", "я", "он", "она", "они", "мы", "вы", "если",
    "or", "the", "a", "an", "is", "are", "to", "of", "for", "and",
    "ну", "вот", "ах", "ой", "эх", "хм", "ага", "уже", "там", "тут",
    "по", "от", "до", "за", "из", "со", "о", "об", "при", "с",
}

_TOKEN_RE = re.compile(r"[\w']{2,}", re.UNICODE)


def extract_topic_tokens(text: str, *, top_n: int = 3) -> list[str]:
    """Выделяет top-N значимых слов как «тему» сообщения.

    Используется для cooldown per-topic: если бот недавно отвечал на ту же
    тему — суп­рессим повтор.
    """
    tokens = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    tokens = [t for t in tokens if t not in _STOPWORDS_RU and len(t) > 2]
    if not tokens:
        return []
    counts = Counter(tokens)
    return [tok for tok, _ in counts.most_common(top_n)]


def topics_overlap(a: Iterable[str], b: Iterable[str], *, min_shared: int = 2) -> bool:
    """True если у двух тем достаточно общих токенов."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return False
    return len(sa & sb) >= min_shared


# ====== banned_topics ======


@dataclass
class BannedTopicHit:
    pattern_id: int
    pattern: str
    fallback: str
    mode: str  # 'silent' | 'fallback' | 'redirect'


def check_banned_topics(text: str, banned: Iterable[dict]) -> Optional[BannedTopicHit]:
    """Проверяет текст против списка banned_topics.

    Каждая запись — dict с {id, pattern, fallback, mode, enabled}.
    pattern может быть либо набором ключевых слов через `;` либо regex
    с префиксом `re:`.
    """
    if not text:
        return None
    text_lower = text.lower()
    for item in banned:
        if not item.get("enabled", 1):
            continue
        pattern = (item.get("pattern") or "").strip()
        if not pattern:
            continue
        try:
            if pattern.startswith("re:"):
                rgx = re.compile(pattern[3:], re.IGNORECASE | re.UNICODE)
                if rgx.search(text):
                    return BannedTopicHit(
                        pattern_id=int(item.get("id") or 0),
                        pattern=pattern,
                        fallback=item.get("fallback") or "",
                        mode=item.get("mode") or "silent",
                    )
            else:
                # split by ; or , — все слова должны встретиться чтобы триггернуть
                # (более избирательно чем "хоть одно")
                parts = [p.strip().lower() for p in re.split(r"[;,]", pattern) if p.strip()]
                if parts and all(p in text_lower for p in parts):
                    return BannedTopicHit(
                        pattern_id=int(item.get("id") or 0),
                        pattern=pattern,
                        fallback=item.get("fallback") or "",
                        mode=item.get("mode") or "silent",
                    )
        except re.error:
            continue
    return None


# ====== hallucination_guard ======


_HALLUCINATION_PATTERNS_RU = [
    re.compile(r"\b(?:ты\s+(?:сказал|говорил|писал|упоминал|делал|сделал|был|была|играл|играла))\b", re.IGNORECASE | re.UNICODE),
    re.compile(r"\b(?:вчера|на\s+прошлом\s+стриме|в\s+прошлый\s+раз|раньше\s+ты)\b", re.IGNORECASE | re.UNICODE),
    re.compile(r"\b(?:я\s+помню,?\s+как\s+ты)\b", re.IGNORECASE | re.UNICODE),
]

_HALLUCINATION_PATTERNS_EN = [
    re.compile(r"\b(?:you\s+(?:said|told|mentioned|did|were|played|wrote))\b", re.IGNORECASE),
    re.compile(r"\b(?:yesterday|last\s+stream|earlier\s+you|i\s+remember\s+you)\b", re.IGNORECASE),
]


@dataclass
class HallucinationCheck:
    safe: bool
    matches: list[str]
    cleaned_text: str


def check_hallucination(
    bot_reply: str,
    *,
    user_facts: Iterable[str] = (),
    user_history_text: str = "",
    strict: bool = True,
) -> HallucinationCheck:
    """Проверяет ответ бота на «галлюцинирующие» отсылки к юзеру.

    Если бот написал «ты сказал X» — пробуем найти X (или ключевые слова из X)
    в user_facts или user_history_text. Если не нашли — помечаем небезопасным
    и в strict режиме вырезаем эту фразу из ответа.
    """
    if not bot_reply:
        return HallucinationCheck(True, [], bot_reply)

    matches: list[str] = []
    cleaned = bot_reply
    facts_text = " ".join(user_facts).lower() + " " + (user_history_text or "").lower()

    patterns = _HALLUCINATION_PATTERNS_RU + _HALLUCINATION_PATTERNS_EN
    for rgx in patterns:
        for m in rgx.finditer(bot_reply):
            matches.append(m.group(0))

    if not matches:
        return HallucinationCheck(True, [], bot_reply)

    # Если у нас вообще нет фактов и нет истории — всё это галлюцинация
    has_evidence = bool(facts_text.strip())

    if not has_evidence and strict:
        # Вырезаем предложения с подозрительными фразами
        sentences = re.split(r"(?<=[.!?])\s+", bot_reply)
        kept = []
        for s in sentences:
            if any(rgx.search(s) for rgx in patterns):
                continue
            kept.append(s)
        cleaned = " ".join(kept).strip()
        return HallucinationCheck(False, matches, cleaned)

    # Если факты есть — оставляем как есть, но помечаем
    return HallucinationCheck(has_evidence, matches, bot_reply)


# ====== output_filter ======


_SLURS_PATTERNS = [
    re.compile(r"\b(?:n[i1]gg[e3]r|f[a4]gg[o0]t|k[a4]ffir|tr[a4]nn[i1]e)\b", re.IGNORECASE),
]

# Очень мягкий список — на твич более жёсткие правила, но мы не хотим
# запрещать обычные ругательства. Это только для action-уровня хейта.


@dataclass
class FilterReport:
    safe: bool
    reasons: list[str]
    suggested: str  # отредактированная или пустая строка для silent


def filter_output_heuristic(
    text: str,
    *,
    max_length: int = 450,
    max_caps_pct: float = 0.85,
    forbid_links: bool = False,
    min_length: int = 1,
) -> FilterReport:
    """Heuristic-проверки безопасности вывода бота.

    Возвращает FilterReport. Если safe=False, suggested может быть пустой
    строкой (=> не отправлять) или подрезанной/очищенной версией.
    """
    if not text or not text.strip():
        return FilterReport(False, ["empty"], "")

    cleaned = text.strip()
    reasons: list[str] = []

    if len(cleaned) < min_length:
        reasons.append(f"too_short<{min_length}")

    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 1].rstrip() + "…"
        reasons.append("trimmed")

    # CAPS check (только для длинных сообщений > 12 символов)
    letters = [c for c in cleaned if c.isalpha()]
    if len(letters) > 12:
        caps = sum(1 for c in letters if c.isupper())
        ratio = caps / max(1, len(letters))
        if ratio > max_caps_pct:
            cleaned = cleaned.lower()
            reasons.append(f"caps>{int(max_caps_pct * 100)}%")

    # Slurs
    for rgx in _SLURS_PATTERNS:
        if rgx.search(cleaned):
            reasons.append("slur_detected")
            return FilterReport(False, reasons, "")

    # Links
    if forbid_links and _URL_RE.search(cleaned):
        cleaned = _URL_RE.sub("[ссылка]", cleaned)
        reasons.append("links_stripped")

    # Если только trimmed/links_stripped — всё ещё считается safe
    soft = {"trimmed", "links_stripped"}
    hard_problems = [r for r in reasons if r not in soft]
    safe = not hard_problems
    return FilterReport(safe, reasons, cleaned)


# ====== streamer_kb retrieval (RAG without embeddings) ======


def score_kb_entry(entry: dict, query: str) -> float:
    """TF-IDF-light: сколько уникальных слов запроса встречается в entry.

    entry = {topic, content, tags, priority(int)}
    query = строка от пользователя
    Возвращает score 0..1+ (priority может пробить 1.0).
    """
    if not query:
        return 0.0
    q_tokens = set(t.lower() for t in _TOKEN_RE.findall(query) if len(t) > 2)
    if not q_tokens:
        return 0.0
    haystack = " ".join([
        entry.get("topic", ""),
        entry.get("content", ""),
        entry.get("tags", ""),
    ]).lower()
    h_tokens = set(t for t in _TOKEN_RE.findall(haystack) if len(t) > 2)
    if not h_tokens:
        return 0.0
    overlap = q_tokens & h_tokens
    if not overlap:
        return 0.0
    base = len(overlap) / len(q_tokens)
    priority_boost = (entry.get("priority", 5) or 5) / 50.0
    # Топик-совпадение бонус
    topic_l = (entry.get("topic", "") or "").lower()
    topic_boost = 0.3 if any(t in topic_l for t in q_tokens) else 0.0
    return round(base + priority_boost + topic_boost, 3)


def retrieve_kb(query: str, entries: Iterable[dict], *, top_k: int = 3, min_score: float = 0.15) -> list[dict]:
    """Возвращает топ-K записей знаний для запроса."""
    scored = []
    for e in entries:
        if not e.get("enabled", 1):
            continue
        s = score_kb_entry(e, query)
        if s >= min_score:
            scored.append((s, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**e, "_score": s} for s, e in scored[:top_k]]


def format_kb_block(entries: list[dict]) -> str:
    """Превращает топ-K записей в блок для system_prompt."""
    if not entries:
        return ""
    parts = ["Информация о стримере (используй только если уместно, не цитируй дословно):"]
    for e in entries:
        topic = e.get("topic", "").strip()
        content = e.get("content", "").strip()
        if topic and content:
            parts.append(f"  • {topic}: {content}")
        elif content:
            parts.append(f"  • {content}")
    return "\n".join(parts)


# ====== few-shot style ======


def format_few_shot_block(examples: Iterable[dict], *, max_examples: int = 5) -> str:
    """Форматирует примеры стиля стримера в блок для system_prompt."""
    items = [e for e in list(examples) if (e.get("message") or "").strip()][:max_examples]
    if not items:
        return ""
    parts = ["Образцы стиля стримера (повторяй длину/тон/сленг, но не копируй дословно):"]
    for e in items:
        msg = (e.get("message") or "").strip().replace("\n", " ")
        if len(msg) > 200:
            msg = msg[:197] + "…"
        parts.append(f"  → {msg}")
    return "\n".join(parts)


# ====== A/B variant selection ======


def pick_variant(variants: list[dict]) -> Optional[dict]:
    """Выбирает вариант по weight через cumulative distribution.

    variants = [{id, label, system_prompt, weight, count, likes, dislikes, enabled}]
    Возвращает один из enabled вариантов или None.
    """
    import random

    enabled = [v for v in variants if v.get("enabled", 1) and (v.get("weight") or 0) > 0]
    if not enabled:
        return None
    total = sum(int(v.get("weight") or 0) for v in enabled)
    if total <= 0:
        return enabled[0]
    pick = random.uniform(0, total)
    acc = 0.0
    for v in enabled:
        acc += int(v.get("weight") or 0)
        if pick <= acc:
            return v
    return enabled[-1]


def variant_score(variant: dict) -> float:
    """Простой score для сравнения вариантов: (likes - dislikes) / sqrt(count+1)."""
    likes = int(variant.get("likes") or 0)
    dislikes = int(variant.get("dislikes") or 0)
    count = int(variant.get("count") or 0)
    raw = likes - dislikes
    return round(raw / math.sqrt(count + 1), 3)


# ====== memory facts с confidence + decay ======


def normalize_fact_entry(raw, *, default_confidence: float = 0.8) -> dict:
    """Превращает старую строку или dict в каноничный формат.

    Каноничный: {fact, confidence, priority, last_seen, expires_at,
    source_msg_id, confirmed, source}.
    ``priority`` and ``expires_at`` are optional additions to the old JSON format.
    ``confirmed`` (bool) — факт подтверждён владельцем (живёт дольше,
    идёт в prompt первым).
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(raw, str):
        return {
            "fact": raw.strip(),
            "confidence": default_confidence,
            "priority": 50,
            "last_seen": now,
            "expires_at": None,
            "source_msg_id": None,
            "confirmed": False,
            "source": "auto",
        }
    if isinstance(raw, dict):
        try:
            priority = max(0, min(100, int(raw.get("priority", 50))))
        except (TypeError, ValueError):
            priority = 50
        return {
            "fact": str(raw.get("fact") or "").strip(),
            "confidence": float(raw.get("confidence", default_confidence) or default_confidence),
            "priority": priority,
            "last_seen": str(raw.get("last_seen") or now),
            "expires_at": str(raw["expires_at"]) if raw.get("expires_at") else None,
            "source_msg_id": raw.get("source_msg_id"),
            "confirmed": bool(raw.get("confirmed", False)),
            "source": str(raw.get("source") or "auto")[:32],
        }
    return {
        "fact": str(raw),
        "confidence": default_confidence,
        "priority": 50,
        "last_seen": now,
        "expires_at": None,
        "source_msg_id": None,
        "confirmed": False,
        "source": "auto",
    }


def decay_facts(facts: Iterable, *, half_life_days: int = 30, drop_below: float = 0.1) -> list[dict]:
    """Применяет затухание: confidence уменьшается с возрастом.

    После каждых `half_life_days` дней не-обновления — confidence × 0.5.
    Факты с confidence < drop_below — удаляются.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    result = []
    for raw in facts:
        f = normalize_fact_entry(raw)
        if not f["fact"]:
            continue
        if f.get("expires_at"):
            try:
                expires = datetime.fromisoformat(str(f["expires_at"]).replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= now:
                    continue
            except ValueError:
                pass  # Invalid legacy metadata must not hide an otherwise valid fact.
        try:
            ls = datetime.strptime(f["last_seen"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            ls = now
        age_days = max(0.0, (now - ls).total_seconds() / 86400.0)
        if half_life_days > 0:
            decay = 0.5 ** (age_days / half_life_days)
        else:
            decay = 1.0
        new_conf = round(f["confidence"] * decay, 3)
        if new_conf < drop_below:
            continue
        f["confidence"] = new_conf
        result.append(f)
    return result


def merge_fact(existing: list[dict], new_fact: str, *, source_msg_id: Optional[int] = None) -> list[dict]:
    """Добавляет/обновляет факт в списке.

    Если такой факт уже есть (case-insensitive substring match) — bump'аем confidence
    и обновляем last_seen. Иначе добавляем как новый с conf=0.8.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    new_fact = (new_fact or "").strip()
    if not new_fact:
        return list(existing)

    new_lower = new_fact.lower()
    found = False
    out: list[dict] = []
    for raw in existing:
        f = normalize_fact_entry(raw)
        if not f["fact"]:
            continue
        if not found and (new_lower in f["fact"].lower() or f["fact"].lower() in new_lower):
            f["confidence"] = min(1.0, round(f["confidence"] + 0.10, 3))
            f["last_seen"] = now
            if source_msg_id is not None:
                f["source_msg_id"] = source_msg_id
            # Если новый факт длиннее (более информативен) — заменяем формулировку
            if len(new_fact) > len(f["fact"]) + 5:
                f["fact"] = new_fact
            found = True
        out.append(f)

    if not found:
        out.append({
            "fact": new_fact,
            "confidence": 0.8,
            "priority": 50,
            "last_seen": now,
            "expires_at": None,
            "source_msg_id": source_msg_id,
        })
    return out


def format_facts_for_prompt(
    facts: list[dict], *, min_confidence: float = 0.3, max_facts: int = 8, max_chars: int = 1200
) -> str:
    """Форматирует действующие факты по приоритету, не раздувая prompt.

    Подтверждённые факты (``confirmed=True``) идут первыми и получают
    бонус к effective priority (100 → 100).
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    candidates = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        if f.get("confidence", 1.0) < min_confidence:
            continue
        expires_at = f.get("expires_at")
        if expires_at:
            try:
                expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= now:
                    continue
            except ValueError:
                pass
        fact = (f.get("fact") or "").strip()
        if fact:
            try:
                priority = max(0, min(100, int(f.get("priority", 50))))
            except (TypeError, ValueError):
                priority = 50
            confirmed = bool(f.get("confirmed"))
            if confirmed:
                # подтверждённые бустим приоритет до максимума
                effective_priority = 100
            else:
                effective_priority = priority
            candidates.append((effective_priority, float(f.get("confidence", 1.0) or 0), fact))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    items = []
    used = 0
    for _, _, fact in candidates[:max(0, max_facts)]:
        if used + len(fact) + (2 if items else 0) > max_chars:
            break
        items.append(fact)
        used += len(fact) + (2 if len(items) > 1 else 0)
    return "; ".join(items)
