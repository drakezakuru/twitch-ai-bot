"""Static theme/layout contracts; computed-style/browser acceptance stays separate."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static/app.css").read_text(encoding="utf-8")
BASE = (ROOT / "templates/base.html").read_text(encoding="utf-8")


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


TAGS = Tags(BASE).tags


def declarations(selector):
    """Read declarations for exact selectors, including later responsive overrides."""
    result = {}
    source = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", source):
        if selector in [part.strip() for part in selectors.split(",")]:
            for declaration in body.split(";"):
                if ":" in declaration:
                    name, value = declaration.split(":", 1)
                    result[name.strip()] = value.strip()
    return result


def test_panel_is_dark_before_styles_or_application_scripts():
    html = next(attrs for tag, attrs in TAGS if tag == "html")
    assert html["data-theme"] == html["data-panel-theme"] == "dark"
    assert any(tag == "meta" and attrs.get("name") == "color-scheme"
               and attrs.get("content") == "dark" for tag, attrs in TAGS)
    assert BASE.index('id="panelThemeBoot"') < BASE.index('rel="stylesheet"')
    assert declarations(':root[data-panel-theme="dark"]')["color-scheme"] == "dark"


def test_legacy_light_rules_cannot_select_panel_or_widget_controls():
    # Light compatibility remains available outside the canonical panel root.
    selectors = re.findall(r"([^{}]+)\{", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
    light = [part.strip() for group in selectors for part in group.split(",")
             if '[data-theme="light"]' in part]
    assert light
    assert all(part.startswith(':root:not([data-panel-theme="dark"])[data-theme="light"]')
               for part in light)
    assert declarations(":root")["--bg"] == "#0e0e10"
    assert declarations(":root")["--text"] == "#efeff1"
    assert 'onclick="toggleTheme()"' not in BASE
    assert any(attrs.get("class") == "theme-indicator" for _, attrs in TAGS)


def test_ordinary_content_is_centered_and_bounded():
    content = declarations(".app-content")
    assert 1400 <= int(content["max-width"].removesuffix("px")) <= 1600
    assert content["width"] == "100%"
    assert content["margin-inline"] == "auto"
    assert content["min-width"] == "0"


@pytest.mark.parametrize("selector", [".table-wrap", ".bot-files-editor", ".panel-overflow-surface"])
def test_wide_content_has_local_overflow_instead_of_clipping(selector):
    rules = declarations(selector)
    assert rules["min-width"] == "0"
    assert rules["max-width"] == "100%"
    assert rules["overflow-x"] == "auto"
    assert rules["overscroll-behavior-x"] == "contain"
    assert declarations(".bot-files-textarea")["overflow"] == "auto"


def test_mobile_shell_shrinks_and_legacy_content_stays_reachable():
    for selector in (".app-main", ".search-bar", ".search-bar input", ".grid > *", ".flex > *"):
        assert declarations(selector)["min-width"] == "0"
    assert declarations(".app-content > .section")["overflow-x"] == "auto"
    assert declarations(".app-content > .section")["max-width"] == "100%"
    assert declarations(".app-topbar")["flex-wrap"] == "wrap"
    assert declarations(".search-bar")["flex"] == "1 1 100%"
    assert declarations("#toastContainer")["max-width"] == "calc(100% - 40px)"
    assert declarations(".modal")["max-width"] == "calc(100vw - 24px)"
    assert declarations(".modal-actions")["flex-wrap"] == "wrap"
    for selector in ("html", "body", ".app-main", ".app-content"):
        assert declarations(selector).get("overflow-x") not in ("hidden", "clip")


def test_focus_outline_covers_native_and_custom_keyboard_targets():
    selector = ':root[data-panel-theme="dark"] :is(button, a[href], input, select, textarea, summary, [tabindex], [role="button"]):focus-visible'
    assert selector in CSS
    body = CSS.split(selector, 1)[1].split("}", 1)[0]
    assert "outline: 2px solid var(--text)" in body
    assert "outline-offset: 2px" in body
    assert "@media (prefers-reduced-motion: reduce)" in CSS


def test_shell_controls_and_dialogs_have_accessible_names():
    by_id = {attrs["id"]: attrs for _, attrs in TAGS if "id" in attrs}
    for class_name in ("sidebar-collapse", "menu-burger"):
        attrs = next(attrs for _, attrs in TAGS if attrs.get("class") == class_name)
        assert attrs["aria-label"]
        assert attrs["data-i18n-aria-label"] == attrs["data-i18n-title"]
        assert attrs["aria-controls"] in by_id
    nav_buttons = [attrs for _, attrs in TAGS if "data-section" in attrs]
    # Q40: страница Режиссёра вернулась в меню — 9 nav-кнопок, включая director.
    assert len(nav_buttons) == 9
    assert "director" in {attrs["data-section"] for attrs in nav_buttons}
    for attrs in nav_buttons:
        assert attrs["aria-label"]
        assert attrs["data-i18n-aria-label"] == "nav." + attrs["data-section"]
    assert by_id["globalSearch"]["data-i18n-aria-label"] == "search.placeholder"
    dialogs = [attrs for _, attrs in TAGS if "modal" in attrs.get("class", "").split()]
    # c57a0cd (DEC-OWNER-016): модалка-предупреждение Media Share удалена из
    # base.html — остаются onboarding-card и observation-modal.
    assert len(dialogs) == 2
    for attrs in dialogs:
        assert attrs["role"] == "dialog"
        assert attrs["aria-modal"] == "true"
        assert attrs["tabindex"] == "-1"
        assert by_id[attrs["aria-labelledby"]]["data-i18n"]
        for reference in attrs.get("aria-describedby", "").split():
            assert reference in by_id
    for name in ("toastContainer", "observationContent", "onboardingError"):
        assert by_id[name]["aria-live"] in ("polite", "assertive")


def test_early_theme_boot_behavior_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    result = subprocess.run(
        [node, "--test", str(ROOT / "tests/panel_theme_layout.test.js")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
