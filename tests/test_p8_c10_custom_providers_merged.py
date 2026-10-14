"""P8-C10: custom providers объединены с глобальным и per-bot AI select.

C-010 migration: refresh/select lifecycle, stale selection, create/edit payload,
validation, failure и cache reload доказываются исполнением production-функций
в Node VM (`tests/panel_custom_providers.test.js`). Здесь остаётся только
non-runtime контракт карточки-редактора.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_custom_providers_card_is_list_editor():
    html = (ROOT / "templates" / "partials" / "settings.html").read_text(encoding="utf-8")
    assert 'id="customProvidersCard"' in html
    assert 'id="customProvidersList"' in html
    assert 'onclick="saveCustomProvider()"' in html


def test_custom_providers_runtime_behavior():
    """Node VM исполняет production merge custom providers в оба AI select."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/panel_custom_providers.test.js"],
        cwd=ROOT,
        check=True,
    )
