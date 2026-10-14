"""Shared themes for stream status widgets preserve their data contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(folder: str) -> str:
    return (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")


def test_stream_cohort_opts_into_shared_theme_tokens():
    recent = _source("recent-events")
    soundboard = _source("soundboard")

    assert 'event widget-theme-surface' in recent
    assert 'kind widget-theme-accent' in recent
    assert 'id="state" class="widget-theme-surface"' in soundboard


def test_stream_cohort_preserves_default_styles_and_behavior():
    recent = _source("recent-events")
    soundboard = _source("soundboard")

    assert "#1e293b var(--widget-opacity-percent,100%)" in recent
    assert "/api/widgets/public/recent-events?" in recent
    assert "['account_id','channel']" in recent
    assert "'limit=5&t='" in recent
    assert "setInterval(load,5000)" in recent
    assert "rgba(15,15,26,var(--widget-opacity,.8))" in soundboard
    assert "state.className='widget-theme-surface '+cls" in soundboard
    assert "d.type!=='soundboard'||d.kind!=='play'" in soundboard
    assert "retry=Math.min(retry*2,10000)" in soundboard
    assert "new URL(`/api/widgets/public/soundboard/tracks/${d.track_id}`,base)" in soundboard
