#!/usr/bin/env python3
"""ТРЕК 4: обход всех preview_url реестра виджетов на живой панели.

Проверяет для каждого контракта из `WIDGET_INVENTORY`, а также для
retired/alias/legacy URL:

* HTTP-статус 200 (ни один OBS Browser Source не должен получить 404/500);
* отсутствие неподставленных `__PLACEHOLDER__` в отданном HTML;
* тёмную схему (`color-scheme` / прозрачный фон) — белый кадр в OBS виден сразу;
* наличие ветки `?preview=1` там, где виджет не самодостаточен.

Запуск (панель поднята на :8000):
    .venv/bin/python scripts/qa_preview_sweep.py
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.widget_inventory import (  # noqa: E402
    ALIAS_WIDGETS,
    LEGACY_PARAM_URLS,
    RETIRED_WIDGETS,
    WIDGET_INVENTORY,
)

BASE = "http://127.0.0.1:8000"
SELF_RENDERING = {"animated-bg", "mascot", "anime-runner"}


def fetch(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(BASE + url, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"ERROR {exc}"


def main() -> int:
    failures: list[str] = []
    checked = 0

    for item in WIDGET_INVENTORY:
        status, html = fetch(item.preview_url)
        checked += 1
        problems = []
        if status != 200:
            problems.append(f"HTTP {status}")
        else:
            left = sorted(set(re.findall(r"__[A-Z_]+__", html)))
            if left:
                problems.append(f"неподставленные плейсхолдеры {left}")
            if "color-scheme" not in html and "background: transparent" not in html:
                problems.append("нет тёмной схемы")
            if item.folder not in SELF_RENDERING and "preview" not in html:
                problems.append("нет ветки ?preview=1")
        mark = "OK  " if not problems else "FAIL"
        print(f"{mark} {item.slug:22} {item.preview_url}")
        for p in problems:
            print(f"       {p}")
            failures.append(f"{item.slug}: {p}")

    # Совместимость: старые адреса из OBS-сцен владельца обязаны отвечать.
    for url in list(RETIRED_WIDGETS) + list(ALIAS_WIDGETS) + list(LEGACY_PARAM_URLS):
        status, _ = fetch(url)
        checked += 1
        ok = status == 200
        print(f"{'OK  ' if ok else 'FAIL'} {'(compat)':22} {url}")
        if not ok:
            failures.append(f"{url}: HTTP {status}")

    print(f"\nпроверено URL: {checked}; проблем: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
