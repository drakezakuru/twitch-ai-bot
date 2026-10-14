"""Q27b (DEC-OWNER-017 п.4): секция «⚡ Правила» в карточке виджета.

Правила биндингов живут прямо в карточке виджета (details.wa-widget-rules с
data-rules-slug): список его правил + inline-форма КОГДА → ТОГДА без селекта
виджета. waWidgetBindingAdd открывает секцию карточки и скроллит к ней.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment

from app.widget_inventory import WIDGET_INVENTORY

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static/app/13_widgets_session.js").read_text(encoding="utf-8")
ADMIN = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")


def _render_catalog() -> str:
    return Environment(autoescape=True).from_string(PANEL).render(widget_inventory=WIDGET_INVENTORY)


def test_every_binding_widget_card_has_rules_section():
    rendered = _render_catalog()
    for item in WIDGET_INVENTORY:
        if not item.binding_slug:
            continue
        assert f'data-rules-slug="{item.binding_slug}"' in rendered, item.slug


def test_static_cards_have_rules_sections():
    for slug in ("goals", "sub_goal", "now_playing", "countdown", "soundboard"):
        assert f'data-rules-slug="{slug}"' in PANEL, slug


def test_rules_section_markup_contract():
    # секция: summary с i18n-заголовком + пустое тело, которое строит JS
    assert 'details class="wa-widget-rules" data-rules-slug="{{ widget.binding_slug }}"' in PANEL
    assert 'data-i18n="bindings.rules_section"' in PANEL
    assert 'class="wa-widget-rules-body"' in PANEL


def test_inline_form_has_no_widget_select():
    body = SCRIPT.split("function waRulesEnsure(", 1)[1].split("function waRulesFormSync(", 1)[0]
    # виджет уже выбран (data-rules-slug) — селекта виджета в inline-форме нет
    assert "wa-rules-source" in body and "wa-rules-match" in body
    assert "wa-rules-action" in body and "wa-rules-role" in body
    assert "waBindWidget" not in body


def test_rules_sections_are_fed_by_shared_bindings_cache():
    # общий кэш наполняет waBindingsLoad, секции читают его же
    assert "window._waBindingsCache" in SCRIPT
    # лёгкий waBindingsLoad (Q27c): только кэш + перерисовка секций карточек
    assert "waRulesRenderAll();\n}" in SCRIPT
    assert "секции карточек" in SCRIPT


def test_soundboard_prefill_keeps_old_anchors():
    # привязка трека работает через секцию карточки, а не общую модалку
    fn = ADMIN.split("function waSoundboardBind(", 1)[1].split("\n}", 1)[0]
    assert "waWidgetBindingAdd('soundboard', action)" in fn
