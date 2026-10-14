"""ТРЕК 2C Wave 1 (KEEP): контракт состояний виджета.

R-ВИД1/R-ВИД2 (docs/PRODUCT_RULES.md): у каждой карточки живое тёмное превью,
а сам оверлей обязан честно показывать loading/empty/error вместо пустоты или
выдуманного успеха. Проверяем вызовы переводов состояний. Offline Node-тесты проверяют рендеры
на RU/EN/UA; browser/OBS-приёмка остаётся отдельной.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "widgets"

# Wave 1 KEEP: виджеты, где владелец видит состояние прямо в OBS-сцене.
KEEP_WIDGETS = [
    "stream-session",
    "countdown",
    "clip-moments",
    "mod-feed",
    "subathon-timer",
    "blur-guard-v2",
    "tts-chat-overlay",
    "animated-bg",
]


def _html(folder: str) -> str:
    return (WIDGETS / folder / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("folder", KEEP_WIDGETS)
def test_keep_widget_has_representative_preview(folder: str):
    """?preview=1 обязан рисовать представительное состояние без live-данных."""
    html = _html(folder)
    if folder == "animated-bg":
        # Автономный эффект: он и без данных всегда рисует представительный кадр.
        pytest.skip("animated-bg не зависит от API — превью всегда живое")
    assert "preview" in html, f"{folder}: нет ветки ?preview=1 — карточка будет пустой"
    assert "'preview'" in html or '"preview"' in html, folder


@pytest.mark.parametrize(
    "folder,markers",
    [
        ("stream-session", ("stream-session.offline", "common.unavailable", "common.loading")),
        ("countdown", ("countdown.idle", "countdown.paused", "common.disconnected")),
        ("clip-moments", ("clip-moments.unavailable_http", "common.disconnected", "clip-moments.empty")),
        ("mod-feed", ("mod-feed.empty", "common.disconnected")),
        ("subathon-timer", ("subathon-timer.idle", "common.disconnected")),
        ("tts-chat-overlay", ("common.disconnected",)),
    ],
)
def test_keep_widget_states_are_explicit(folder: str, markers: tuple[str, ...]):
    html = _html(folder)
    for marker in markers:
        assert re.search(r"(?:WidgetI18n\.t|wt)\(['\"]" + re.escape(marker) + r"['\"]", html), folder


def test_stream_session_does_not_tick_without_live_session():
    """Uptime без живой сессии показывает прочерк, а не растущее время."""
    html = _html("stream-session")
    assert "'—:—:—'" in html


def test_animated_bg_bounds_density_and_respects_reduced_motion():
    html = _html("animated-bg")
    assert "MAX_COUNT" in html and "Math.min(MAX_COUNT" in html
    assert "prefers-reduced-motion" in html
    assert "if(!REDUCED)requestAnimationFrame(step)" in html


def test_blur_guard_preview_shows_blur_without_camera():
    """Q36: единственный Blur Guard — превью обязано показывать блюр и зоны."""
    html = _html("blur-guard-v2")
    assert "demoScene" in html
    assert 'qs.get("preview") === "1"' in html
    assert "activateBlur(" in html.split('qs.get("preview") === "1"', 1)[1]


def test_tts_overlay_preview_does_not_open_live_ws():
    """Карточка не должна висеть на живом WS: превью крутит демо-ленту."""
    html = _html("tts-chat-overlay")
    assert "if (IS_PREVIEW) {" in html
    assert "} else {\n            connect();" in html
