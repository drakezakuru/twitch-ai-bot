"""W7 canonical registry and 100% panel preview-contract coverage."""
from pathlib import Path
import re

from app.widget_bindings import ALLOWED_ACTIONS
from app.widget_inventory import (
    ALIAS_WIDGETS,
    LEGACY_PARAM_URLS,
    PROTECTED_WIDGET_OUTPUTS,
    RETIRED_WIDGETS,
    WIDGET_CATALOG_DETAILS,
    WIDGET_INVENTORY,
)

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "templates/partials/widgets.html").read_text(encoding="utf-8")


def _public_overlay_routes() -> set[str]:
    routes: set[str] = set()
    pattern = re.compile(r'@(public_router|ws_router)\.get\("(/(?:widget|obs)/[a-z0-9-]+)"')
    for path in (ROOT / "app").glob("*.py"):
        routes.update(match.group(2) for match in pattern.finditer(path.read_text(encoding="utf-8")))
    return routes - {"/widget/sw.js"}


def test_registry_is_the_canonical_public_overlay_inventory():
    routes = [item.route for item in WIDGET_INVENTORY]
    assert len(routes) == len(set(routes)), "duplicate public route in widget registry"
    # Protected, retired, alias и legacy-param URL сохраняют адрес без карточки.
    extra = (
        set(PROTECTED_WIDGET_OUTPUTS)
        | set(RETIRED_WIDGETS)
        | set(ALIAS_WIDGETS)
        | set(LEGACY_PARAM_URLS)
    )
    assert set(routes).isdisjoint(extra)
    assert set(routes) | extra == _public_overlay_routes()


def test_protected_outputs_are_explicit_and_not_reusable_panel_previews():
    assert PROTECTED_WIDGET_OUTPUTS == {
        "/widget/moderator-media": "exact account + channel + rotated OBS token",
    }
    assert set(PROTECTED_WIDGET_OUTPUTS).isdisjoint(
        item.route for item in WIDGET_INVENTORY
    )
    source = (ROOT / "app/moderator_media_routes.py").read_text(encoding="utf-8")
    assert "account_id: int, channel: str, token: str" in source
    assert "_valid_obs_token(account_id, channel, token)" in source


def test_merged_widget_legacy_urls_still_serve_their_period():
    """Wave 3 (Q15-17): три исторических top-donator URL живы и держат период."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.widgets import public_router
    app = FastAPI()
    app.include_router(public_router)
    client = TestClient(app)
    assert LEGACY_PARAM_URLS, "реестр исторических URL не должен быть пустым"
    for legacy, canonical in LEGACY_PARAM_URLS.items():
        old = client.get(legacy)
        new = client.get(canonical)
        assert old.status_code == 200, f"{legacy} сломан — OBS-сцена перестанет работать"
        assert old.text == new.text, f"{legacy} должен совпадать с {canonical}"
        period = canonical.split("period=", 1)[1]
        assert f'"{period}"' in old.text or f"'{period}'" in old.text or period in old.text


def test_alias_urls_serve_their_replacement_not_a_notice():
    """Q36: старый /obs/blur-guard отдаёт v2, чтобы сцена работала как раньше."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.widgets import public_router
    app = FastAPI()
    app.include_router(public_router)
    client = TestClient(app)
    assert ALIAS_WIDGETS, "реестр alias-URL не должен быть пустым"
    for old_route, new_route in ALIAS_WIDGETS.items():
        assert new_route in {item.route for item in WIDGET_INVENTORY}, \
            f"замена {new_route} должна быть живой карточкой"
        old = client.get(old_route)
        new = client.get(new_route)
        assert old.status_code == 200
        assert old.text == new.text, f"{old_route} должен отдавать {new_route}"


