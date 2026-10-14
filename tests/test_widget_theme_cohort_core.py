"""Shared themes for established overlay widgets preserve legacy contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(folder: str) -> str:
    return (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")


def test_core_cohort_uses_semantic_theme_tokens():
    expected = {
        "goals": ("widget-theme-surface", "widget-theme-fill"),
        "now-playing": ("widget-theme-surface", "widget-theme-text"),
        "schedule": ("widget-theme-surface", "widget-theme-accent"),
        "follower-ticker": ("widget-theme-surface", "widget-theme-text"),
        "stream-session": ("widget-theme-surface", "widget-theme-muted"),
        "emoji-chat": ("msg widget-theme-surface", "widget-theme-text"),
    }
    for folder, markers in expected.items():
        source = _source(folder)
        for marker in markers:
            assert marker in source, (folder, marker)


def test_core_cohort_preserves_legacy_themes_and_routes():
    assert ".box.light" in _source("goals")
    assert ".np.light" in _source("now-playing")
    schedule = _source("schedule")
    assert ".wrap.arcade" in schedule and ".wrap.cyber" in schedule
    ticker = _source("follower-ticker")
    assert "body.theme-minimal" in ticker and "body.theme-rainbow" in ticker
    uptime = _source("stream-session")
    assert "body.theme-retro" in uptime and "body.theme-minimal" in uptime
    emoji = _source("emoji-chat")
    assert ".list.neon" in emoji and ".list.fire" in emoji and ".list.glass" in emoji
