"""Q13: blur-guard — простая настройка, остальное в «Дополнительно».

Форма читается как «Защита: вкл/выкл · Чувствительность · Длительность блюра ·
Своя картинка (режим)»; интервал/pre-delay/плотность/промпт/категории спрятаны
в <details id="waBgAdvanced"> «Дополнительно». Существующие значения не
сбрасываются: модель настроек (blur_guard_settings) и все id контролов не
менялись — это перестройка формы, а не миграция данных.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")
SESSION = (ROOT / "static/app/13_widgets_session.js").read_text(encoding="utf-8")

CARD = PANEL.split("<!-- §13: Blur Guard", 1)[1].split("<!-- Голосование:", 1)[0]

PRIMARY_ROW = ["waBgEnabled", "waBgSensitivity", "waBgDuration", "waBgProtectionMode"]
ADVANCED_FIELDS = ["waBgInterval", "waBgPreDelay", "waBgPercent", "waBgPercentRange",
                   "waBgPrompt", "waBgCategories"]


def test_primary_row_is_simple():
    primary = CARD.split('id="waBgAdvanced"', 1)[0]
    for control in PRIMARY_ROW:
        assert f'id="{control}"' in primary, control
    # «Своя картинка» — режим с условными полями картинки/OBS рядом
    assert 'id="waBgImageFields"' in primary
    assert 'id="waBgObsFields"' in primary


def test_advanced_details_holds_the_rest():
    advanced = CARD.split('id="waBgAdvanced"', 1)[1].split("</details>", 1)[0]
    for control in ADVANCED_FIELDS:
        assert f'id="{control}"' in advanced, control
    assert 'data-i18n="blur_guard.advanced"' in CARD


def test_no_control_lost_or_renamed():
    # все контракты контролов сохранены (id и обработчики на месте)
    for anchor in ("waBgProtectionMode", "waBgDuration", "waBgPercentRange", "waBgSensitivity",
                   "waBgEnabled", "waBgImage", "waBgObsSource", "waBgObsFilter", "waBgPrompt",
                   "waBgCategories", "waBgStatus", "waBgPreviewLayer", "blurZonesList"):
        assert f'id="{anchor}"' in CARD, anchor
    # логика JS не менялась
    for fn in ("waBgModeSync", "waBgPreviewSync", "waBgSave", "waBgBind", "waBgImageUpload"):
        assert fn in SESSION, fn


def test_advanced_i18n_three_languages():
    assert SESSION.count("'blur_guard.advanced'") == 3
