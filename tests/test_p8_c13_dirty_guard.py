"""P8-C13: guard несохранённых изменений (вариант владельца — не autosave).

C-010 migration: поведение (beforeunload, cancel/accept навигации, save/clear,
идемпотентность bindDirtyWatch) доказывается исполнением продакшн-кода в Node VM
(`tests/panel_dirty_guard.test.js`). Здесь остаются только non-runtime контракты:
переводы dirty.confirm ×3 языка.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
APP_JS = ROOT / "static" / "app.js"


def test_dirty_confirm_i18n_all_langs():
    lines = [ln for ln in APP_JS.read_text(encoding="utf-8").splitlines() if "'dirty.confirm':" in ln]
    assert len(lines) >= 3, f"dirty.confirm: переводов {len(lines)}, нужно ≥3"


def test_dirty_guard_runtime_behavior():
    """Node VM исполняет продакшн markDirty/confirmDirty/bindDirtyWatch/beforeunload."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/panel_dirty_guard.test.js"],
        cwd=ROOT,
        check=True,
    )
