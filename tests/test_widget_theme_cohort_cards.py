"""First common-theme cohort: compact cards retain defaults and opt into tokens."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COHORT = ("countdown", "donation-challenge", "latest-event-card", "top-donator")


def _source(folder: str) -> str:
    return (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")


def test_card_cohort_consumes_shared_semantic_tokens():
    for folder in COHORT:
        source = _source(folder)
        assert "widget-theme-surface" in source, folder
        for theme in ("dark", "light", "neon", "fire", "glass", "mono"):
            assert f"'{theme}'" in source, (folder, theme)


def test_card_cohort_preserves_existing_defaults_and_legacy_names():
    for folder in COHORT:
        source = _source(folder)
        assert "?'neon'" in source or ":'neon'" in source, folder
    assert "'minimal'" in _source("countdown")
    assert "'minimal'" in _source("donation-challenge")
    assert "'rainbow'" in _source("latest-event-card")
    assert "'minimal'" in _source("top-donator")


def test_theme_class_inputs_are_whitelisted_before_dom_use():
    for folder in COHORT:
        source = _source(folder)
        assert "new Set([" in source, folder
        assert ".has(requestedTheme)" in source, folder
