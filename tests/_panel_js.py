"""P5-сплит app.js: единое чтение JS-кода панели для текстовых якорь-тестов.

`static/app.js` — ядро (первый скрипт в templates/base.html); `static/app/NN_*.js`
— чанки того же исходного монолита в исходном порядке строк. Тесты, которые
грепают панельный JS, читают его через panel_js()/panel_js_files(), чтобы
P5-сплит не ломал якоря (конкатенация в порядке загрузки = старый app.js).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CORE = ROOT / "static" / "app.js"
_CHUNKS_DIR = ROOT / "static" / "app"


def panel_js_files() -> list[Path]:
    """Все JS-файлы панели в порядке <script>-тегов templates/base.html."""
    files = [_CORE] if _CORE.exists() else []
    if _CHUNKS_DIR.exists():
        files += sorted(_CHUNKS_DIR.glob("*.js"))
    return files


def panel_js() -> str:
    """Конкатенация всех JS-файлов панели в порядке загрузки браузером."""
    return "\n".join(p.read_text(encoding="utf-8") for p in panel_js_files())
