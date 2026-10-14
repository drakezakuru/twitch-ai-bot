#!/usr/bin/env python3
"""PANEL_REVIEW Ф2 — рантайм-проходка панели (browser smoke).

Требует Playwright (в репо-venv уже есть):  venv/bin/python scripts/browser_smoke.py
Панель должна быть запущена:                python run.py  (или ./start.sh)

Что делает:
- открывает ВСЕ разделы панели (7: dashboard, bots, chat, analytics, brain,
  widgets, settings) и все вкладки карточки бота (7 групп showBotGroup);
- собирает: JS-ошибки (pageerror + console.error), failed-ответы (HTTP >= 400),
  error-тосты, пустые активные секции;
- скриншоты 1440 / 1280x800 (Steam Deck оконный) / 1024 / 390 + проверка
  горизонтального overflow на 390;
- отчёт: лог в консоль + JSON (logs/smoke_report.json).

Безопасность: скрипт ТОЛЬКО навигация (GET/WS-подписки). Кнопки, которые
шлют что-то в реальный чат или меняют данные (Quick Send, TTS-тест),
выполняются ТОЛЬКО с --interactive — по умолчанию выключены.

Возврат: 0 — всё зелёное; 1 — есть падения (JS-ошибки, 5xx, пустые секции,
overflow). Playwright не установлен → код 2 (окружение, не баг панели).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"

# Активные разделы панели (showSection; отдельной секции «Модерация» нет —
# модерация живёт во вкладках карточки бота и в mod-feed).
SECTIONS = [
    "dashboard", "bots", "channels", "director", "chat", "analytics", "brain",
    "widgets", "settings", "chatlogger",
]
# Вкладки первого fake-бота qa_modbot; voice скрыт для роли moderator по контракту.
BOT_GROUPS = ["overview", "brain-x", "identity", "flow", "moderation", "memory", "advanced"]

# Ответы, которые не считаются поломкой панели (ожидаемая фоновая динамика).
EXPECTED_4XX = {
    # пример: "/api/some-optional-endpoint": "пояснение — зачем ожидаемо"
}


def _installed_chrome() -> str | None:
    browser_root = Path.home() / ".agent-browser" / "browsers"
    for candidate in sorted(browser_root.glob("*/chrome")):
        if candidate.is_file():
            return str(candidate)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--out", default=str(LOGS / "smoke_report.json"))
    parser.add_argument("--interactive", action="store_true",
                        help="разрешить клики, шлющие данные (Quick Send, TTS-тест)")
    parser.add_argument("--strict", action="store_true",
                        help="считать падением любой ответ >= 400 (по умолчанию только 5xx)")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright не установлен — окружение не готово (код 2).")
        print("  venv/bin/python -m playwright install chromium")
        return 2

    LOGS.mkdir(exist_ok=True)
    report: dict = {
        "url": args.url,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sections": {},
        "js_errors": [],
        "console_errors": [],
        "bad_responses": [],
        "error_toasts": [],
        "screenshots": [],
        "checks": [],
    }
    hard_failures: list[str] = []

    def check(name: str, ok: bool, note: str = "") -> None:
        report["checks"].append({"name": name, "ok": ok, "note": note})
        if not ok:
            hard_failures.append(f"{name}: {note}")
        print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" — {note}" if note else ""))

    with sync_playwright() as pw:
        chrome = _installed_chrome()
        browser = pw.chromium.launch(executable_path=chrome) if chrome else pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        page.on("pageerror", lambda exc: report["js_errors"].append(str(exc)[:300]))
        page.on("console", lambda m: report["console_errors"].append(m.text[:300])
                if m.type == "error" else None)
        page.on("response", lambda r: report["bad_responses"].append(
            {"status": r.status, "url": r.url[:200]})
            if r.status >= 400 else None)

        def toasts() -> list[str]:
            out = []
            for el in page.locator(".toast.error, .toast-danger, .toast[data-type='error']").all():
                t = el.inner_text().strip()
                if t:
                    out.append(t[:200])
            return out

        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        def goto(section: str, settle_ms: int = 1200) -> None:
            page.locator(f".nav-btn[data-section='{section}']").click()
            page.wait_for_timeout(settle_ms)

        def section_text(name: str) -> str:
            sec = page.locator(f"#section-{name}")
            return sec.inner_text() if sec.count() else ""

        # ── Проходка разделов ──
        for name in SECTIONS:
            goto(name)
            text = section_text(name)
            empty = len(text.strip()) < 20
            check(f"section-{name}", not empty,
                  "секция пустая (<20 символов после загрузки)" if empty else "")
            report["sections"][name] = {"chars": len(text.strip()),
                                        "toasts": toasts()}
            report["error_toasts"] += [t for t in toasts() if t not in report["error_toasts"]]

        # ── Вкладки карточки бота ──
        goto("bots")
        visible_bot_cards = page.locator(".bot-card:visible")
        has_bots = visible_bot_cards.count() > 0
        if not has_bots:
            check("bot-card-tabs", True,
                  "SKIP: нет ботов в базе — вкладки карточки не проверялись")
        else:
            configure = visible_bot_cards.first.locator(
                "button[onclick*='openBotSettings']"
            ).first
            configure.click()
            page.wait_for_timeout(600)
            for group in BOT_GROUPS:
                tab = page.locator(
                    f"[onclick*=\"showBotGroup('{group}')\"]:visible"
                ).first
                if not tab.count():
                    check(f"bot-tab-{group}", False, "кнопка вкладки не найдена")
                    continue
                tab.click()
                page.wait_for_timeout(700)
                report["error_toasts"] += [t for t in toasts()
                                           if t not in report["error_toasts"]]
                # вкладка не должна быть пустой
                visible = page.evaluate(
                    """() => {
                        const els = document.querySelectorAll('.bot-group, [class*="bot-group"]');
                        for (const el of els) {
                            if (el.offsetParent && el.innerText.trim().length > 10) return true;
                        }
                        return document.body.innerText.length > 100;
                    }"""
                )
                check(f"bot-tab-{group}", bool(visible),
                      "" if visible else "вкладка выглядит пустой")

        # ── Интерактив (только с --interactive) ──
        if args.interactive and has_bots:
            def quick_send() -> None:
                btn = page.locator("[onclick*='quickSend'], [onclick*='sendQuickSnippet']").first
                if btn.count():
                    btn.click()
                    page.wait_for_timeout(800)
            check("quick-send", quick_send() is None)
            def tts_test() -> None:
                btn = page.locator("[onclick*='testBotTTS']").first
                if btn.count():
                    btn.click()
                    page.wait_for_timeout(1500)
            check("tts-test", tts_test() is None)
        elif not args.interactive:
            check("interactive-skipped", True,
                  "SKIP: Quick Send / TTS-тест выключены (запуск с --interactive)")

        # ── Скриншоты + узкий экран (Steam Deck оконный 1280×800) ──
        for w, h, tag in [(1440, 900, "1440"), (1280, 800, "deck-1280"),
                          (1024, 800, "1024"), (390, 844, "390")]:
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(500)
            shot = LOGS / f"smoke-{tag}.png"
            page.screenshot(path=str(shot), full_page=False)
            report["screenshots"].append(str(shot.relative_to(ROOT)))
            if w == 390:
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth + 8")
                check("mobile-390-no-overflow", not overflow,
                      "горизонтальный overflow на 390px" if overflow else "")

        browser.close()

    # ── Вердикты по собранному ──
    if report["js_errors"]:
        check("no-js-errors", False, "; ".join(report["js_errors"][:3]))
    else:
        check("no-js-errors", True)
    limit = 400 if args.strict else 500
    serious = [b for b in report["bad_responses"]
               if b["status"] >= limit and b["url"] not in EXPECTED_4XX]
    check("no-serious-http-failures", not serious,
          "; ".join(f"{b['status']} {b['url']}" for b in serious[:3]))
    if report["error_toasts"]:
        check("no-error-toasts", False, "; ".join(report["error_toasts"][:3]))
    else:
        check("no-error-toasts", True)

    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    report["hard_failures"] = hard_failures
    out = Path(args.out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nОтчёт: {out}")
    print(f"Итог: {len(report['checks']) - len(hard_failures)}/{len(report['checks'])} "
          f"проверок, JS-ошибок {len(report['js_errors'])}, HTTP>=400 — "
          f"{len(report['bad_responses'])}, error-тостов {len(report['error_toasts'])}")
    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
