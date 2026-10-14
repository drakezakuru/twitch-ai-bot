#!/usr/bin/env python3
"""Отрисовка виджетов в статические HTML для визуальной проверки превью.

Зачем: карточки в панели показывают `?preview=1` в iframe, но проверять этот
контракт удобно и без запуска панели (владелец запускает её сам). Скрипт
подставляет те же плейсхолдеры, что и роуты `app/widgets.py`, и складывает
результат в указанную папку (по умолчанию /tmp/opencode/widget-previews).

    python scripts/render_widget_previews.py [--out DIR]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WIDGETS = ROOT / "widgets"

# Значения по умолчанию совпадают с дефолтами роутов /widget/* в app/widgets.py.
SUBSTITUTIONS = {
    "__THEME__": "rec",
    "__TITLE__": "",
    "__TITLE_OVERRIDE__": "",
    "__THEME_OVERRIDE__": "",
    "__PERIOD__": "alltime",
    "__TYPE__": "stars",
    "__SPEED__": "1.0",
    "__COUNT__": "0",
    "__COLOR__": "",
    "__BG__": "#0f0f1a",
    "__TTS_ACCENT__": "#FFD700",
    "__ACCOUNT_ID__": "0",
    "__MAX_MSGS__": "5",
    "__RETAIN_MS__": "8000",
    "__CHANNEL__": "''",
    "__ROLE__": "'any'",
    "__LANG__": "'ru'",
    "__RATE__": "1",
    "__VOL__": "1",
    "__MAXCHARS__": "200",
    "__TZ__": "local",
    "__TTS_ACCENT_SOFT__": "rgba(255,215,0,0.35)",
    "__TTS_GLOW__": "rgba(255,215,0,0.45)",
    "__TTS_ICON__": "🎙",
    "__PRESET_OVERRIDE__": "",
    "__CUSTOM_URL_OVERRIDE__": "",
    "__SIZE_OVERRIDE__": "",
    "__CORNER_OVERRIDE__": "",
    "__ACCENT_OVERRIDE__": "",
    "__EYE_OVERRIDE__": "",
    "__HAIR_OVERRIDE__": "",
    "__OUTFIT_OVERRIDE__": "",
    "__PATH_MODE_OVERRIDE__": "",
    "__SPEED_OVERRIDE__": "",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/opencode/widget-previews")
    args = parser.parse_args()

    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    count = 0
    for path in sorted(WIDGETS.glob("*/index.html")):
        html = path.read_text(encoding="utf-8")
        for placeholder, value in SUBSTITUTIONS.items():
            html = html.replace(placeholder, value)
        (out / f"{path.parent.name}.html").write_text(html, encoding="utf-8")
        count += 1
    print(f"{count} widget(s) → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
