"""Шум-эвристика чата — вынесено из app/chat_analyzer.py (P5-сплит, PLAN.md).

Эвристика: коротенькие/спам-эмоты/реакции-без-смысла сообщения, чтобы AI смотрел
на содержательные реплики, а не на стену из ``KEKW LUL Pog +1 ???``.
"""
import re

# Regex для определения "шумовых" сообщений: одни эмоды/реакции, без полезной информации.
# Twitch и BTTV/FFZ-эмоды — заглавные слова без пробелов: KEKW, LULW, OMEGALUL, Pog, Kappa.
_EMOTE_WORD_RE = re.compile(r"^[A-Z][A-Za-z0-9_]{1,30}$")
_PUNCT_ONLY_RE = re.compile(r"^[\W_+]+$", re.UNICODE)
_NOISE_PHRASES = {
    "+", "++", "+1", "?", "??", "!", "!!", "lol", "lul", "kek",
    "лол", "лул", "ор", "кек", "хех", "ха", "ахах", "ахаха", "хах",
    "сяб", "ок", "+2", "f", "F",
}


def _is_noise_message(text: str) -> bool:
    """Эвристика: коротенькое/спам-эмоты/реакция-без-смысла сообщение.

    Используется при сборке контекста для AI — чтобы он смотрел на содержательные
    реплики, а не на стену из ``KEKW LUL Pog +1 ???``.
    """
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < 2:
        return True
    if _PUNCT_ONLY_RE.match(stripped):
        return True
    if stripped.lower() in _NOISE_PHRASES:
        return True
    tokens = stripped.split()
    if tokens and all(_EMOTE_WORD_RE.match(t) or t.lower() in _NOISE_PHRASES for t in tokens):
        return True
    return False
