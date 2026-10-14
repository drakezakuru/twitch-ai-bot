"""Q15b (E2/E3): один список моделей провайдера с типами + дропдауны бота.

E2: у кастом-провайдера один редактор списка моделей с пометкой типа
(чат/vision/оба); хранение ``models``+``vision_models`` сохраняется — UI
собирает оба списка из одной таблицы, дубли схлопываются.
E3: у бота при ``custom:*``-провайдере чат- и vision-модели — дропдауны из
его списков (ручной ввод строкой убран); у встроенных провайдеров — прежний
свободный ввод. Контракт Q15a не меняется: пустой ``ai_vision_model_override``
= общая база.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_provider_form_has_single_typed_model_editor():
    settings = _read("templates", "partials", "settings.html")
    assert 'id="cpModelsEditor"' in settings, "один редактор списка моделей"
    assert 'onclick="cpAddModelRow()"' in settings
    assert 'id="cpModels"' not in settings, "две textarea (chat/vision) заменены одним списком"
    assert 'id="cpVisionModels"' not in settings
    assert 'data-i18n="cp.models_types_hint"' in settings


def test_provider_js_keeps_storage_contract():
    js = _read("static", "app", "08_providers_moderation.js")
    # хранение models+vision_models сохраняется: save шлёт оба списка
    assert "const lists = _cpListsFromRows()" in js
    assert "const models = lists.models" in js
    assert "const vision_models = lists.vision_models" in js
    assert "models, vision_models }));" in js
    # edit восстанавливает строки из обоих списков (модель в обоих = both)
    assert "function _cpRowsFromProvider(" in js
    assert "_cpModelRows = _cpRowsFromProvider(p)" in js


def test_bot_card_has_model_dropdowns_for_custom_providers():
    html = _read("templates", "partials", "bots.html")
    assert 'id="botAIModelSelect"' in html
    assert 'id="botAIVisionModelSelect"' in html
    assert 'list="botAIVisionModels"' not in html and 'id="botAIVisionModels"' not in html, \
        "ручной ввод через datalist убран"
    # свободный ввод остаётся для встроенных провайдеров
    assert 'id="botAIModel"' in html and 'id="botAIVisionModel"' in html


def test_bots_js_dropdown_logic_and_q15a_contract():
    js = _read("static", "app", "03_bots.js")
    assert "function _botNamedProvider(" in js
    assert "function _fillModelSelect(" in js
    assert "function refreshBotAIModels(" in js
    assert "refreshBotAIVisionModels" not in js, "старый рефрешер заменён"
    assert "function onBotAIProviderChange(" in js, "смена провайдера сбрасывает модели"
    # у custom:* чтение из дропдауна, у остальных — из свободного ввода
    assert "$('botAIModelSelect')?.value || ''" in js
    assert "$('botAIVisionModelSelect')?.value || ''" in js
    # контракт Q15a сохранён: «своя» с пустым полем = общая (пустая строка)
    assert "data.ai_vision_model_override = mode === 'own' ? vm : ''" in js


def test_q15b_i18n_in_three_languages():
    js = _read("static", "app.js")
    for key in ("'cp.add_model':", "'cp.models_types_hint':", "'cp.type_both':",
                "'cp.no_models':", "'bot.model_default':", "'bot.vision_default':"):
        assert js.count(key) == 3, key
    # старые ключи двух textarea удалены во всех трёх словарях
    for key in ("'cp.vision_models_ph':", "'cp.vision_models_hint':", "'cp.models_ph':"):
        assert js.count(key) == 0, key
