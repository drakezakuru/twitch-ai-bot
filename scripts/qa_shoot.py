#!/usr/bin/env python3
"""Скриншоты виджетов и панели напрямую через headless Chrome.

Зачем: агентская браузер-сессия в песочнице умеет залипать на `about:blank`
(демон жив и рапортует успех, но страница не грузится и снимок выходит белым).
Сам Chrome при этом полностью рабочий — проверено `--dump-dom`. Этот скрипт
снимает кадры в обход сессии, чтобы визуальная проверка не блокировалась.

Запуск (панель поднята на :8000):
    .venv/bin/python scripts/qa_shoot.py [папка]

По умолчанию кадры кладутся в `qa/`. Папка не коммитится (см. .gitignore) —
кадры прикладываются к PR через загрузку, а не как файлы репозитория.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"

# name, path, (width, height)
SHOTS: list[tuple[str, str, tuple[int, int]]] = [
    # Wave 5/6 — виджеты, чей рантайм переведён на общие ядра.
    ("mascot", "/widget/mascot?preview=1", (1280, 720)),
    ("anime-runner", "/widget/anime-runner?preview=1", (1280, 720)),
    ("tts-bot", "/widget/tts-bot?preview=1", (1280, 720)),
    ("chat-reader", "/widget/chat-reader?preview=1", (1280, 720)),
    ("tts-chat-overlay", "/widget/tts-chat-overlay?preview=1", (1280, 720)),
    ("tts-raw", "/obs/tts?channel=demo&preview=1", (1280, 720)),
    ("opacity-goals-default", "/widget/goals?preview=1&theme=light", (1280, 720)),
    ("opacity-goals-custom", "/widget/goals?preview=1&theme=light&opacity=.2", (1280, 720)),
    ("opacity-gradient-default", "/widget/latest-event-card?preview=1&theme=rainbow", (1280, 720)),
    ("opacity-gradient-custom", "/widget/latest-event-card?preview=1&theme=rainbow&opacity=.2", (1280, 720)),
    ("panel", "/", (1440, 900)),
]


def _chrome() -> Path | None:
    root = Path.home() / ".agent-browser" / "browsers"
    for candidate in sorted(root.glob("*/chrome")):
        if candidate.is_file():
            return candidate
    return None


def shoot(chrome: Path, out: Path, name: str, path: str, size: tuple[int, int]) -> bool:
    target = out / f"{name}.png"
    # A failed Chrome run must not make a stale frame look like a fresh success.
    target.unlink(missing_ok=True)
    cmd = [
        str(chrome),
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={size[0]},{size[1]}",
        # Даём странице «прожить» несколько секунд виртуального времени,
        # иначе анимации и превью-ветка не успевают отрисоваться.
        "--virtual-time-budget=4000",
        f"--screenshot={target}",
        BASE + path,
    ]
    for _attempt in range(2):
        # A failed Chrome run must not make a stale frame look like a fresh success.
        target.unlink(missing_ok=True)
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return True
    return False


def main() -> int:
    chrome = _chrome()
    if chrome is None:
        print("chrome не найден в ~/.agent-browser/browsers/*/chrome", file=sys.stderr)
        return 2

    out = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "qa")
    out.mkdir(parents=True, exist_ok=True)

    failed = 0
    for name, path, size in SHOTS:
        ok = shoot(chrome, out, name, path, size)
        print(f"{'OK  ' if ok else 'FAIL'} {name:18} {path}")
        if not ok:
            failed += 1

    print(f"\nкадры в {out.relative_to(ROOT)}/; неудач: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
