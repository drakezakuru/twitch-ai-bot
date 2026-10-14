"""Q28 (DEC-OWNER-017 п.5): брендовая палитра, пипетка и готовые темы в UI.

Проверяем: редактор палитры в шапке «Виджетов» (per-канал); полоски палитры
в карточках каталога (каждая карточка) и в статических карточках; живое
перекрашивание превью через URL-параметры accent/bg (appearance.js читает их
и валидирует hex); готовые темы одним кликом (неон/минимал/градиент/сброс);
i18n RU/EN/UA; роут включён в server.py.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment

from app.widget_inventory import WIDGET_INVENTORY

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
SESSION = (ROOT / "static/app/13_widgets_session.js").read_text(encoding="utf-8")
APPEARANCE = (ROOT / "widgets/_shared/appearance.js").read_text(encoding="utf-8")
SERVER = (ROOT / "app/server.py").read_text(encoding="utf-8")


def _render_catalog() -> str:
    return Environment(autoescape=True).from_string(PANEL).render(widget_inventory=WIDGET_INVENTORY)


def test_brand_palette_editor_in_header():
    assert 'id="waBrandPaletteEditor"' in PANEL
    assert 'id="waBrandPaletteBox"' in PANEL
    assert 'data-i18n="widgets.brand_palette"' in PANEL
    assert "include_router(_widget_brand_router)" in SERVER


def test_every_catalog_card_has_palette_strip():
    rendered = _render_catalog()
    for item in WIDGET_INVENTORY:
        assert f'data-palette-card="{item.slug}"' in rendered, item.slug
        assert f'data-palette-route="{item.route}"' in rendered, item.slug


def test_static_cards_have_palette_strips():
    for slug, route in (("goals", "/widget/goals"), ("sub_goal", "/widget/sub-goal"),
                        ("now_playing", "/widget/now-playing"), ("countdown", "/widget/countdown"),
                        ("soundboard", "/widget/soundboard")):
        assert f'data-palette-card="{slug}" data-palette-route="{route}"' in PANEL, slug


def test_live_recolor_uses_url_params_and_design_forms():
    # пипетка/свотч → превью перекрашивается сразу (accent/bg через URL)
    assert "function waCardApplyLook(" in SESSION
    assert "searchParams.set('accent'" in SESSION
    assert "searchParams.set('bg'" in SESSION
    # дизайн-виджеты (tts/chat-reader) сохраняют цвет в widget_design_*
    assert "waDesignSave(designWidget)" in SESSION
    # честный OBS URL в карточке обновляется вместе с превью
    assert "widget-url-form input" in SESSION


def test_appearance_js_applies_validated_accent_and_bg():
    assert "params.get('accent')" in APPEARANCE
    assert "params.get('bg')" in APPEARANCE
    # инъекция невозможна: только строгий hex
    assert "/^#?[0-9a-fA-F]{6}$/" in APPEARANCE
    assert "--widget-theme-accent" in APPEARANCE and "--w-accent" in APPEARANCE


def test_ready_themes_one_click():
    assert "WA_CARD_THEMES" in SESSION
    for theme in ("neon", "minimal", "gradient", "dark"):
        assert f"{theme}:" in SESSION
        assert f"widgets.theme_{theme}" in SESSION
    assert "function waCardApplyTheme(" in SESSION


def test_brand_palette_i18n_three_languages():
    for key in ("widgets.brand_palette", "widgets.brand_palette_hint", "widgets.brand_color",
                "widgets.brand_apply", "widgets.pick_color", "widgets.look_applied",
                "widgets.theme_neon", "widgets.theme_minimal", "widgets.theme_gradient",
                "widgets.theme_dark"):
        assert SESSION.count(f"'{key}'") >= 3, key
