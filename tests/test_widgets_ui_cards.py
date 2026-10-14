"""WIDGETS-UI: превью целиком, группы, биндинг и настройки на карточке.

Разметочные проверки плана 12.09 (каждый шаг плана добавляет свои проверки сюда).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WIDGETS_HTML = REPO / "templates" / "partials" / "widgets.html"
APP_CSS = REPO / "static" / "app.css"
WIDGETS_JS = REPO / "static" / "app" / "07_widgets.js"


def _tpl() -> str:
    return WIDGETS_HTML.read_text(encoding="utf-8")


def test_step1_preview_toolbar_on_hand_written_cards():
    """Каждая рукописная карточка с превью имеет тулбар «Увеличить» + «В новой вкладке»."""
    tpl = _tpl()
    toolbars = re.findall(r'<div class="widget-preview-toolbar">.*?</div>', tpl, flags=re.S)
    assert len(toolbars) == 13
    for toolbar in toolbars:
        assert 'data-i18n="widgets.zoom"' in toolbar
        assert 'data-i18n="widgets.preview_tab"' in toolbar
        assert "waWidgetZoom(" in toolbar
        # Пер-виджетный скоуп: «в новой вкладке» открывается через
        # waWidgetBestUrl (общий скоуп или override виджета, с фолбэком).
        assert "window.open(waWidgetBestUrl(" in toolbar


def test_step1_zoom_sizes_match_widget_inventory():
    """Размеры в waWidgetZoom для рукописных карточек совпадают с WIDGET_OBS_SIZES."""
    from app.widget_inventory import WIDGET_OBS_SIZES
    tpl = _tpl()
    calls = re.findall(
        r"waWidgetZoom\('/widget/([a-z0-9-]+)[^']*',[^,]+,\s*(\d+),\s*(\d+)\)", tpl)
    checked = 0
    for slug, w, h in calls:
        if slug not in WIDGET_OBS_SIZES:
            continue
        inv_w, inv_h, _ = WIDGET_OBS_SIZES[slug]
        assert (int(w), int(h)) == (inv_w, inv_h), slug
        checked += 1
    assert checked >= 9, checked


def test_step1_catalog_card_has_zoom_button_with_inventory_size():
    """Карточка каталога: «Увеличить» с obs_width/obs_height из widget_inventory."""
    tpl = _tpl()
    assert "waWidgetZoom('{{ widget.preview_url }}','ui.catalog.title.{{ widget.slug }}', {{ widget.obs_width }}, {{ widget.obs_height }})" in tpl


def test_step1_zoom_lightbox_and_i18n_defined():
    """Лайтбокс в 07_widgets.js: функция, масштаб под экран, переводы RU/EN/UA."""
    js = WIDGETS_JS.read_text(encoding="utf-8")
    assert "function waWidgetZoom(" in js
    assert "transform:scale(" in js
    for lang in ("ru", "en", "ua"):
        block = re.search(rf"Object\.assign\(LANGS\.{lang}, \{{\n    'widgets\.zoom'.*?}}\);", js, flags=re.S)
        assert block, lang
        assert "'widgets.preview_tab'" in block.group(0)
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".widget-preview-toolbar" in css
    assert ".widget-zoom-stage" in css


def test_step2_widget_groups_wrapped_and_collapsed():
    """Шаг 2: карточки разбиты на <details>-группы; по умолчанию все свёрнуты."""
    tpl = _tpl()
    groups = re.findall(r'<details class="widget-group" data-widget-group="([a-z_]+)">', tpl)
    assert groups == ["basics", "donations", "tts_sound", "automation", "overlays", "extras", "catalog"]
    assert tpl.count("<details") == tpl.count("</details>")
    for group_id in groups:
        opening = re.search(
            rf'<details class="widget-group" data-widget-group="{group_id}">\s*<summary[^>]*>.*?</summary>',
            tpl, flags=re.S)
        assert opening, group_id
        head = opening.group(0)
        assert 'data-i18n="widgets.group.' + group_id + '"' in head
        assert 'class="badge widget-group-count"' in head
        assert 'open' not in opening.group(0).split(">")[0], "группа не должна быть открыта по умолчанию"


def test_step2_group_state_persisted_in_localstorage():
    """Шаг 2: состояние раскрытия хранится в localStorage; счётчик и lazy-превью сохранены."""
    js = (REPO / "static" / "app" / "13_widgets_session.js").read_text(encoding="utf-8")
    assert "WIDGET_GROUPS_STORAGE_KEY" in js
    assert "localStorage.getItem(WIDGET_GROUPS_STORAGE_KEY)" in js
    assert "localStorage.setItem(WIDGET_GROUPS_STORAGE_KEY" in js
    assert "waWidgetGroupsInit" in js
    tpl = _tpl()
    # ключи групп переведены на RU/EN/UA
    for key in ("widgets.group.basics", "widgets.group.donations", "widgets.group.tts_sound",
                "widgets.group.automation", "widgets.group.overlays", "widgets.group.extras",
                "widgets.group.catalog"):
        assert f"'{key}'" in js
    # превью остаются lazy — скрытая группа не грузит iframe
    assert 'loading="lazy"' in tpl


def test_step2_group_css_defined():
    css = APP_CSS.read_text(encoding="utf-8")
    for sel in ("details.widget-group", "summary.widget-group-head", ".widget-group-count"):
        assert sel in css


def test_step3_widget_rules_live_in_card_sections():
    """Q27b: карточный CTA открывает секцию «⚡ Правила» в самой карточке;
    inline-форма не дублирует канонический билдер (виджет уже выбран)."""
    session_js = (REPO / "static" / "app" / "13_widgets_session.js").read_text(encoding="utf-8")
    tpl = _tpl()
    # секции правил в карточках статических виджетов
    for slug in ("goals", "sub_goal", "now_playing", "countdown"):
        assert f"waWidgetBindingAdd('{slug}')" in tpl
        assert f'data-rules-slug="{slug}"' in tpl
    for legacy in ("waWB-source", "waWB-match", "waWB-key", "waWB-action", "waWB-value", "waWB-role"):
        assert legacy not in tpl
    # секция строится и синкается общим кодом; CTA скроллит к карточке
    assert "function waRulesEnsure(" in session_js
    assert "function waWidgetBindingAdd(slug, prefillAction)" in session_js
    assert "waRulesRenderAll" in session_js


def test_step4_widget_settings_open_from_card_via_shared_form():
    """Шаг 4: карточка открывает настройки виджета модально, форма не дублируется."""
    tpl = _tpl()
    session_js = (REPO / "static" / "app" / "13_widgets_session.js").read_text(encoding="utf-8")
    slugs = ("lower-third", "mascot", "anime-runner", "chat-roulette", "latest-event-card", "uptime", "recent-events")
    for slug in slugs:
        assert f'id="wa2Form-{slug}"' in tpl, slug
        assert tpl.count(f'id="wa2Form-{slug}"') == 1, slug
    # кнопка «Настройки» только у виджетов, у которых есть форма
    assert tpl.count("waWidgetSettingsOpen('{{ widget.slug }}')") == 1
    assert "widget.slug in ('lower-third', 'mascot', 'anime-runner', 'chat-roulette', 'latest-event-card', 'uptime', 'recent-events')" in tpl
    assert "function waWidgetSettingsOpen(slug)" in session_js
    assert "function waWidgetSettingsClose(" in session_js
    assert "waWidgetSettingsReturn" in session_js
    # форма переносится в оверлей и возвращается на исходное место
    assert "overlay.querySelector('#waWidgetSettingsBody').appendChild(form)" in session_js
    assert "home.parent.insertBefore(form, home.anchor)" in session_js
    # переводы кнопки на RU/EN/UA
    assert session_js.count("'widgets.settings'") >= 3
