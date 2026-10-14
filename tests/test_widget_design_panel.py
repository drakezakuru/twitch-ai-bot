"""Panel contract for chat-reader and raw TTS visual customization."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_design_cards_have_color_controls_actions_and_live_previews():
    from jinja2 import Template
    from app.widget_inventory import WIDGET_INVENTORY

    source = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
    template = Template(source).render(widget_inventory=WIDGET_INVENTORY)

    assert "waDesignForm-chat-reader" in template
    assert "waDesignForm-tts-raw" in template
    assert 'type="color"' in template
    for field in (
        "theme", "accent", "bg", "opacity", "radius", "font", "size",
        "scale", "pos", "shadow", "hold", "maxw", "showstatus",
    ):
        assert f'data-design-field="{field}"' in template
    assert "waDesignSave" in template
    assert "waDesignCopy" in template
    assert "data-design-preview-frame" in template
    assert "widget-preview" in template


def test_design_panel_updates_preview_and_persists_settings():
    js = (ROOT / "static/app/07_widgets.js").read_text(encoding="utf-8")

    assert "waDesignLoad('chat-reader')" in js
    assert "waDesignLoad('tts-raw')" in js
    assert "`/api/widgets/design/${widget}`" in js
    assert "frame.src = _waDesignUrl(widget, true)" in js
    assert "url.searchParams.set('preview', '1')" in js


def test_design_labels_are_translated_in_all_three_languages():
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")

    for key in (
        "widgets.design_theme", "widgets.design_accent", "widgets.design_bg",
        "widgets.design_opacity", "widgets.design_position", "widgets.design_status",
    ):
        assert js.count(f"'{key}'") == 3

