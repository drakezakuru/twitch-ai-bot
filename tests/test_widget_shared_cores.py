"""Wave 5/6 guard: виджет, использующий общее ядро, обязан его подключать.

Ошибка, ради которой этот тест написан (поймана вживую 04.09): в
`anime-runner` рантайм перевели на `CharacterCore`, но тег
`<script src="/widget/_shared/character-core.js">` забыли — страница молча
падала на `ReferenceError: CharacterCore is not defined`, а в OBS-сцене это
выглядит как «персонаж перестал двигаться», без единого признака в статике.

Здесь проверяется симметрия «используешь → подключил» по всей папке
`widgets/`, поэтому новый виджет попадает под правило автоматически.
Полный рантайм-прогон в реальном DOM — `scripts/verify_widget_runtime.js`
(требует поднятой панели и jsdom, поэтому не входит в focused-тесты).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = sorted(p for p in (ROOT / "widgets").glob("*/index.html"))
SHARED = ROOT / "widgets" / "_shared"

# global -> файл общего ядра, который его определяет.
CORES = {
    "TtsCore": "tts-core.js",
    "CharacterCore": "character-core.js",
    "WidgetBus": "widget-bus-client.js",
}


def _ids(path: Path) -> str:
    return path.parent.name


@pytest.mark.parametrize("core_global,filename", sorted(CORES.items()))
def test_shared_core_file_exists_and_defines_global(core_global: str, filename: str):
    path = SHARED / filename
    assert path.is_file(), f"нет общего ядра {filename}"
    assert f"window.{core_global}" in path.read_text(encoding="utf-8"), (
        f"{filename} не объявляет window.{core_global}"
    )


@pytest.mark.parametrize("widget", WIDGETS, ids=_ids)
def test_widget_loads_every_shared_core_it_uses(widget: Path):
    html = widget.read_text(encoding="utf-8")
    # Не считаем упоминания внутри комментариев-ссылок на файл ядра.
    body = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
    for core_global, filename in CORES.items():
        if not re.search(rf"\b{core_global}\s*\.", body):
            continue
        assert f"_shared/{filename}" in html, (
            f"{_ids(widget)}: использует {core_global}, но не подключает {filename} — "
            f"страница упадёт с ReferenceError и виджет замрёт в OBS"
        )


def test_tts_family_shares_one_transport():
    """Wave 5: четыре TTS-виджета не держат собственный `new WebSocket`."""
    for folder in ("tts-raw", "tts-bot", "chat-reader", "tts-chat-overlay"):
        html = (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")
        assert "_shared/tts-core.js" in html, f"{folder}: не подключает общий transport"
        assert "new WebSocket(" not in html, (
            f"{folder}: свой WebSocket вместо общего TtsCore.connect"
        )


def test_characters_share_one_event_loop():
    """Wave 6: mascot и anime-runner не поллят события каждый по-своему."""
    for folder in ("mascot", "anime-runner"):
        html = (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")
        assert "_shared/character-core.js" in html, f"{folder}: не подключает общее ядро"
        assert "public/recent-events" not in html, (
            f"{folder}: свой poll событий вместо общего CharacterCore.start"
        )
