"""Track 6.10: native Twitch Poll panel contract."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "partials" / "widgets.html").read_text(encoding="utf-8")
I18N = (ROOT / "static" / "app" / "15_feedback_2908.js").read_text(encoding="utf-8")


def test_poll_choices_are_separate_dynamic_inputs():
    assert 'id="waPollChoices"' in TEMPLATE
    assert TEMPLATE.count('class="input wa-poll-choice"') == 2
    assert 'id="waPollAddChoice"' in TEMPLATE
    assert 'id="waPollChoiceCount"' in TEMPLATE
    assert 'id="waPollChoices" class="input"' not in TEMPLATE


def test_poll_prediction_panel_runtime_behavior():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/twitch_poll_prediction_ui.test.js"],
        cwd=ROOT,
        check=True,
    )


def test_poll_ui_strings_are_translated_in_all_panel_languages():
    keys = (
        "widgets.poll.title", "widgets.poll.hint", "widgets.poll.title_placeholder",
        "widgets.poll.choice_placeholder", "widgets.poll.add_choice",
        "widgets.poll.choice_count", "widgets.poll.invalid_choices", "widgets.poll.created",
    )
    for key in keys:
        assert I18N.count(f"'{key}':") == 3, key
