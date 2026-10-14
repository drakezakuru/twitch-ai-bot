"""Общий gate 2C: у каждого виджета есть ветка `?preview=1` и тёмная схема.

R-ВИД1/R-ВИД2 (`docs/PRODUCT_RULES.md`): карточка в панели показывает
`preview_url` в iframe, поэтому виджет без ветки превью даёт белый/пустой
прямоугольник. Ловим это по всей папке `widgets/`, а не по списку — новый
виджет попадает под правило автоматически.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = sorted(p for p in (ROOT / "widgets").glob("*/index.html"))

# Виджеты, которые рисуют представительный кадр без данных вообще:
# автономная анимация не зависит ни от API, ни от WS.
SELF_RENDERING = {"animated-bg", "mascot", "anime-runner"}


def _ids(path: Path) -> str:
    return path.parent.name


@pytest.mark.parametrize("widget", WIDGETS, ids=_ids)
def test_widget_declares_dark_color_scheme(widget: Path):
    assert "color-scheme" in widget.read_text(encoding="utf-8"), _ids(widget)


@pytest.mark.parametrize("widget", WIDGETS, ids=_ids)
def test_widget_has_preview_branch(widget: Path):
    name = _ids(widget)
    if name in SELF_RENDERING:
        pytest.skip(f"{name}: автономная анимация — превью живое без данных")
    html = widget.read_text(encoding="utf-8")
    assert "'preview'" in html or '"preview"' in html, (
        f"{name}: нет ветки ?preview=1 — карточка панели будет пустой"
    )


@pytest.mark.parametrize("widget", WIDGETS, ids=_ids)
def test_widget_placeholders_are_rendered_by_routes(widget: Path):
    """Каждый __PLACEHOLDER__ в HTML обязан подставляться роутом.

    Иначе виджет уезжает в OBS с текстом `__TTS_ICON__` вместо иконки.
    """
    import re

    html = widget.read_text(encoding="utf-8")
    placeholders = set(re.findall(r"__[A-Z_]+__", html))
    if not placeholders:
        return
    routes = (ROOT / "app" / "widgets.py").read_text(encoding="utf-8")
    extra = (ROOT / "app" / "routes.py").read_text(encoding="utf-8")
    missing = [p for p in sorted(placeholders) if p not in routes and p not in extra]
    assert not missing, f"{_ids(widget)}: роут не подставляет {missing}"
