"""Shared theme palettes and injection-safe URL normalization."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import asyncio

from app.widget_inventory import WIDGET_INVENTORY
from app.widgets import _widget_html
from app.widgets import widget_shared_file


ROOT = Path(__file__).resolve().parents[1]
COMMON_THEMES = {"dark", "light", "neon", "fire", "glass", "mono"}


def _run_theme(query: str) -> dict[str, str]:
    source = (ROOT / "widgets/_shared/appearance.js").read_text(encoding="utf-8")
    harness = f"""
const values = {{}};
global.window = {{location: {{search: {json.dumps(query)}}}}};
global.document = {{documentElement: {{
  setAttribute: (key, value) => values[key] = value,
  style: {{setProperty: (key, value) => values[key] = value}}
}}}};
eval({json.dumps(source)});
process.stdout.write(JSON.stringify(values));
"""
    result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_common_theme_runtime_is_whitelist_only():
    for theme in COMMON_THEMES:
        assert _run_theme(f"?theme={theme}")["data-widget-theme"] == theme
    assert _run_theme("") == {}
    assert _run_theme("?theme=rainbow") == {}
    assert _run_theme("?theme=dark%22%20style%3D%22color%3Ared") == {}


def test_shared_stylesheet_defines_every_semantic_palette():
    css = (ROOT / "widgets/_shared/theme.css").read_text(encoding="utf-8")
    tokens = ("surface", "border", "text", "muted", "accent", "accent-2", "shadow")
    for theme in COMMON_THEMES:
        block = css.split(f'[data-widget-theme="{theme}"] {{', 1)[1].split("}", 1)[0]
        for token in tokens:
            assert f"--widget-theme-{token}:" in block


def test_every_widget_receives_shared_theme_contract():
    for item in WIDGET_INVENTORY:
        html = _widget_html(item.folder)
        assert '/widget/_shared/theme.css' in html, item.slug
        assert '/widget/_shared/appearance.js' in html, item.slug


def test_shared_asset_version_changes_invalidate_widget_html_cache():
    source = (ROOT / "app/widgets.py").read_text(encoding="utf-8")
    assert "theme_path.stat().st_mtime_ns" in source
    assert "appearance_path.stat().st_mtime_ns" in source
    assert 'theme.css?v={asset_version}' in source
    assert 'appearance.js?v={asset_version}' in source


def test_service_worker_fetches_shared_design_assets_network_first():
    source = (ROOT / "app/widgets.py").read_text(encoding="utf-8")
    shared_branch = source.index("url.pathname.startsWith('/widget/_shared/')")
    widget_branch = source.index("url.pathname.startsWith('/widget/')", shared_branch)
    assert shared_branch < widget_branch
    assert "networkFirstWithTimeout(event.request, CACHE_NAME" in source[shared_branch:widget_branch]
    assert "widget-cache-v2" in source


def test_shared_theme_asset_is_served_as_css():
    response = asyncio.run(widget_shared_file("theme.css"))
    assert response.media_type == "text/css"
