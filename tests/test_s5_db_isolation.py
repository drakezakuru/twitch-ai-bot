"""PLAN_FEEDBACK_3008 §5: аудит БД — изоляция функций и дубли схем.

1. Таблицы, создаваемые в двух местах (database.py + widgets.py), должны иметь
   ИДЕНТИЧНЫЕ схемы — иначе «кто первый создал, тот и прав» (дрейф, как в P0).
2. Каждый CREATE-дубль пары должен оставаться в белом списке известных пар.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Пары «таблица: [файлы]», известные на момент аудита (30.08).
# Новая пара в коде без обновления этого списка = тест упадёт (и это правильно).
KNOWN_DUPLICATES = {
    "clip_moments": ["app/database.py", "app/widgets.py"],
    "stream_goals": ["app/database.py", "app/widgets.py"],
    "sub_goal": ["app/database.py", "app/widgets.py"],
    "now_playing": ["app/database.py", "app/widgets.py"],
    "schedule_blocks": ["app/database.py", "app/widgets.py"],
    "widget_titles": ["app/database.py", "app/widgets.py"],
}

_FILES = ["app/database.py", "app/widgets.py", "app/replay_debug.py", "app/moderation.py",
          "app/ai_quality_db.py", "app/blur_guard.py", "app/bot_logs.py", "app/donation_integrations.py"]


def _extract_create(path: str) -> dict[str, str]:
    src = (ROOT / path).read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\)\s*(?:;|$)", src, re.S):
        table, body = m.group(1), m.group(2)
        # нормализация: пробелы/переносы/регистр ключевых слов
        norm = re.sub(r"\s+", " ", body).strip().rstrip(";").lower()
        out[table] = norm
    return out


def test_no_unknown_duplicate_creates():
    found: dict[str, list[str]] = {}
    for f in _FILES:
        p = ROOT / f
        if not p.exists():
            continue
        for table in _extract_create(f):
            found.setdefault(table, []).append(f)
    unknown = {t: fs for t, fs in found.items()
               if len(fs) > 1 and t not in KNOWN_DUPLICATES}
    assert not unknown, f"новые дубли CREATE без записи в whitelist: {unknown}"


def test_duplicate_schemas_in_sync():
    schemas = {f: _extract_create(f) for f in KNOWN_DUPLICATES[next(iter(KNOWN_DUPLICATES))]}
    drifted = {}
    for table, files in KNOWN_DUPLICATES.items():
        variants = set()
        for f in files:
            body = schemas[f].get(table)
            if body:
                variants.add(body)
        if len(variants) > 1:
            drifted[table] = variants
    assert not drifted, f"схемы дублей расходятся (P0-паттерн): {list(drifted)}"
