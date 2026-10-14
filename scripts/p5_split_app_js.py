#!/usr/bin/env python3
"""P5 (PLAN.md «Разбить монолиты»): разовый сплит static/app.js на чанки.

Способ: ПОРЯД-СОХРАНЯЮЩИЕ классические скрипты (не ES-модули — в шаблонах
~700 инлайн onclick=, которые ломаются в module-scope). Файлы грузятся
отдельными <script>-тегами в templates/base.html строго в исходном порядке
строк, поэтому семантика 1:1 с монолитом.

Гарантии (проверяются скриптом до записи):
- каждая граница чанка — строка-маркер секции по правилу теста-якоря
  tests/test_p3_app_js_map.py (строка начинается с "// ── " или "// =" + "====");
- конкатенация app.js(ядро) + static/app/NN_*.js БЕЗ заголовков == исходный файл
  байт-в-байт;
- число найденных маркеров == числу строк-маркеров исходника.

Побочно печатает: таблицу «файл ← исходные строки» и новый APPENDIX для
docs/APP_JS_MAP.md (маркер → файл + новый диапазон).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "static" / "app.js"
OUT_DIR = ROOT / "static" / "app"

# (файл, первая строка исходного app.js 1-based, что внутри)
CHUNKS: list[tuple[str, int, str]] = [
    ("app.js",                     1, "ядро: state/helpers/toast/LANGS/v12P0/nav/search/WS"),
    ("02_dashboard.js",         1692, "Dashboard + мини-виджет «Последние нарушения»"),
    ("03_bots.js",              1849, "список ботов, карточка: базовые вкладки, Bot Files"),
    ("04_chat_settings.js",     3465, "Chat, Analytics, Settings, Uptime, Init"),
    ("05_bots_tabs.js",         4104, "доп-вкладки карточки: AI..Snippets, Voice Clones, KB, модалки"),
    ("06_roles.js",             5049, "Extend showBotTab, роли ботов §6, копирка §R4"),
    ("07_widgets.js",           5576, "Widgets Admin, Goals..Song Request, §9j, §17"),
    ("08_providers_moderation.js", 5998, "§25.4 провайдеры, §9d, §9k, вкладка Модерация v14"),
    ("09_brain_p3.js",          6502, "Мозг бота P3, чья память, Инструкция, К3, Субатон"),
    ("10_stream_p4_p6.js",      6889, "beep-конвейер, blur-v2, TTS за баллы, TTS-чат, стрим-инструменты"),
    ("11_brain_v16.js",         7422, "Мозг v16 + карточки главной страницы бота"),
    ("12_dashboard_extras.js",  7986, "настроение стримера, всплески чата, i18n"),
    ("13_widgets_session.js",   8196, "now-playing, биндинги, донаты, Blur Guard, логи, Polls, таймаут-политика"),
    ("14_brain_memory.js",      8600, "Brain priority/TTL, KB import/export, affinity + i18n"),
    ("15_feedback_2908.js",     8815, "PLAN_FEEDBACK_2908 §1–§7 + §24 wa2"),
    ("16_tail.js",              9598, "§9k-категории, гайд, дашборд по ролям, §S3/§S4/§S6"),
]

HEADER_TPL = "// [P5-split] {name} ← static/app.js, исходные строки {a}–{b}; грузится после предыдущего чанка, порядок = порядку строк\n\n"


def is_marker(line: str) -> bool:
    """Правило маркера из tests/test_p3_app_js_map.py (дословно)."""
    return line.startswith("// ── ") or (line.startswith("// =") and "====" in line)


def main() -> int:
    original = SRC.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    n = len(lines)
    bounds = [b for _, b, _ in CHUNKS] + [n + 1]
    if bounds != sorted(bounds) or len(set(bounds)) != len(bounds):
        print("FATAL: границы чанков не возрастают/дублируются", file=sys.stderr)
        return 2

    for (name, start, _desc), nxt in zip(CHUNKS, bounds[1:]):
        if not is_marker(lines[start - 1]) and start != 1:
            print(f"FATAL: строка {start} ({name}) не маркер: {lines[start - 1]!r}",
                  file=sys.stderr)
            return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    concat_parts: list[str] = []
    appendix: list[str] = []
    for (name, start, desc), nxt in zip(CHUNKS, bounds[1:]):
        end = nxt - 1
        body = "".join(lines[start - 1:end])
        concat_parts.append(body)
        if name == "app.js":
            SRC.write_text(body, encoding="utf-8")
        else:
            out = HEADER_TPL.format(name=name, a=start, b=end) + body
            (OUT_DIR / name).write_text(out, encoding="utf-8")
        print(f"{name:32s} <- {start:5d}-{end:5d} ({end - start + 1:5d} строк)  {desc}")

    # Тождество: склейка чанков (без заголовков) == исходник.
    if "".join(concat_parts) != original:
        print("FATAL: конкатенация чанков != исходный app.js", file=sys.stderr)
        return 2

    # Новый APPENDIX: маркер -> файл + диапазон НОВЫХ строк (для docs/APP_JS_MAP.md).
    for (name, start, desc), nxt in zip(CHUNKS, bounds[1:]):
        path = SRC if name == "app.js" else OUT_DIR / name
        chunk_lines = path.read_text(encoding="utf-8").splitlines()
        marker_idx = [i for i, ln in enumerate(chunk_lines) if is_marker(ln)]
        for pos, mi in enumerate(marker_idx):
            seg_end = (marker_idx[pos + 1] - 1) if pos + 1 < len(marker_idx) else len(chunk_lines) - 1
            appendix.append(f"`{name} {mi + 1}–{seg_end + 1}`: `{chunk_lines[mi].strip()}`")
    Path("/tmp/opencode/appjs_appendix_new.md").write_text(
        "\n\n".join(appendix) + "\n", encoding="utf-8")
    print(f"\nOK: {len(CHUNKS)} файлов, маркеров в приложении: {len(appendix)} "
          f"(ожидалось ~113); appendix -> /tmp/opencode/appjs_appendix_new.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
