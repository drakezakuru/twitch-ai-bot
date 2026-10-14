"""Shared safe scale/position controls for bounded OBS overlays."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from app.widget_inventory import WIDGET_INVENTORY
from app.widgets import _WIDGET_BOUNDED_ROOTS, _widget_html


ROOT = Path(__file__).resolve().parents[1]
NATIVE_LAYOUT_WIDGETS = {"chat-reader", "tts-raw"}
NON_BOUNDED_WIDGETS = {
    "animated-bg", "anime-runner", "blur-guard-v2", "follower-ticker", "media-share",
}


def _run_appearance(query: str, *, bounded: bool = True) -> dict[str, object]:
    source = (ROOT / "widgets/_shared/appearance.js").read_text(encoding="utf-8")
    harness = f"""
const values = {{}};
const attrs = {json.dumps({'data-widget-layout': 'bounded', 'data-widget-root': '#root'} if bounded else {})};
const classes = [];
const element = {{
  style: {{setProperty: (key, value) => values[key] = value}},
  classList: {{add: (name) => classes.push(name)}},
  getBoundingClientRect: () => ({{width: 320}}),
}};
global.window = {{location: {{search: {json.dumps(query)}}}}};
global.document = {{
  readyState: 'complete',
  documentElement: {{
    style: {{setProperty: (key, value) => values[key] = value}},
    getAttribute: (key) => attrs[key] || null,
    setAttribute: (key, value) => attrs[key] = value,
  }},
  querySelectorAll: () => [element],
}};
eval({json.dumps(source)});
process.stdout.write(JSON.stringify({{values, attrs, classes}}));
"""
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_shared_scale_is_numeric_clamped_and_position_is_whitelisted():
    low = _run_appearance("?scale=-2&pos=tc")
    assert low["values"]["--widget-scale"] == "0.5"
    assert low["attrs"]["data-widget-pos"] == "tc"
    assert "widget-appearance-root" in low["classes"]

    high = _run_appearance("?scale=9&pos=br")
    assert high["values"]["--widget-scale"] == "3"
    assert high["attrs"]["data-widget-pos"] == "br"

    bad = _run_appearance("?scale=1%3Bcolor%3Ared&pos=tl%22%20onclick%3Dalert(1)")
    assert "--widget-scale" not in bad["values"]
    assert "data-widget-pos" not in bad["attrs"]


def test_layout_controls_do_not_activate_for_fullscreen_or_strip_contracts():
    result = _run_appearance("?scale=2&pos=tr", bounded=False)
    assert "--widget-scale" not in result["values"]
    assert "data-widget-pos" not in result["attrs"]
    assert result["classes"] == []


def test_all_and_only_bounded_overlays_receive_layout_metadata():
    active_folders = {item.folder for item in WIDGET_INVENTORY}
    expected = active_folders - NATIVE_LAYOUT_WIDGETS - NON_BOUNDED_WIDGETS
    assert set(_WIDGET_BOUNDED_ROOTS) == expected

    for folder in expected:
        html = _widget_html(folder)
        assert 'data-widget-layout="bounded"' in html, folder
        assert 'data-widget-root="' in html, folder

    for folder in NATIVE_LAYOUT_WIDGETS | NON_BOUNDED_WIDGETS:
        assert 'data-widget-layout="bounded"' not in _widget_html(folder), folder


def test_native_and_special_coordinate_contracts_remain_intact():
    chat = (ROOT / "widgets/chat-reader/index.html").read_text(encoding="utf-8")
    tts = (ROOT / "widgets/tts-raw/index.html").read_text(encoding="utf-8")
    runner = (ROOT / "widgets/anime-runner/index.html").read_text(encoding="utf-8")
    assert "__DESIGN_SCALE__" in chat and "__DESIGN_POS__" in chat
    assert "__DESIGN_SCALE__" in tts and "__DESIGN_POS__" in tts
    assert "corner" in runner and "path-mode" in runner and "lane.className" in runner


def test_legacy_unbounded_scale_contracts_are_not_replaced():
    media = (ROOT / "widgets/media-share/index.html").read_text(encoding="utf-8")
    blur = (ROOT / "widgets/blur-guard-v2/index.html").read_text(encoding="utf-8")
    assert "qs.get('scale')" in media
    assert 'qs.get("scale")' in blur
