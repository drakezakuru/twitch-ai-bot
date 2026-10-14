"""P5 PLAN.md: целостность сплита static/app.js на чанки static/app/NN_*.js.

Найденный при сплите баг (const _loadWidgetsAdminPrev5 объявлен дважды на
верхнем уровне → весь app.js падал с SyntaxError в браузере) здесь
запечатан тремя проверками:
1. base.html подключает ядро + все чанки по порядку (проводка не рассыхается);
2. top-level const/let-имена не дублируются сквозь все JS-файлы панели
   (классические <script> делят global lexical scope);
3. если в системе есть node — синтакс-проверка каждого файла и конкатенации.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from tests import _panel_js

ROOT = Path(__file__).resolve().parents[1]


def test_base_html_wires_all_chunks_in_order():
    html = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    srcs = re.findall(r'<script src="/static/([^"?]+)\?', html)
    assert srcs and srcs[0] == "app.js", "app.js должен идти первым"
    chunk_srcs = [s for s in srcs if s.startswith("app/")]
    on_disk = [f"app/{p.name}" for p in _panel_js.panel_js_files()[1:]]
    assert chunk_srcs == on_disk, (
        f"base.html и static/app/ разошлись:\nbase: {chunk_srcs}\ndisk: {on_disk}")
    assert chunk_srcs == sorted(chunk_srcs), "порядок тегов должен совпадать с NN_-префиксом"


def test_no_duplicate_toplevel_const_let_across_panel_js():
    dupes: list[str] = []
    for kind in ("const", "let"):
        seen: dict[str, str] = {}
        for path in _panel_js.panel_js_files():
            for ln in path.read_text(encoding="utf-8").splitlines():
                m = re.match(rf"{kind} ([A-Za-z_$][\w$]*)", ln)
                if m:
                    name = m.group(1)
                    if name in seen and seen[name] != path.name:
                        dupes.append(f"{kind} {name}: {seen[name]} + {path.name}")
                    seen.setdefault(name, path.name)
    assert not dupes, (
        "дубликаты top-level const/let сквозь JS-файлы панели (SyntaxError "
        "в браузере — второй <script> падает целиком):\n" + "\n".join(dupes))


def test_node_syntax_check_when_available():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node недоступен")
    files = _panel_js.panel_js_files()
    assert len(files) > 1, "сплит должен существовать"
    for path in files:
        r = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        assert r.returncode == 0, f"{path.relative_to(ROOT)}: {r.stderr[:400]}"
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(_panel_js.panel_js())
        tmp = fh.name
    try:
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        assert r.returncode == 0, "конкатенация (общий scope) невалидна: " + r.stderr[:400]
    finally:
        Path(tmp).unlink(missing_ok=True)
