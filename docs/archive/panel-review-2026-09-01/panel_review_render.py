#!/usr/bin/env python3
"""PANEL_REVIEW Ф3 — генератор вердикт-отчёта из структурированных данных.

Читает docs/panel_review_data.json → пишет docs/PANEL_REVIEW_<дата>.md.
Правки вносятся В JSON (не в сгенерированный MD) — отчёт регенерируемый.

Запуск:  python3 scripts/panel_review_render.py [--data docs/panel_review_data.json] [--out docs/PANEL_REVIEW_<дата>.md]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _render_card_rows(cards: list[dict]) -> list[str]:
    lines = ["| Карточка | Что делает + почему здесь | Альтернатива | Цена переноса | Рекомендация | Баги |",
             "|---|---|---|---|---|---|"]
    for c in cards:
        bugs = c.get("bugs") or "—"
        lines.append(
            f"| **{c['name']}** | {c['does_why']} | {c.get('alternative') or '—'} "
            f"| {c.get('price') or '—'} | {c['verdict']} | {bugs} |"
        )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "docs" / "panel_review_data.json"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else ROOT / "docs" / (
        "PANEL_REVIEW_" + time.strftime("%Y-%m-%d") + ".md")

    md: list[str] = []
    meta = data["meta"]
    md.append(f"# PANEL_REVIEW_{time.strftime('%d.%m.%Y')} — вердикт-таблица панели")
    md.append("")
    md.append(f"> {meta['method']}")
    md.append(f"> Сгенерировано {time.strftime('%d.%m.%Y %H:%M')} из "
              f"`docs/panel_review_data.json` скриптом `scripts/panel_review_render.py`. "
              f"Правки — в JSON, не в этот файл.")
    md.append("")
    md.append(f"**Объём**: разделов {len(data['sections'])}, карточек "
              f"{sum(len(s['cards']) for s in data['sections'])}, "
              f"форм наполнения виджетов {sum(len(s.get('forms', [])) for s in data['sections'])}, "
              f"багов/находок {len(data['bugs'])}, кандидатов на перенос {len(data['transfers'])}.")
    md.append("")

    for sec in data["sections"]:
        md.append(f"## {sec['title']}")
        md.append("")
        if sec.get("note"):
            md.append(f"_{sec['note']}_")
            md.append("")
        md += _render_card_rows(sec["cards"])
        md.append("")
        if sec.get("forms"):
            md.append(f"### Формы наполнения ({sec['id']}) — статусы превью (F1) и биндингов (F3)")
            md.append("")
            md.append("| Форма | Назначение | Живое превью | Биндинги | Вердикт |")
            md.append("|---|---|---|---|---|")
            for f in sec["forms"]:
                md.append(f"| **{f['name']}** | {f['purpose']} | {f['preview']} "
                          f"| {f.get('bindings') or '—'} | {f['verdict']} |")
            md.append("")

    md.append("## Баги и находки (сводно)")
    md.append("")
    md.append("| ID | Severity | Находка | Воспроизведение | Фикс-план (Ф4) | Статус |")
    md.append("|---|---|---|---|---|---|")
    for b in data["bugs"]:
        md.append(f"| **{b['id']}** | {b['severity']} | {b['what']} | {b['repro']} "
                  f"| {b['fix_plan']} | {b['status']} |")
    md.append("")

    md.append("## Переносы-кандидаты")
    md.append("")
    md.append("| Что | Куда | Цена | Рекомендация | Решение владельца |")
    md.append("|---|---|---|---|---|")
    for t in data["transfers"]:
        md.append(f"| {t['what']} | {t['to']} | {t['price']} | {t['recommendation']} "
                  f"| {t.get('decision') or '—'} |")
    md.append("")

    if data.get("appendix"):
        md.append("## Приложение")
        md.append("")
        for line in data["appendix"]:
            md.append(line)
        md.append("")

    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"OK: {out} ({len(md)} строк)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
