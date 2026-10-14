"""Anti-detection: маскируем бота под живого человека.

Модуль stateless / pure-functions, чтобы его было легко юнит-тестировать.
Используется из ``chat_analyzer._generate_and_send``.

Фичи:
* ``compute_self_similarity`` — шинглы N=3 между новым ответом и
  последними N отправленными ботом. Возвращает 0..1.
  Если выше порога — caller перегенерирует или скипает.
* ``humanized_delay_seconds`` — гауссова задержка с зависимостью от
  длины сообщения (бот «печатает»).
* ``apply_typo`` — редко вносит правдоподобную опечатку (соседняя
  клавиша на QWERTY). Используется опционально, по флагу.
* ``looks_like_bot`` — простая эвристика: подозрительный ник + повтор
  фраз. Чтобы бот не отвечал другим ботам и не разгонял спам-петли.

Все функции детерминированы при заданном ``random.Random`` (нужно для
юнит-тестов): большинство принимает опциональный ``rng``.
"""

from __future__ import annotations

import math
import random
import re
import string
from dataclasses import dataclass
from typing import Iterable


# ---- self-similarity ----------------------------------------------------

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def _shingles(text: str, n: int) -> set[tuple[str, ...]]:
    tokens = _tokenize(text)
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def compute_self_similarity(new_text: str, recent_texts: Iterable[str], *, n: int = 2) -> float:
    """Возвращает максимум Jaccard-схожести между ``new_text`` и любым
    из ``recent_texts``. 0 = ничего общего, 1 = идентично.

    Используем bigram-шинглы по дефолту (короткие реплики чата не дают
    нормально работать N=3). Для дополнительной устойчивости сравниваем
    ещё и multi-set токенов и берём максимум.
    """
    new_sh = _shingles(new_text, n)
    new_tokens = set(_tokenize(new_text))
    if not new_sh:
        return 0.0

    best = 0.0
    for old in recent_texts:
        old_sh = _shingles(old, n)
        old_tokens = set(_tokenize(old))
        if not old_sh:
            continue
        jacc_sh = _jaccard(new_sh, old_sh)
        jacc_tok = _jaccard(new_tokens, old_tokens)
        # Берём средневзвешенное (shingles важнее токенов 2:1).
        jacc = (2 * jacc_sh + jacc_tok) / 3
        if jacc > best:
            best = jacc
    return best


# ---- humanized delay ---------------------------------------------------


def humanized_delay_seconds(
    text: str,
    base: float = 1.2,
    per_char: float = 0.04,
    sigma: float = 0.35,
    cap: float = 8.0,
    rng: random.Random | None = None,
) -> float:
    """Сколько секунд «подождать перед отправкой».

    Имитируем «набор» сообщения: длинные дольше. Сверху Gauss-шум, чтобы
    не было ровных интервалов. Ограничено сверху ``cap`` секунд.
    """
    rng = rng or random
    n = len(text or "")
    mean = base + per_char * n
    delay = rng.gauss(mean, max(sigma, 0.01))
    if delay < 0.2:
        delay = 0.2
    if delay > cap:
        delay = cap
    return delay


# ---- typo simulation ---------------------------------------------------

# Соседи на QWERTY. Только нижний регистр — для типовых опечаток.
_QWERTY_NEIGHBORS = {
    "q": "wa",
    "w": "qeas",
    "e": "wrsd",
    "r": "etdf",
    "t": "ryfg",
    "y": "tugh",
    "u": "yihj",
    "i": "uojk",
    "o": "ipkl",
    "p": "ol",
    "a": "qwsz",
    "s": "awedxz",
    "d": "serfcx",
    "f": "drtgvc",
    "g": "ftyhbv",
    "h": "gyujnb",
    "j": "huikmn",
    "k": "jiolm",
    "l": "kop",
    "z": "asx",
    "x": "zsdc",
    "c": "xdfv",
    "v": "cfgb",
    "b": "vghn",
    "n": "bhjm",
    "m": "njk",
}


@dataclass
class TypoConfig:
    rate: float = 0.05  # вероятность опечатки на сообщение (0..1).
    max_typos_per_msg: int = 1
    min_length: int = 8  # на коротких сообщениях не косячим.


def apply_typo(text: str, cfg: TypoConfig, rng: random.Random | None = None) -> str:
    """С шансом ``cfg.rate`` вносим до ``cfg.max_typos_per_msg`` опечаток."""
    rng = rng or random
    if not text or len(text) < cfg.min_length:
        return text
    if rng.random() >= cfg.rate:
        return text

    chars = list(text)
    typos = 0
    # Список индексов букв (не пробелы/знаки), которые можем испортить.
    candidates = [i for i, c in enumerate(chars) if c.lower() in _QWERTY_NEIGHBORS]
    rng.shuffle(candidates)
    for idx in candidates:
        if typos >= cfg.max_typos_per_msg:
            break
        c = chars[idx]
        lower = c.lower()
        neighbors = _QWERTY_NEIGHBORS.get(lower, "")
        if not neighbors:
            continue
        new = rng.choice(neighbors)
        chars[idx] = new.upper() if c.isupper() else new
        typos += 1
    return "".join(chars)


# ---- bot detection -----------------------------------------------------

_BOT_NICK_RE = re.compile(r"(?:bot|nightbot|streamelements|moobot|fossabot|wizebot|stay_hydrated|streamlabs)", re.I)
_BOT_PHRASE_RE = re.compile(
    r"(?:!command|^\s*\$\w+|^\s*\.\w+|"
    r"is being followed|enjoy the stream|added.*?to.*?queue|"
    r"^\s*\[bot\]|^\s*\[server\])",
    re.I,
)


def looks_like_bot(username: str, message: str = "") -> bool:
    """Эвристика: похоже ли что отправитель — другой бот?

    Простая. Срабатывает на популярные сервисные ники (Nightbot,
    StreamElements, etc) и на типичные паттерны команд / служебных
    объявлений. Цель — чтобы наш бот не вступал в диалог с другим
    ботом и не разгонял спам-петлю.
    """
    if not username:
        return False
    if _BOT_NICK_RE.search(username):
        return True
    if message and _BOT_PHRASE_RE.search(message):
        return True
    return False


# ---- helpers -----------------------------------------------------------


def estimate_chars_per_second(typed_chars: int, elapsed_sec: float) -> float:
    """Безопасный divider — для метрик/будущих эвристик."""
    if elapsed_sec <= 0:
        return 0.0
    return typed_chars / elapsed_sec


__all__ = [
    "TypoConfig",
    "apply_typo",
    "compute_self_similarity",
    "estimate_chars_per_second",
    "humanized_delay_seconds",
    "looks_like_bot",
]
