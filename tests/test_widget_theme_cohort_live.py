"""Shared themes cover live overlays without recoloring status semantics."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(folder: str) -> str:
    return (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")


def test_live_overlay_surfaces_use_shared_theme_tokens():
    expected = {
        "chat-roulette": ("winner-box widget-theme-surface", "name-label widget-theme-text"),
        "clip-moments": ("box widget-theme-surface", "rate widget-theme-accent"),
        "tts-bot": ('id="tts-container" class="widget-theme-surface"', "[data-widget-theme] #tts-container"),
        "tts-chat-overlay": ("tts-msg widget-theme-surface", "speaker widget-theme-accent"),
        "mod-feed": ("plate widget-theme-surface k-", "note widget-theme-surface"),
        "sub-goal": ("title widget-theme-accent", "bar widget-theme-fill"),
        "media-share": ("overlay-info widget-theme-surface", "idle widget-theme-muted"),
    }
    for folder, markers in expected.items():
        source = _source(folder)
        for marker in markers:
            assert marker in source, (folder, marker)


def test_special_visual_contracts_remain_intact():
    roulette = _source("chat-roulette")
    assert "repeating-conic-gradient" in roulette and ".pointer" in roulette
    mod_feed = _source("mod-feed")
    for kind in ("violation", "intent", "action", "lurker", "beep"):
        assert f".plate.k-{kind}" in mod_feed
    sub_goal = _source("sub-goal")
    assert "sceneEl.className='scene '+(d.theme||'tree')" in sub_goal
    assert "d.theme==='reef'" in sub_goal and "d.theme==='city'" in sub_goal
    media = _source("media-share")
    assert 'id="player"' in media and ".paused-badge" in media
