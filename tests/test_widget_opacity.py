"""Shared opacity URL control for active widget backdrops."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

BACKDROP_WIDGETS = {
    "animated-bg", "goals", "now-playing", "sub-goal", "schedule",
    "stream-session", "follower-ticker", "lower-third", "anime-runner",
    "chat-highlight", "chat-roulette", "song-request", "top-donator",
    "countdown", "donation-challenge", "clip-moments", "latest-event-card",
    "tts-bot", "tts-chat-overlay", "hype-meter", "subathon-timer",
    "emoji-leaderboard", "blur-guard-v2", "emoji-chat", "media-share",
    "mod-feed", "soundboard", "recent-events",
}

def test_shared_appearance_parser_is_numeric_clamped_and_injection_safe():
    source = (ROOT / "widgets/_shared/appearance.js").read_text(encoding="utf-8")
    assert "Number(rawOpacity)" in source
    assert "Number.isFinite(value)" in source
    assert "Math.max(0, Math.min(1, value))" in source
    assert "--widget-opacity-percent" in source
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source


def _run_appearance(query: str) -> dict[str, str]:
    source = (ROOT / "widgets/_shared/appearance.js").read_text(encoding="utf-8")
    harness = f"""
const values = {{}};
global.window = {{location: {{search: {json.dumps(query)}}}}};
global.document = {{documentElement: {{style: {{setProperty: (key, value) => values[key] = value}}}}}};
eval({json.dumps(source)});
process.stdout.write(JSON.stringify(values));
"""
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_shared_appearance_runtime_applies_clamps_and_rejects_code():
    assert _run_appearance("?opacity=.2") == {
        "--widget-opacity": "0.2",
        "--widget-opacity-percent": "20%",
    }
    assert _run_appearance("?opacity=-4")["--widget-opacity"] == "0"
    assert _run_appearance("?opacity=4")["--widget-opacity"] == "1"
    assert _run_appearance("?opacity=bad") == {}
    assert _run_appearance("?opacity=0.5%3Bbackground%3Ared") == {}


def test_all_widget_html_receives_shared_appearance_runtime():
    from app.widget_inventory import WIDGET_INVENTORY
    from app.widgets import _widget_html

    for item in WIDGET_INVENTORY:
        html = _widget_html(item.folder)
        assert '/widget/_shared/appearance.js' in html, item.slug


def test_migrated_backdrops_use_shared_opacity_variable():
    for folder in BACKDROP_WIDGETS:
        source = (ROOT / "widgets" / folder / "index.html").read_text(encoding="utf-8")
        assert "--widget-opacity" in source, folder

