"""Per-game vocabulary switcher.

Подсовываем боту словарь игровых терминов в зависимости от того, во что играет стример
(определяется через Helix `channel.game_name`).

Если категория не распознана — пустой блок (не ломаем поведение).

Pure functions — легко тестируется.
"""

from __future__ import annotations

import re
from typing import Iterable


# Дефолтные категории. Можно расширить через UI / БД, но это уже из коробки покрывает 80% Twitch-каталога.
DEFAULT_GAME_CATEGORIES: dict[str, dict] = {
    "souls": {
        "match": [
            "dark souls", "elden ring", "bloodborne", "sekiro", "lies of p",
            "demon's souls", "demon souls", "nioh", "lords of the fallen",
        ],
        "vocab": [
            "git gud", "you died", "praise the sun", "хардкор",
            "босс зажал", "опять помер", "перекат — твой друг", "урон в спину",
        ],
        "tone": "немного дразнящий, фанат сложных игр, иронит на смерти",
    },
    "moba": {
        "match": [
            "dota 2", "dota", "league of legends", "lol", "heroes of the storm",
            "smite", "predecessor",
        ],
        "vocab": [
            "репорт мид", "русские раки", "мид по флеш", "ганк топ",
            "крип-стек", "руна-варда", "лейт-стадия", "тип-3", "5в5", "афк-фарм",
        ],
        "tone": "слегка токсичный, как обычный донный mid-laner",
    },
    "fps": {
        "match": [
            "counter-strike", "cs2", "cs:go", "csgo", "valorant", "call of duty",
            "apex legends", "overwatch", "rainbow six", "battlefield", "tarkov",
            "escape from tarkov", "halo",
        ],
        "vocab": [
            "хедшот", "вн-педикс", "флэш", "смок", "раш b", "ace",
            "кемперит", "вх", "читак", "1в3", "клатч", "эко-раунд",
        ],
        "tone": "комментирует игру как зритель турниров, любит хайповать на клатчах",
    },
    "horror": {
        "match": [
            "resident evil", "silent hill", "outlast", "phasmophobia", "amnesia",
            "alien isolation", "dead by daylight", "the forest", "soma", "visage",
            "layers of fear",
        ],
        "vocab": [
            "не ходи туда", "сзади!", "оно тебя видит", "выключи свет",
            "осторожнее", "это ловушка", "беги", "у меня мурашки",
        ],
        "tone": "напряжённый, нервный, реагирует с задержкой 'аааа!' на скримеры",
    },
    "rpg": {
        "match": [
            "skyrim", "fallout", "the witcher", "witcher 3", "cyberpunk", "baldur's gate",
            "bg3", "diablo", "path of exile", "poe", "wow", "world of warcraft",
            "final fantasy", "kingdom come",
        ],
        "vocab": [
            "квест на повтор", "лор", "нпц", "перк", "крафт",
            "лут", "билд", "респаун", "сайдквест", "новая глава",
        ],
        "tone": "увлекается лором, любит обсуждать билды и квесты",
    },
    "mmo": {
        "match": [
            "world of warcraft", "final fantasy xiv", "ff14", "guild wars 2",
            "lost ark", "new world", "albion online", "eve online", "ragnarok",
        ],
        "vocab": [
            "райд-пати", "босс на скилл-чек", "тэнк-хил", "лут-нинзя",
            "длс-фарм", "ивент", "сезон", "рейдовый прог",
        ],
        "tone": "опытный игрок MMO, разговаривает терминами PvE/PvP",
    },
    "racing": {
        "match": [
            "forza", "gran turismo", "f1", "iracing", "assetto corsa",
            "wreckfest", "need for speed", "the crew", "burnout",
        ],
        "vocab": [
            "апекс", "пол-позиция", "пит-стоп", "сетап", "ливрея",
            "обгон", "развал-схождение", "трасса знакомая", "залип в стену",
        ],
        "tone": "технически разбирается в трассах и сетапах",
    },
    "fighting": {
        "match": [
            "tekken", "street fighter", "mortal kombat", "guilty gear", "dragon ball fighterz",
            "smash bros", "ssbu", "king of fighters", "skullgirls",
        ],
        "vocab": [
            "комбо", "панишер", "хитбокс", "ту-туу", "перфект",
            "рэндж", "грабли", "защита-кик", "хайлоу",
        ],
        "tone": "болельщик файтингов, кричит COMBO BREAKER на трансляции",
    },
    "minecraft": {
        "match": ["minecraft", "майнкрафт"],
        "vocab": [
            "крипер!", "энд-эра", "алмазы найдены", "построй стену",
            "что за курсед сид", "респаун", "нэйзер-портал", "шахта",
        ],
        "tone": "детский азарт, восхищается постройками",
    },
    "irl": {
        "match": [
            "just chatting", "irl", "irl outdoors", "travel & outdoors",
            "asmr", "food & drink", "art", "music",
        ],
        "vocab": [
            "как дела", "кушать сходи", "норм денёк", "что слушаешь",
            "вкуснотища", "красиво", "лайк за труд", "пять с плюсом",
        ],
        "tone": "разговорный, бытовой, эмпатичный",
    },
    "strategy": {
        "match": [
            "starcraft", "starcraft ii", "age of empires", "civilization",
            "total war", "stellaris", "europa universalis", "crusader kings",
            "company of heroes",
        ],
        "vocab": [
            "тех-1", "ранний раш", "эко", "макро-стиль", "контра-юниты",
            "разведка прошла", "тильт", "хороший позишн",
        ],
        "tone": "методичный, любит обсуждать билд-ордеры и тактику",
    },
}


