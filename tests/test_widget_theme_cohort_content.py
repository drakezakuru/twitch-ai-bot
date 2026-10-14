"""Shared URL themes coexist with persisted content-widget themes."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(folder: str) -> str:
    return (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")


def test_content_cohort_preserves_semantic_classes_during_updates():
    lower = _source("lower-third")
    assert 'lt widget-theme-surface' in lower
    assert "'dark','light','neon','fire','glass','mono','minimal','corporate'" in lower

    highlight = _source("chat-highlight")
    assert highlight.count("bubble widget-theme-surface theme-") == 2
    assert 'author widget-theme-accent' in highlight

    songs = _source("song-request")
    assert 'sr-now widget-theme-surface' in songs
    assert 'sr-queue-item widget-theme-surface' in songs
    assert "-webkit-text-fill-color:currentColor" in songs


def test_content_cohort_keeps_all_legacy_theme_rules():
    lower = _source("lower-third")
    assert "body.theme-neon" in lower and "body.theme-corporate" in lower
    highlight = _source("chat-highlight")
    for theme in ("glow", "neon", "minimal", "fire"):
        assert f".bubble.theme-{theme}" in highlight
    songs = _source("song-request")
    for theme in ("purple", "fire", "minimal"):
        assert f".theme-{theme} .sr-now" in songs