def test_retired_widgets_keep_their_public_url_with_dark_notice():
    """Owner survey: карточку убираем, но OBS Browser Source не должен ломаться."""
    from app.widgets import _retired_widget_html
    assert RETIRED_WIDGETS, "реестр retired-виджетов не должен быть пустым"
    for route, (title, reason, _replacement) in RETIRED_WIDGETS.items():
        assert route in _public_overlay_routes(), f"URL {route} исчез — OBS-сцена сломается"
        html = _retired_widget_html(route)
        assert "color-scheme: dark" in html.replace("color-scheme:dark", "color-scheme: dark")
        assert "#0f0f1a" in html, "заглушка должна быть тёмной, как остальные оверлеи"
        assert title in html and reason in html


def test_registry_covers_every_widget_folder_and_contract_is_complete():
    disk_folders = {
        path.parent.name for path in (ROOT / "widgets").glob("*/index.html")
        if path.parent.name != "_shared"
    }
    registered_folders = {item.folder for item in WIDGET_INVENTORY}
    assert registered_folders == disk_folders
    for item in WIDGET_INVENTORY:
        assert item.preview_url.startswith(item.route)
        assert item.preview_mode in {"live-dark", "representative-dark"}
        assert item.obs_width > 0 and item.obs_height > 0
        assert item.obs_layout in {"overlay", "strip", "fullscreen"}
        assert item.slug and item.title and item.description


def test_panel_renders_every_inventory_item_from_registry_with_preview():
    assert "{% for widget in widget_inventory %}" in PANEL
    assert "data-preview-contract=\"{{ widget.preview_mode }}\"" in PANEL
    assert "src=\"{{ widget.preview_url }}\"" in PANEL
    assert 'id="widgetInventorySearch"' in PANEL
    assert 'data-widget-search="{{ widget.title }} {{ widget.slug }}"' in PANEL
    assert 'data-obs-size="{{ widget.obs_width }}x{{ widget.obs_height }}"' in PANEL
    assert 'data-i18n="widgets.obs_size"' in PANEL
    assert "{% for title, description, path, slug in [" not in PANEL


def test_preview_iframes_have_non_white_dark_host_background():
    css = (ROOT / "static/app.css").read_text(encoding="utf-8")
    rule = css.split(".widget-preview {", 1)[1].split("}", 1)[0]
    assert "color-scheme: dark" in rule
    assert "background: var(--bg-secondary, #0f0f1a)" in rule
    for path in (ROOT / "widgets").glob("*/index.html"):
        assert "color-scheme" in path.read_text(encoding="utf-8"), path


def test_catalog_details_and_binding_ctas_cover_inventory():
    assert len(WIDGET_INVENTORY) == len(WIDGET_CATALOG_DETAILS) == 32
    assert {item.slug for item in WIDGET_INVENTORY} == set(WIDGET_CATALOG_DETAILS)
    for item in WIDGET_INVENTORY:
        assert item.verdict and item.example and item.catalog_note
        if item.binding_slug:
            assert item.binding_slug in ALLOWED_ACTIONS
    script = (ROOT / "static/app/13_widgets_session.js").read_text(encoding="utf-8")
    # Q27b: waWidgetBindingAdd(slug, prefillAction) открывает секцию правил в карточке
    assert "function waWidgetBindingAdd(slug, prefillAction)" in script
    assert 'id="waBindAction"' not in PANEL  # Q27c: общий билдер снесён, форма inline в карточках
    assert 'id="waBindingBuilder"' not in PANEL
    assert "onclick=\"waWidgetBindingAdd('{{ widget.binding_slug }}')\"" in PANEL


def test_representative_preview_data_for_event_overlays():
    tts = (ROOT / "widgets/tts-chat-overlay/index.html").read_text(encoding="utf-8")
    recent = (ROOT / "widgets/recent-events/index.html").read_text(encoding="utf-8")
    assert "DemoBot" in tts and "preview" in tts
    assert "DemoViewer" in recent and "preview" in recent
    assert "color-scheme" in tts and "#0f0f1a" in tts
    assert "color-scheme" in recent and "#0f0f1a" in recent


def test_representative_inventory_previews_request_demo_state():
    representative = [item for item in WIDGET_INVENTORY if item.preview_mode == "representative-dark"]
    assert representative
    for item in representative:
        assert "preview=1" in item.preview_url, item.slug
