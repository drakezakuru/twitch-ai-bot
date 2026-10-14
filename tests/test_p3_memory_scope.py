"""P3 §1.4 → P8-C2: «чья память».

История: скоуп shared-фактов (cross_bot_memory_*) существовал с P3.
P8-C2 (вердикт владельца 02.09): общая память между ботами УДАЛЕНА —
факты живут только per-bot (user_memory), общие мигрировали к ботам.
Тесты теперь проверяют ОТРИЦАНИЕ: shared-настройки и UI не возвращаются.
"""
from __future__ import annotations

from pathlib import Path

from tests import _panel_js

ROOT = Path(__file__).resolve().parents[1]


def test_shared_memory_settings_removed():
    src = (ROOT / "app" / "chat_analyzer.py").read_text(encoding="utf-8")
    assert "cross_bot_memory_enabled" not in src, "общая память вернулась в настройки"

    routes = (ROOT / "app" / "routes.py").read_text(encoding="utf-8")
    assert "/api/shared-user-facts" not in routes, "роуты shared-user-facts вернулись"

    preview = (ROOT / "app" / "brain_preview.py").read_text(encoding="utf-8")
    assert "memory_scope" not in preview and "shared_facts" not in preview


def test_shared_memory_ui_removed():
    tpl = (ROOT / "templates" / "partials" / "bots.html").read_text(encoding="utf-8")
    assert 'id="analyzerCrossBotMemory"' not in tpl
    assert 'id="sharedFactsList"' not in tpl
    assert "loadSharedFacts" not in tpl
    js = _panel_js.panel_js()
    assert "loadSharedFacts" not in js
    assert "/api/shared-user-facts" not in js
