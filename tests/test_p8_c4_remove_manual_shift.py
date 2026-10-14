"""P8-C4: ручной Personality Shift убран.

Вердикт владельца: карточку «🎭 Personality Shift» удалить; авто-эволюция
характера остаётся через learning («Обучение (предложения)»); модуль
personality_shift.py помечен deprecated и остаётся только для внутренней
автоматики (raid-сдвиг).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_manual_shift_card_removed():
    brain = (ROOT / "templates" / "partials" / "brain.html").read_text(encoding="utf-8")
    assert 'id="shiftEnabled"' not in brain, "карточка Personality Shift вернулась"
    assert 'id="shiftIntensity"' not in brain


def test_manual_shift_js_removed():
    js11 = (ROOT / "static" / "app" / "11_brain_v16.js").read_text(encoding="utf-8")
    assert "async function loadShift" not in js11
    assert "async function shiftSet" not in js11
    assert "loadShift()" not in js11, "вызов loadShift остался в init-цепочке"
    js9 = (ROOT / "static" / "app" / "09_brain_p3.js").read_text(encoding="utf-8")
    assert "'brainx.shift'" not in js9, "строка Personality Shift осталась в инспекторе"


def test_manual_shift_routes_removed():
    src = (ROOT / "app" / "routes_snippets.py").read_text(encoding="utf-8")
    assert '"/api/accounts/{account_id}/shift"' not in src, \
        "ручные GET/POST /shift роуты вернулись"
    # автоматика (raid) сохранена
    assert "/api/accounts/{account_id}/shift/trigger" in src


def test_personality_shift_endpoint_removed():
    """C4 (PLAN_TODO ТРЕК 1): POST /personality-shift писал в _shifts, который никто не читал."""
    src = (ROOT / "app" / "routes_persona_presets.py").read_text(encoding="utf-8")
    assert "personality-shift" not in src, "ручной роут personality-shift вернулся"
    assert "personality_shifts" not in src, "мёртвое in-memory хранилище _shifts вернулось"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/personality-shift" not in readme, "README всё ещё документирует удалённый роут"


def test_module_marked_deprecated_and_automation_intact():
    mod = (ROOT / "app" / "personality_shift.py").read_text(encoding="utf-8")
    assert "DEPRECATED P8-C4" in mod
    ca = (ROOT / "app" / "chat_analyzer.py").read_text(encoding="utf-8")
    assert "shift_manager.trigger" in ca, "автоматика raid-сдвига сломалась"
