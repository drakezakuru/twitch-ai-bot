"""Every active widget has shared semantic or native common-theme coverage."""
from pathlib import Path

from app.widget_inventory import WIDGET_INVENTORY
from app.widgets import _WIDGET_THEME_COLORS


ROOT = Path(__file__).resolve().parents[1]
NATIVE_DESIGN_WIDGETS = {"chat-reader", "tts-raw"}


def _source(folder: str) -> str:
    return (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")


def test_all_active_widgets_support_the_common_theme_palette():
    for item in WIDGET_INVENTORY:
        if item.folder in NATIVE_DESIGN_WIDGETS:
            continue
        assert "widget-theme-" in _source(item.folder), item.slug

    assert set(_WIDGET_THEME_COLORS) == {"light", "neon", "fire", "glass", "mono"}
    for folder in NATIVE_DESIGN_WIDGETS:
        source = _source(folder)
        assert "__DESIGN_ACCENT__" in source
        assert "__DESIGN_BG_RGBA__" in source


def test_fullscreen_art_contracts_are_not_replaced_by_theme_surfaces():
    assert '<canvas id="c" class="widget-theme-surface"' not in _source("animated-bg")
    assert '<div id="player" class="widget-theme-surface"' not in _source("media-share")
    mascot = _source("mascot")
    assert 'class="mascot widget-theme-surface' not in mascot
    sub_goal = _source("sub-goal")
    assert 'class="scene widget-theme-surface' not in sub_goal
    blur = _source("blur-guard-v2")
    assert 'id="region" class="widget-theme-surface"' not in blur
    assert "#btnFalse:hover" in blur and "#btnMissed:hover" in blur and "#btnGood:hover" in blur


def test_special_overlays_theme_only_safe_auxiliary_surfaces():
    animated = _source("animated-bg")
    assert "banner widget-theme-surface widget-theme-text" in animated
    anime = _source("anime-runner")
    assert "say widget-theme-surface widget-theme-text" in anime
    assert "lane.className" in anime
    mascot = _source("mascot")
    assert "zZz widget-theme-accent" in mascot
    blur = _source("blur-guard-v2")
    assert "hidden widget-theme-surface widget-theme-text" in blur
