"""UI-01 focused gates. Browser/OBS acceptance remains separate and opt-in."""
from pathlib import Path
import re
import subprocess

from tests.test_panel_labels import dictionaries

ROOT = Path(__file__).resolve().parents[1]


def test_panel_keyboard_and_localization_runtime():
    subprocess.run(["node", "--test", "tests/panel_accessibility.test.js", "tests/panel_dynamic_i18n.test.js"],
                   cwd=ROOT, check=True, timeout=30)


def test_literal_panel_translation_keys_are_available_in_three_languages(dictionaries):
    labels = dictionaries["all"]
    for path in [ROOT / "static/app.js", *sorted((ROOT / "static/app").glob("*.js"))]:
        for key in re.findall(r"\bt\(['\"]([^'\"]+)['\"]", path.read_text(encoding="utf-8")):
            if key.endswith((".", "_")):
                continue  # Dynamic prefixes/suffixes have separate feature contracts.
            for language in ("ru", "en", "ua"):
                assert labels[language].get(key), (path.name, key, language)


def test_panel_dialog_entrypoints_use_shared_lifecycle():
    helpers = (ROOT / "static/app/05_bots_tabs.js").read_text(encoding="utf-8")
    assert "openPanelDialog(name" in helpers and "closePanelDialog(name)" in helpers
    for name in ("03_bots.js", "07_widgets.js"):
        source = (ROOT / "static/app" / name).read_text(encoding="utf-8")
        assert not re.search(r"\$\('[^']*(?:Modal|Overlay)'\)\??\.classList\.(?:add|remove)\('hidden'\)", source)
    instructions = (ROOT / "static/app/09_brain_p3.js").read_text(encoding="utf-8")
    assert "openPanelDialog(overlay, {removeOnClose: true})" in instructions
    assert 'aria-labelledby="widgetInstrTitle"' in instructions
    assert 'aria-describedby="widgetInstrSteps"' in instructions
    boot = (ROOT / "static/app/04_chat_settings.js").read_text(encoding="utf-8")
    # The Q20 chat channel picker is a popover, not a dialog: its own Escape
    # close is allowed, but it must stay the only ad-hoc Escape handler here.
    assert re.findall(r"e\.key === 'Escape'\) (\w+)\(", boot) == ["closeChatChannelPanel"]
    assert "enforcePanelDarkTheme();" in boot
    assert "getItem('theme')" not in boot


def test_catalog_and_design_labels_cover_the_canonical_inventory(dictionaries):
    from app.widget_inventory import WIDGET_INVENTORY
    from jinja2 import Environment, FileSystemLoader
    from tests.test_panel_labels import Template
    html = Environment(loader=FileSystemLoader(ROOT / 'templates')).get_template('partials/widgets.html').render(widget_inventory=WIDGET_INVENTORY)
    parsed = Template(html)
    for item in WIDGET_INVENTORY:
        for field in ('title', 'description'):
            key = f'ui.catalog.{field}.{item.slug}'
            assert any(el.attrs.get('data-i18n') == key for el in parsed.elements)
            for lang in ('ru', 'en', 'ua'):
                assert dictionaries['all'][lang].get(key), (lang, key)
        for lang in ('ru', 'en', 'ua'):
            assert dictionaries['all'][lang].get(f'ui.catalog.verdict.{item.verdict}')
    for element in parsed.elements:
        if element.attrs.get('data-design-field') in ('theme', 'font', 'pos'):
            for option in element.children:
                key = option.attrs['data-i18n']
                assert option.attrs['value']
                for lang in ('ru', 'en', 'ua'):
                    assert dictionaries['all'][lang].get(key), (lang, key)
