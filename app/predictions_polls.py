"""Auto-vote в Twitch Predictions / Polls.

Идея:
  - подписка на EventSub события channel.poll.begin и channel.prediction.begin;
  - на событие — AI выбирает вариант на основе текста вопроса/опций;
  - голос отправляется через Helix API (POST /helix/predictions/predict, /helix/polls/vote).

NB: API голосования за predictions требует user-token голосующего (бота), не broadcaster-token.
Для polls — то же. Поэтому это работает только если у бота есть валидный user-token
с нужным scope (`channel:manage:predictions` для proxy/мониторинга? нет — для голосования
требуется лишь обычный user-token с channel-points-scope, по которому Twitch разрешает
тратить points).

В этой реализации мы:
  - детектим события (handler в server.py);
  - формируем prompt → ai_service.generate_text → парсим выбор;
  - кладём голос в очередь (callback на оплату points / poll-vote endpoint);
  - если ключи/scopes отсутствуют — просто логируем выбор (dry-run).

Pure-функции — выбор варианта по AI-ответу + парсинг — легко тестируются.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable

try:
    from app.ai_service import ai_service  # type: ignore
except Exception:  # pragma: no cover
    ai_service = None  # type: ignore


# --- pure helpers ----------------------------------------------------------


def normalize_choice(text: str) -> str:
    return (text or "").strip().lower()


def parse_choice_index(
    ai_reply: str, choices: list[str], *, default_idx: int | None = None
) -> int | None:
    """Парсит ответ AI → индекс выбранной опции.

    Понимает форматы:
      - "1" или "1)" или "вариант 1" → idx=0
      - имя опции (case-insensitive substring) → idx
      - "yes" / "no" → 0 / 1 если две опции
      - default_idx если ничего не подошло
    """
    if not ai_reply or not choices:
        return default_idx
    reply = ai_reply.strip().lower()
    # 1) explicit digit
    m = re.search(r"\b([1-9])\b", reply)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(choices):
            return idx
    # 2) substring match по тексту опции
    best_idx = None
    best_len = 0
    for i, c in enumerate(choices):
        cn = normalize_choice(c)
        if cn and cn in reply and len(cn) > best_len:
            best_idx = i
            best_len = len(cn)
    if best_idx is not None:
        return best_idx
    # 3) yes/no для бинарных
    if len(choices) == 2:
        if any(w in reply for w in ("yes", "да", "true", "за", "буду")):
            return 0
        if any(w in reply for w in ("no", "нет", "false", "против", "не буду")):
            return 1
    return default_idx


def build_vote_prompt(question: str, choices: list[str], *, channel: str = "", style: str = "casual") -> str:
    """Промпт для AI: выбрать вариант. AI должен ответить только номером опции."""
    chs = [f"  {i+1}. {c}" for i, c in enumerate(choices)]
    extra = ""
    if channel:
        extra = f"\nКанал: {channel}"
    return (
        f"Ты обычный зритель Twitch. Стример провёл голосование.{extra}\n"
        f"Вопрос: {question}\n"
        f"Варианты:\n" + "\n".join(chs) + "\n\n"
        f"Какой вариант ты выберешь как зритель? Ответь одним числом (1-{len(choices)}). "
        f"Можешь коротко пояснить, но первое слово — число."
    )


def fallback_random_choice(choices: list[str], *, rng=None) -> int:
    """Если AI недоступен — рандомный выбор."""
    import random as _r

    if not choices:
        return -1
    rng = rng or _r.Random()
    return rng.randint(0, len(choices) - 1)


def is_obvious_loaded_question(question: str) -> bool:
    """Эвристика: если вопрос явно подразумевает один ответ ("умру?", "выиграю?")
    → бот должен поддержать стримера (выбрать первый вариант).
    """
    q = (question or "").lower()
    triggers = (
        "выиграю", "одержу", "пройду босса", "вынесу", "победа",
        "я смогу", "получится", "хайп", "пинага",
    )
    return any(t in q for t in triggers)


# --- stateful ------------------------------------------------------------


@dataclass
class VoteDecision:
    """Результат решения о голосовании."""

    choice_idx: int = -1
    choice_text: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    used_fallback: bool = False

    def to_dict(self) -> dict:
        return {
            "choice_idx": self.choice_idx,
            "choice_text": self.choice_text,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "used_fallback": self.used_fallback,
        }


async def decide_vote(
    question: str,
    choices: list[str],
    *,
    channel: str = "",
    style: str = "casual",
    rng=None,
    ai_callback=None,
) -> VoteDecision:
    """Возвращает VoteDecision. ai_callback — async callable(prompt) → str.

    Если ai_callback не передан и ai_service доступен — используется он.
    Если AI недоступен или вернул мусор — fallback на случайный выбор.
    """
    if not choices:
        return VoteDecision(choice_idx=-1, used_fallback=True, reasoning="no choices")

    # 1) Тривиальный кейс — loaded question → support streamer.
    if is_obvious_loaded_question(question):
        return VoteDecision(
            choice_idx=0,
            choice_text=choices[0],
            confidence=0.9,
            reasoning="loaded question → support",
        )

    callable_ai = ai_callback
    if callable_ai is None and ai_service is not None:
        async def _wrapped(prompt: str) -> str:
            try:
                return await ai_service.generate_text(prompt=prompt, system="", max_tokens=120)  # type: ignore[attr-defined]
            except Exception:
                return ""

        callable_ai = _wrapped

    reply = ""
    if callable_ai is not None:
        try:
            reply = await callable_ai(build_vote_prompt(question, choices, channel=channel, style=style))
        except Exception:
            reply = ""

    idx = parse_choice_index(reply, choices, default_idx=None)
    if idx is None:
        idx = fallback_random_choice(choices, rng=rng)
        return VoteDecision(
            choice_idx=idx,
            choice_text=choices[idx] if 0 <= idx < len(choices) else "",
            confidence=0.1,
            reasoning="ai response unparseable → random",
            used_fallback=True,
        )

    return VoteDecision(
        choice_idx=idx,
        choice_text=choices[idx],
        confidence=0.7,
        reasoning=(reply or "")[:200],
        used_fallback=False,
    )


def extract_question(payload: dict) -> str:
    """Извлекает заголовок poll/prediction из EventSub-payload."""
    e = serialize_event(payload)
    return e.get("title") or ""


def extract_choices(payload: dict) -> list[str]:
    """Возвращает плоский список title-ов вариантов."""
    e = serialize_event(payload)
    return [c["title"] for c in e.get("choices", []) if isinstance(c, dict) and c.get("title")]


def format_decision_for_chat(event_type: str, decision: "VoteDecision", *, dry_run: bool = True) -> str:
    """Формирует строку для лога/чата."""
    kind = "poll" if "poll" in event_type else "prediction"
    prefix = "DRY-RUN " if dry_run else ""
    return f"{prefix}{kind} vote: «{decision.choice_text}» (conf={decision.confidence:.2f})"


def serialize_event(payload: dict) -> dict:
    """Нормализует EventSub-payload в простую структуру.

    Поддерживает channel.poll.begin и channel.prediction.begin.
    """
    if not payload or not isinstance(payload, dict):
        return {}
    event = payload.get("event") or payload
    out = {
        "type": (payload.get("subscription") or {}).get("type") or event.get("type") or "",
        "channel": event.get("broadcaster_user_name") or event.get("broadcaster_user_login") or "",
        "id": event.get("id") or "",
        "title": event.get("title") or "",
        "choices": [],
    }
    # poll → choices[*].title
    raw_choices = event.get("choices") or []
    # prediction → outcomes[*].title
    if not raw_choices:
        raw_choices = event.get("outcomes") or []
    for c in raw_choices:
        if isinstance(c, dict):
            out["choices"].append({
                "id": c.get("id") or "",
                "title": c.get("title") or "",
            })
    return out
