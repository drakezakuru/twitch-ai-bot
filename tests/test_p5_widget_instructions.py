"""P5: кнопка «Инструкция» у карточек виджетов (OBS modal).

C-010 migration: open/replace/backdrop-close, canonical URL/size/defaults,
slug-specific parameters and escaping execute production showWidgetInstr in Node
VM (`tests/widget_instruction_modal.test.js`). Static assertions remain only for
registry-driven markup and ru/en/ua translation inventory.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from tests import _panel_js

ROOT = Path(__file__).resolve().parents[1]


def test_grid_cards_have_instruction_button():
    """Каждая registry-driven grid-card получает кнопку с route/slug/OBS size."""
    tpl = (ROOT / "templates" / "partials" / "widgets.html").read_text(encoding="utf-8")
    assert 'data-i18n="widgets.instr"' in tpl
    assert "showWidgetInstr('{{ widget.route }}', '{{ widget.slug }}', {{ widget.obs_width }}, {{ widget.obs_height }})" in tpl
    assert '{% for widget in widget_inventory %}' in tpl
    assert 'class="card widget-guide-card"' in tpl


def test_widget_instruction_i18n_all_langs():
    js = _panel_js.panel_js()
    for key in (
        "widgets.instr", "instr.title", "instr.steps", "instr.size_note",
        "instr.params", "instr.common_params", "instr.transparent",
        "widgets.obs_size", "widgets.obs_layout_overlay",
        "widgets.obs_layout_strip", "widgets.obs_layout_fullscreen",
    ):
        assert js.count(f"'{key}'") >= 3, key


def test_widget_instruction_runtime_behavior():
    """Node VM исполняет production showWidgetInstr."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/widget_instruction_modal.test.js"],
        cwd=ROOT,
        check=True,
    )
