"""Behavior contracts for bot-card tab navigation and loader coverage."""
from __future__ import annotations

import re
from pathlib import Path
from tests import _panel_js

ROOT = Path(__file__).resolve().parents[1]


def _app_js() -> str:
    return _panel_js.panel_js()


def test_tab_switch_does_not_reset_form_fields():
    """showBotTab/showBotGroup меняют только видимость — поля не сбрасываются.

    Регресс-защита: если кто-то добавит сброс .value/innerHTML в функции
    переключения вкладок, несохранённые данные карточки бота начнут теряться.
    """
    js = _app_js()
    # Берём ВСЕ определения showBotTab/showBotGroup (их может быть несколько —
    # переопределение через повторный function-декларейшн).
    for name in ("showBotTab", "showBotGroup"):
        bodies = re.findall(rf"function {name}\([^)]*\) \{{(.*?)\n\}}", js, re.S)
        assert bodies, f"{name} не найден"
        for body in bodies:
            assert "classList" in body, f"{name}: нет переключения классов"
            # Запрет сброса значений форм и innerHTML контейнеров вкладок.
            assert ".value = ''" not in body, f"{name} сбрасывает поля!"
            assert ".innerHTML = ''" not in body, f"{name} сбрасывает DOM!"
            assert "remove()" not in body or name != "showBotTab"


def test_every_tab_panel_has_loader_and_is_grouped():
    """botTab-* ↔ _botTabLoaders ↔ группы: целостность механики вкладок."""
    js = _app_js()
    tpl = (ROOT / "templates" / "partials" / "bots.html").read_text()
    panels = set(re.findall(r'id="botTab-([a-z-]+)"', tpl))
    assert len(panels) >= 17, "панели вкладок карточки бота (после C1: role/behavior/patterns убраны)"
    m = re.search(r"(?:const _botTabLoaders = |function _botTabLoaders\(\) \{\s*return )\{(.*?)\};", js, re.S)
    assert m, "_botTabLoaders не найден"
    loaders = set(re.findall(r"^\s+'?([a-z-]+)'?:\s*load", m.group(1), re.M))
    assert panels <= loaders, f"вкладки без загрузчика: {panels - loaders}"
    # Каждая группа в showBotGroup ссылается только на существующие вкладки.
    groups = re.search(r"const BOT_TAB_GROUPS = \{(.*?)\n\};", js, re.S)
    assert groups, "BOT_TAB_GROUPS не найден"
    referenced = set(re.findall(r"'([a-z-]+)'", groups.group(1)))
    unknown = referenced - panels - {"overview"}
    assert not unknown, f"группы ссылаются на несуществующие вкладки: {unknown}"
