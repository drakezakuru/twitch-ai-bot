"""Инлайн-скрипты всех виджетов обязаны быть синтаксически валидными.

Виджеты — самостоятельные HTML-файлы без сборки: опечатка в <script> раньше
всплывала только в OBS (виджет молча пустой). `scripts/check_widget_js.js`
ловит её на месте, этот тест прогоняет проверку по всей папке widgets/.
Так были найдены два мёртвых виджета: sub-goal (многострочная '…'-строка) и
tts-raw (двойное экранирование в regex).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_widget_js.js"
WIDGETS = sorted(p for p in (ROOT / "widgets").glob("*/index.html"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node не установлен в окружении")
@pytest.mark.parametrize("widget", WIDGETS, ids=lambda p: p.parent.name)
def test_widget_inline_scripts_parse(widget: Path):
    result = subprocess.run(
        ["node", str(CHECKER), str(widget)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr.strip() or result.stdout.strip()


def test_every_widget_folder_is_covered():
    disk = {p.parent.name for p in (ROOT / "widgets").glob("*/index.html")}
    assert disk == {p.parent.name for p in WIDGETS}
    assert disk, "папка widgets/ не должна быть пустой"
