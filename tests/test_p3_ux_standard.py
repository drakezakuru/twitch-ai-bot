"""P3 §3 PLAN_PANEL_REWORK: UX-стандарт карточек — автопроверки (греп-тесты).

По образцу test_no_broken_bg_secondary_fallback (tests/test_ui_input_styles.py).
Правила §3.1, которые проверяем автоматически:
  1. Запрет inline-fallback цветов вида var(--x, #fff) в шаблонах/app.js —
     рвут тёмную тему (прецедент: white-on-white брейн-карточки).
  2. Запрет data-i18n-ключей без перевода — уже покрыт
     test_plan_v13_features.test_all_active_template_and_javascript_i18n_keys...
     здесь дублируем проверку «ключ в data-i18n, но нет ни в одном LANGS»
     с более понятным выводом.
  3. Запрет дублей-синонимов i18n: один и тот же русский текст определён
     под разными ключами в одном языке — растит путаницу (§Риски).
  4. Карточка имеет строку «что это даёт»: у карточек виджетов с формами
     должен быть hint-текст (text-muted) — проверяем на виджет-карточках.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests import _panel_js

ROOT = Path(__file__).resolve().parents[1]

_FILES = [
    ROOT / "templates" / "base.html",
    *_panel_js.panel_js_files(),
    *sorted((ROOT / "templates" / "partials").glob("*.html")),
]

# Исключения: осознанные fallback (пара: файл, совпавшая строка) — легаси
# до введения правила; НОВЫЕ использования (другой файл или другой var) падают.
_INLINE_FALLBACK_EXCEPTIONS: set[tuple[str, str]] = {
    # P5-сплит: легаси-строки переехали из static/app.js в чанки (ключ = путь файла).
    ("static/app/04_chat_settings.js", "var(--success,#2ecc71)"),
    ("static/app/11_brain_v16.js", "var(--border,#eee)"),
    ("static/app/13_widgets_session.js", "var(--bg-card,#1e1e2e)"),
    ("static/app/13_widgets_session.js", "var(--border,#444)"),
    ("templates/partials/brain.html", "var(--border,#eee)"),
}

# Легаси-дубли i18n (чистка — отдельным шагом; НОВЫЕ дубли запрещены).
# Формат: (язык, текст). Список = полный кросс-блочный скан на 31.08.
_I18N_DUPLICATE_TEXTS: set[tuple[str, str]] = {
    ("en", "AI provider"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "All categories"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Could not complete the request"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Default voice"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Director"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Log level"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Reward voice"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Select a channel"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Twitch channel"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Twitch event"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "Window, sec"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "connecting"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "⏱ Uptime"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "⛔ Select a bot and channel above"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("en", "📅 Schedule"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "URL для OBS"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Включено"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Все категории"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Выберите канал"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Голос награды"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Голос по умолчанию"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Действие"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Заменить"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Запустить"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Канал Twitch"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Не удалось выполнить запрос"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Окно, сек"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Отклонить"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Плотность маски, %"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Показать"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Режиссёр"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Событие Twitch"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Сохранить"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Сочетание клавиш"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "Уровень логов"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "выключен"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "работает"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "⛔ Выбери бота и канал сверху панели"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ru", "📅 Расписание"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "URL для OBS"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Блокувати"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Виберіть канал"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Відхилити"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Вікно, сек"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Голос нагороди"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Замінити"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Запустити"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Зберегти"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Канал Twitch"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Не вдалося виконати запит"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Подія Twitch"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Показати"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Рівень логів"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Сполучення клавіш"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Щільність маски, %"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "вимкнено"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "⛔ Вибери бота й канал вище"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "📅 Розклад"),  # legacy: snapshot e9e2067 (чистка дубликатов — отдельный шаг)
    ("ua", "Увімкнено"),  # status.offline_enabled == overrides.enabled (legacy vs rework overrides)
    ("en", "Bot has no connected channel"),
    ("en", "Disabled"),
    ("en", "Generating 5 snippets..."),
    ("en", "No fresh observation yet"),
    ("en", "OBS connection"),
    ("en", "Observe only"),
    ("en", "Open preview"),
    ("en", "Voice model uploaded"),
    ("en", "global model"),
    ("en", "📋 Copy URL"),
    ("en", "📋 Global logs"),
    ("en", "🟣 Twitch application"),
    ("en", "🧠 AI & TTS"),
    ("en", "🧠 Memory & knowledge"),
    ("ru", "Генерирую 5 заготовок..."),
    ("ru", "Голосовая модель загружена"),
    ("ru", "Открыть превью"),
    ("ru", "Подключение к OBS"),
    ("ru", "Пресет характера применён"),
    ("ru", "Свежего наблюдения пока нет"),
    ("ru", "Свой вариант пола"),
    ("ru", "У бота нет подключённого канала"),
    ("ru", "глобальная модель"),
    ("ru", "🎭 Характер"),
    ("ru", "📋 Глобальные логи"),
    ("ru", "📋 Копировать URL"),
    ("ru", "🟣 Twitch-приложение"),
    ("ru", "🧠 AI и TTS"),
    ("ru", "🧠 Память и знания"),
    ("ua", "Вимкнено"),
    ("ua", "Власний варіант статі"),
    ("ua", "Відкрити превʼю"),
    ("ua", "Генерую 5 заготовок..."),
    ("ua", "Голосову модель завантажено"),
    ("ua", "Пресет характеру застосовано"),
    ("ua", "Підключення до OBS"),
    ("ua", "Свіжого спостереження ще немає"),
    ("ua", "У бота немає підключеного каналу"),
    ("ua", "глобальна модель"),
    ("ua", "🎭 Характер"),
    ("ua", "📋 Глобальні логи"),
    ("ua", "📋 Копіювати URL"),
    ("ua", "🟣 Twitch-застосунок"),
    ("ua", "🧠 Памʼять і знання"),
    # legacy: полный кросс-блочный скан на 27.09 (чистка — отдельный шаг)
    ("ru", "Все роли"),  # bots.packs.role_all == chat_users.all_roles
    ("ru", "Остановить"),  # bindings.action_stop == chatlog.stop
    ("ru", "Блокировать"),  # panel.mod.ext_block == wordfilter.block
    ("ru", "Дополнительно"),  # panel.runner.details == blur_guard.advanced
    ("en", "All roles"),  # bots.packs.role_all == chat_users.all_roles
    ("ua", "Зупинити"),  # bindings.action_stop == chatlog.stop
    ("ua", "Додатково"),  # panel.runner.details == blur_guard.advanced
    ("ua", "Видалити"),  # director.prompt_delete == bots.packs.delete
}


def _iter_lines():
    for path in _FILES:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            yield path, i, line


def test_no_inline_color_fallbacks():
    """var(--x, #hex) в панели — запрещён (ломает тёмную тему)."""
    offenders = []
    pattern = re.compile(r"var\(--[a-z0-9-]+\s*,\s*#[0-9a-fA-F]{3,8}\)")
    for path, i, line in _iter_lines():
        rel = str(path.relative_to(ROOT))
        for match in pattern.finditer(line):
            key = (rel, match.group(0).replace(" ", ""))
            if key in _INLINE_FALLBACK_EXCEPTIONS:
                continue
            offenders.append(f"{rel}:{i}: {key[1]} | {line.strip()[:100]}")
    assert not offenders, (
        "inline-fallback цвета (var(--x, #hex)) ломают тёмную тему:\n"
        + "\n".join(offenders)
    )


def test_no_data_i18n_keys_without_translation():
    """data-i18n-ключ без определения ни в одном LANGS — падает с ясным списком."""
    js = _panel_js.panel_js()
    template_text = "\n".join(
        p.read_text(encoding="utf-8") for p in _FILES if p.suffix == ".html"
    )
    keys = set(re.findall(r'data-i18n(?:-placeholder|-title|-aria-label)?="([^"]+)"',
                          template_text))
    keys = {k for k in keys if "{{" not in k}
    missing = [k for k in sorted(keys)
               if js.count(f"'{k}'") + js.count(f'"{k}"') == 0]
    assert not missing, f"data-i18n без перевода в app.js: {missing}"


def test_no_synonym_duplicates_in_i18n():
    """Одинаковый текст под разными ключами одного языка — запрещён.

    Скан КРОСС-БЛОЧНЫЙ (все Object.assign(LANGS.ru/en/ua, ...) суммарно),
    иначе дубль из двух отдельных блоков проскакивает. Исключения — легаси
    (чистка отдельным шагом); НОВЫЕ дубли падают.
    """
    js = _panel_js.panel_js()
    blocks = re.findall(r"Object\.assign\(LANGS\.(ru|en|ua),\s*\{(.*?)\}\);", js, re.S)
    assert blocks, "LANGS-блоки не найдены"
    offenders = []
    for lang in ("ru", "en", "ua"):
        seen: dict[str, str] = {}
        for l2, body in (b for b in blocks if b[0] == lang):
            for m in re.finditer(r"'([a-z0-9_.]+)':\s*'((?:[^'\\]|\\.)*)'", body):
                key, val = m.group(1), m.group(2)
                if len(val.strip()) < 8 or "{" in val or "}}" in val:
                    continue
                if val in seen and seen[val] != key:
                    if (lang, val) in _I18N_DUPLICATE_TEXTS:
                        continue
                    offenders.append(f"{lang}: '{key}' == '{seen[val]}' → «{val[:60]}»")
                seen.setdefault(val, key)
    assert not offenders, (
        "дубли-синонимы i18n (одинаковый текст под разными ключами):\n"
        + "\n".join(offenders)
    )


def test_widget_cards_with_forms_have_hint():
    """Карточки виджетов с формами имеют строку «что это даёт» (text-muted)."""
    widgets = (ROOT / "templates" / "partials" / "widgets.html").read_text(encoding="utf-8")
    # Разбиваем на карточки верхнего уровня (card mb-4) и проверяем наличие
    # text-muted-подсказки внутри каждой.
    cards = re.findall(r'<div class="card mb-4"[^>]*>(.*?)(?=<div class="card mb-4"|\Z)',
                       widgets, re.S)
    assert len(cards) >= 15, "карточки виджетов должны существовать"
    no_hint = []
    for c in cards:
        has_title = "card-title" in c
        has_form = "<input" in c or "<select" in c
        has_hint = "text-muted" in c or "text-xs" in c
        if has_title and has_form and not has_hint:
            title = re.search(r'card-title"[^>]*>([^<]+)', c)
            no_hint.append(title.group(1).strip() if title else "?")
    assert not no_hint, f"карточки виджетов без подсказки «что это даёт»: {no_hint}"
