"""ТРЕК 2C Wave 2 (BORROW): контракт состояний виджета.

Тот же гейт, что и в Wave 1 (`test_widget_states_wave1.py`), только для
BORROW-виджетов из canonical inventory: карточка обязана
рисовать представительное `?preview=1`, а оверлей — называть empty/error
своими словами, а не показывать «всё хорошо» или пустой экран (R-ВИД1/R-ВИД2).
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "widgets"

# Wave 2 BORROW: живые виджеты (poll-overlay выведен из эксплуатации в 2A).
BORROW_WIDGETS = [
    "goals",
    "now-playing",
    "sub-goal",
    "schedule",
    "follower-ticker",
    "lower-third",
    "chat-highlight",
    "chat-roulette",
    "song-request",
    "donation-challenge",
    "hype-meter",
    "media-share",
    "soundboard",
    "emoji-leaderboard",
]


def _html(folder: str) -> str:
    return (WIDGETS / folder / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("folder", BORROW_WIDGETS)
def test_borrow_widget_has_preview_branch(folder: str):
    """Без ветки ?preview=1 карточка в панели показывает пустой прямоугольник."""
    html = _html(folder)
    assert "preview" in html, f"{folder}: нет ветки ?preview=1"
    assert "#0f0f1a" in html, f"{folder}: превью не выставляет тёмный фон карточки"


@pytest.mark.parametrize(
    "folder,markers",
    [
        ("goals", ("goals.unavailable", "common.disconnected", "goals.empty")),
        ("schedule", ("common.unavailable_http", "common.disconnected", "schedule.empty")),
        ("sub-goal", ("common.unavailable_http", "common.disconnected")),
        ("follower-ticker", ("common.unavailable_http", "common.disconnected")),
        ("song-request", ("common.unavailable_http", "common.disconnected", "song-request.empty")),
        ("donation-challenge", ("common.unavailable_http", "common.disconnected", "donation-challenge.empty")),
        ("soundboard", ("common.disconnected", "soundboard.unavailable")),
        ("emoji-leaderboard", ("common.unavailable_http", "common.disconnected")),
        ("media-share", ("offline", "youtubeOffline")),
        ("chat-roulette", ("chat-roulette.few",)),
        ("hype-meter", ("hype-meter.disconnected",)),
    ],
)
def test_borrow_widget_states_are_explicit(folder: str, markers: tuple[str, ...]):
    html = _html(folder)
    for marker in markers:
        assert re.search(r"(?:WidgetI18n\.t|wt|tx|showGoalState)\(['\"]" + re.escape(marker) + r"['\"]", html), folder


@pytest.mark.parametrize("folder", ["now-playing", "lower-third", "chat-highlight"])
def test_transient_overlays_hide_on_error(folder: str):
    """Оверлеи «появись и исчезни» при обрыве панели убираются из кадра.

    Иначе в OBS навсегда зависает последний трек/имя/сообщение — это ровно тот
    «фиктивный success state», который запрещает план Wave 1-2.
    """
    html = _html(folder)
    tail = html.split("catch", 1)[1]
    assert "hidden" in tail or "remove('show')" in tail or "add('hide')" in tail, folder


def test_hype_meter_does_not_fake_zero_without_ws():
    """0% без соединения неотличим от «чат молчит» — состояние названо явно."""
    html = _html("hype-meter")
    assert "connected = false" in html
    assert "WidgetI18n.t('hype-meter.disconnected')" in html


def test_media_share_preview_does_not_load_youtube():
    """Карточка в панели не должна тянуть YouTube IFrame API ради превью."""
    html = _html("media-share")
    assert "if (IS_PREVIEW){" in html
    runtime_branch = html.split("} else if (!CHANNEL) {", 1)[1].split("</script>", 1)[0]
    assert "loadYouTubeApi();" in runtime_branch


def test_retired_banner_removed_from_kept_widgets():
    """owner survey 03.09: media-share (Q8) и emoji-leaderboard (Q34) оставлены.

    Баннер «Виджет не актуален» от 31.08 противоречил этому решению.
    """
    for folder in ("media-share", "emoji-leaderboard"):
        assert "Виджет не актуален" not in _html(folder), folder
        assert "WIDGET NOT RELEVANT" not in _html(folder), folder
