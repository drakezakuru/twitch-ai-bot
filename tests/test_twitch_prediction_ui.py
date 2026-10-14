"""Track 6.10: standalone native Twitch Predictions panel contract."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "partials" / "widgets.html").read_text(encoding="utf-8")
I18N = (ROOT / "static" / "app" / "15_feedback_2908.js").read_text(encoding="utf-8")


def test_prediction_outcomes_are_separate_dynamic_inputs():
    assert 'id="waPredictionOutcomes"' in TEMPLATE
    assert TEMPLATE.count('class="input wa-prediction-outcome"') == 2
    assert 'id="waPredictionAddOutcome"' in TEMPLATE
    assert 'id="waPredictionOutcomeCount"' in TEMPLATE


def test_prediction_window_controls_expose_helix_limits():
    assert 'min="30" max="1800"' in TEMPLATE
    assert 'id="waPredictionWindowUnit"' in TEMPLATE


def test_prediction_ui_strings_are_translated_in_all_panel_languages():
    keys = (
        "widgets.prediction.title", "widgets.prediction.hint",
        "widgets.prediction.title_placeholder", "widgets.prediction.window_hint",
        "widgets.prediction.outcome_placeholder", "widgets.prediction.add_outcome",
        "widgets.prediction.invalid_window", "widgets.prediction.created",
    )
    for key in keys:
        assert I18N.count(f"'{key}':") == 3, key


def test_prediction_lifecycle_strings_are_translated_in_all_panel_languages():
    for key in (
        "widgets.prediction.refresh", "widgets.prediction.no_active", "widgets.prediction.lock",
        "widgets.prediction.resolve", "widgets.prediction.cancel", "widgets.prediction.choose_winner",
        "widgets.prediction.cancel_confirm", "widgets.prediction.updated",
    ):
        assert I18N.count(f"'{key}':") == 3, key