_WORD_RE = re.compile(r"[a-zа-я0-9\-]+", re.IGNORECASE)


def _normalize(name: str) -> str:
    """Lower-case + collapse whitespace."""
    return re.sub(r"\s+", " ", (name or "").lower()).strip()


def match_game_category(game_name: str, mapping: dict | None = None) -> str:
    """По имени игры подбирает категорию.

    Сначала точный match (по name), потом partial (по подстроке).
    Возвращает имя категории или "" если ничего не подошло.
    """
    if not game_name:
        return ""
    mapping = mapping if mapping is not None else DEFAULT_GAME_CATEGORIES
    norm = _normalize(game_name)
    # 1) точный match по любому из match-слов
    for cat, payload in mapping.items():
        for needle in payload.get("match", []):
            if _normalize(needle) == norm:
                return cat
    # 2) partial match: norm содержит needle или наоборот
    for cat, payload in mapping.items():
        for needle in payload.get("match", []):
            n = _normalize(needle)
            if n and (n in norm or norm in n):
                return cat
    return ""


def format_vocab_block(category: str, mapping: dict | None = None, *, max_words: int = 10) -> str:
    """Формирует блок [Игровой словарь] для system-prompt."""
    if not category:
        return ""
    mapping = mapping if mapping is not None else DEFAULT_GAME_CATEGORIES
    cat = mapping.get(category)
    if not cat:
        return ""
    vocab = list(cat.get("vocab", []))[:max_words]
    tone = (cat.get("tone") or "").strip()
    parts: list[str] = []
    parts.append("[Игровой словарь]")
    if tone:
        parts.append(f"Тон: {tone}")
    if vocab:
        parts.append("Можешь иногда использовать слова: " + ", ".join(vocab))
    parts.append("[/Игровой словарь]")
    return "\n".join(parts)


def select_random_terms(category: str, mapping: dict | None = None, *, n: int = 3, rng=None) -> list[str]:
    """Возвращает n случайных терминов из словаря категории.

    Удобно если хочешь подмешать пару слов в end-of-prompt вместо целого блока.
    """
    import random as _r

    mapping = mapping if mapping is not None else DEFAULT_GAME_CATEGORIES
    cat = mapping.get(category)
    if not cat:
        return []
    vocab = list(cat.get("vocab", []))
    if not vocab:
        return []
    rng = rng or _r.Random()
    if n >= len(vocab):
        return vocab[:]
    return rng.sample(vocab, n)


def all_categories(mapping: dict | None = None) -> list[str]:
    """Список доступных категорий — для UI dropdown."""
    mapping = mapping if mapping is not None else DEFAULT_GAME_CATEGORIES
    return list(mapping.keys())


def extract_game_keywords(text: str, *, min_len: int = 3) -> list[str]:
    """Полезная вспомогалка: вытаскивает потенциальные ключевые слова из текста
    (используется для матчинга по vision/title если game_name пустой).
    """
    if not text:
        return []
    return [w.lower() for w in _WORD_RE.findall(text) if len(w) >= min_len]


def match_via_text(text: str, mapping: dict | None = None) -> str:
    """Запасной матчер: если Helix не вернул game_name, можно дать title стрима
    или vision-описание, и попробовать найти категорию по ключевым словам.
    """
    if not text:
        return ""
    mapping = mapping if mapping is not None else DEFAULT_GAME_CATEGORIES
    norm = _normalize(text)
    for cat, payload in mapping.items():
        for needle in payload.get("match", []):
            n = _normalize(needle)
            if n and n in norm:
                return cat
    return ""
