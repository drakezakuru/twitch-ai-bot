"""P8-A3: стрим-инструменты показываются не-модератору.

C-010 migration: поведение loadStreamTools (ok=false → форма/история скрыты
целиком, ok=true → форма с селектами по STREAM_TOOL_ORDER и режимами, failure
→ error-строка) доказывается исполнением продакшн-кода в Node VM —
`tests/panel_stream_tools.test.js`. Здесь остаются non-runtime контракты:
ids карточки в bots.html и класс .hidden в CSS.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOTS_HTML = ROOT / "templates" / "partials" / "bots.html"


def test_stream_tools_manual_form_has_ids():
    html = BOTS_HTML.read_text(encoding="utf-8")
    for elem_id in ("streamToolsModes", "streamToolsManual", "streamToolsHistoryHead", "streamToolsHistory"):
        assert f'id="{elem_id}"' in html, f"нет #{elem_id} в bots.html"


def test_hidden_css_class_exists():
    """Класс .hidden обязан существовать в CSS (иначе скрытие не работает)."""
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.hidden\s*\{", css), "нет класса .hidden в app.css"


def test_stream_tools_runtime_behavior():
    """Node VM исполняет продакшн loadStreamTools (non-moderator/moderator/failure)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/panel_stream_tools.test.js"],
        cwd=ROOT,
        check=True,
    )
