"""MOD-01 gate: the moderator gateway surface is default-deny against the owner app."""
from __future__ import annotations

import pytest

from app.moderator_site_contract import (
    FORBIDDEN_REMOTE_PREFIXES,
    REMOTE_ROUTE_ALLOWLIST,
    build_app_route_manifest,
    check_default_deny,
)


def _app():
    import os
    import tempfile
    os.environ.setdefault("TWITCH_BOT_DATA_DIR", tempfile.mkdtemp())
    from app.server import app
    return app


def test_app_manifest_is_substantial_and_default_deny_holds():
    app = _app()
    manifest = build_app_route_manifest(app)
    # The owner application is big; the inventory guard would be meaningless otherwise.
    assert len(manifest) > 400
    assert check_default_deny(app) == []


def test_allowlist_stays_within_moderator_site_prefix():
    for method, path in REMOTE_ROUTE_ALLOWLIST:
        assert path.startswith("/moderator-site")


def test_forbidden_surfaces_actually_exist_in_app():
    """The deny list must guard real surfaces, not phantoms."""
    app = _app()
    paths = {path for _method, path in build_app_route_manifest(app)}
    for prefix in FORBIDDEN_REMOTE_PREFIXES:
        assert any(path == prefix or path.startswith(prefix + "/") for path in paths), prefix


def test_no_owner_route_is_remotely_exposed():
    app = _app()
    owner_paths = {path for _method, path in build_app_route_manifest(app) if not path.startswith("/moderator-site")}
    for _method, path in REMOTE_ROUTE_ALLOWLIST:
        assert path not in owner_paths
