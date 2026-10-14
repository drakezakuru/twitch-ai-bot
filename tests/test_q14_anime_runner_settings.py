"""Q14: восстановленные настройки anime-runner в панели.

Виджет читает 19 настроек, бэкенд (/api/widgets/anime-runner PUT) принимает все;
в панельной форме после Wave-6 (wa2) осталось только 7 полей. История:
старый редактор (templates/index_v10_backup.html, widArSave) редактировал полный
набор — форма восстановлена, сам виджет не переписывался.
"""
from pathlib import Path

WIDGETS_HTML = Path("templates/partials/widgets.html").read_text()
FEEDBACK_JS = Path("static/app/15_feedback_2908.js").read_text()
LABELS_JS = Path("static/app/21_panel_labels.js").read_text()

_RESTORED_IDS = (
    "wa2ArEarsEnabled", "wa2ArEarsColor", "wa2ArEarsInner",
    "wa2ArGlovesEnabled", "wa2ArGlovesColor", "wa2ArShoes",
    "wa2ArShirtPattern", "wa2ArShorts", "wa2ArPathMode", "wa2ArPathPoints",
    "wa2ArPause", "wa2ArIdle", "wa2ArRandomPeriod",
)

_PAYLOAD_KEYS = (
    "ears_enabled", "ears_color", "ears_inner_color",
    "gloves_enabled", "gloves_color", "shoes_color", "shirt_pattern",
    "shorts_color", "path_mode", "path_points", "pause_chance",
    "idle_timeout_sec", "random_period_sec",
)

_I18N_KEYS = (
    "panel.runner.ears", "panel.runner.ears_color", "panel.runner.ears_inner",
    "panel.runner.gloves", "panel.runner.gloves_color", "panel.runner.shoes",
    "panel.runner.shorts", "panel.runner.shirt_pattern",
    "panel.runner.shirt_solid", "panel.runner.shirt_palm",
    "panel.runner.shirt_stripes", "panel.runner.path_mode",
    "panel.runner.path_lane", "panel.runner.path_custom",
    "panel.runner.path_random", "panel.runner.pause", "panel.runner.idle",
    "panel.runner.random_period", "panel.runner.details",
)


def test_form_has_restored_fields():
    for fid in _RESTORED_IDS:
        assert f'id="{fid}"' in WIDGETS_HTML, fid


def test_load_and_save_cover_restored_fields():
    for key in _PAYLOAD_KEYS:
        assert f"{key}:" in FEEDBACK_JS, key
        assert f"ar.{key}" in FEEDBACK_JS, key


def test_i18n_three_languages():
    for key in _I18N_KEYS:
        assert LABELS_JS.count("'" + key + "':") == 3, key


def test_widget_and_backend_untouched():
    # Восстановление — только в панели: виджет читает те же cfg-поля,
    # бэкенд-обработчик остался источником валидации.
    widget = Path("widgets/anime-runner/index.html").read_text()
    for key in ("ears_enabled", "shirt_pattern", "path_mode", "path_points",
                "random_period_sec", "pause_chance", "idle_timeout_sec"):
        assert f"cfg.{key}" in widget or key in widget, key
    backend = Path("app/widgets.py").read_text()
    assert 'put("/api/widgets/anime-runner")' in backend
    for key in _PAYLOAD_KEYS:
        assert f'payload.get("{key}"' in backend, key
