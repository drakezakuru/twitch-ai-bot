"""Shared-theme cohort for compact metric cards preserves legacy defaults."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COHORT = ("emoji-leaderboard", "hype-meter", "subathon-timer")


def _source(folder: str) -> str:
    return (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")


def test_metric_cohort_opts_into_shared_semantic_tokens():
    for folder in COHORT:
        source = _source(folder)
        assert "widget-theme-surface" in source, folder
        assert "widget-theme-accent" in source, folder
        assert "widget-theme-muted" in source, folder
    assert "widget-theme-fill" in _source("hype-meter")
    assert "widget-theme-text" in _source("emoji-leaderboard")
    assert "widget-theme-text" in _source("subathon-timer")


def test_metric_cohort_preserves_default_styles_and_functional_parameters():
    emoji = _source("emoji-leaderboard")
    hype = _source("hype-meter")
    subathon = _source("subathon-timer")

    assert "rgba(15,15,25,var(--widget-opacity,0.85))" in emoji
    assert "qs.get('limit')" in emoji
    assert "rgba(15,15,25,var(--widget-opacity,0.8))" in hype
    assert "qs.get('window')" in hype
    assert "qs.get('threshold')" in hype
    assert "rgba(15,15,25,var(--widget-opacity,0.85))" in subathon
    assert "/api/widgets/public/subathon" in subathon


def test_shared_theme_exposes_text_utility_for_explicit_legacy_colors():
    css = (ROOT / "widgets" / "_shared" / "theme.css").read_text(encoding="utf-8")
    assert "[data-widget-theme] .widget-theme-text" in css
    assert "color: var(--widget-theme-text);" in css
