"""Q15a (DEC-OWNER-016): у бота явный выбор Vision «общая (по умолчанию) / своя».

Контракт хранения не меняется: пустой ``ai_vision_model_override`` = общая база
(``global_vision_override`` из Настроек, иначе дефолт провайдера) — это уже
семантика ``AIService._resolve``. Q15a делает выбор явным в UI и честно
описывает поле «Общая Vision-модель» в Настройках (поле остаётся).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_bot_card_has_vision_mode_selector():
    html = _read("templates", "partials", "bots.html")
    assert 'id="botAIVisionMode"' in html
    assert 'value="shared"' in html and 'value="own"' in html
    assert "onchange=\"onBotVisionModeChange()\"" in html
    assert 'id="botAIVisionModel"' in html and "hidden" in html, \
        "поле «своя» скрыто, пока не выбран режим «Своя»"
    # E1-нов: поле «Общая Vision-модель» в Настройках остаётся (не удаляется)
    settings = _read("templates", "partials", "settings.html")
    assert 'id="globalVisionModel"' in settings
    assert 'data-i18n="label.global_vision"' in settings


def test_vision_mode_logic_in_bots_js():
    js = _read("static", "app", "03_bots.js")
    assert "function onBotVisionModeChange(" in js
    assert "_botVisionModeFromOverride(ov.ai_vision_model_override)" in js, \
        "режим выводится из пустоты override"
    assert "mode === 'own' ? vm : ''" in js, \
        "«своя» с пустым полем сохраняется как «общая» (пустая строка)"
    assert "'botAIVisionMode'" in js and "bindDirtyWatch('botAI'" in js


def test_vision_i18n_in_three_languages():
    js = _read("static", "app.js")
    for key in ("'label.vision_mode':", "'bot.vision_shared':", "'bot.vision_own':",
                "'bot.vision_own_ph':"):
        assert js.count(key) == 3, key
    # честное описание общей базы в трёх языках
    assert js.count("Это общая база") == 1
    assert js.count("This is the shared base") == 1
    assert js.count("Це спільна база") == 1
