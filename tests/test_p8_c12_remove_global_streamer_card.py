"""P8-C12: карточка «О стримере (глобально)» убрана из Настроек.

Вердикт владельца: профиль стримера живёт в «Мозге бота» → «Профиль
стримера»; в Настройках карточка была только указателем и путала.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_settings_has_no_global_streamer_card():
    html = (ROOT / "templates" / "partials" / "settings.html").read_text(encoding="utf-8")
    assert "streamer.global_title" not in html, \
        "карточка «О стримере (глобально)» всё ещё в Настройках"
    # профиль стримера в Мозге не пострадал
    brain = (ROOT / "templates" / "partials" / "brain.html").read_text(encoding="utf-8")
    assert "bspChannel" in brain or "Профиль стримера" in brain


def test_load_settings_does_not_call_gsp_loader():
    src = (ROOT / "static" / "app" / "04_chat_settings.js").read_text(encoding="utf-8")
    assert "loadGlobalStreamerChannels().then" not in src, \
        "loadSettings всё ещё зовёт мёртвый gsp-загрузчик"


def test_brain_streamer_profile_loader_intact():
    src = (ROOT / "static" / "app" / "15_feedback_2908.js").read_text(encoding="utf-8")
    assert "loadGlobalStreamerChannels('bsp')" in src.replace('"', "'") or "'bsp'" in src
