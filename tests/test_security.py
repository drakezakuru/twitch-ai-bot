"""Тесты для app.security: шифрование, проверка Basic Auth."""
from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def test_no_encryption_when_key_unset(monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    from app import security
    # Reload to refresh module-level state
    import importlib
    importlib.reload(security)
    plain = "oauth:abc123def456"
    assert security.encrypt_token(plain) == plain
    assert security.decrypt_token(plain) == plain
    assert security.is_encryption_enabled() is False


def test_plaintext_storage_requires_loopback_runtime(monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("QA_PROFILE", raising=False)
    monkeypatch.setenv("PANEL_BIND_HOST", "0.0.0.0")
    from app import security
    import importlib
    importlib.reload(security)

    assert security.credential_storage_mode() == "blocked"
    with pytest.raises(security.CredentialStoragePolicyError):
        security.encrypt_token("oauth:must-not-be-stored")

    monkeypatch.setenv("PANEL_BIND_HOST", "127.0.0.1")
    assert security.credential_storage_mode() == "local_plaintext"
    assert security.encrypt_token("oauth:local-compatible") == "oauth:local-compatible"


def test_plaintext_warning_is_visible_and_localized():
    template = Path("templates/partials/settings.html").read_text(encoding="utf-8")
    renderer = Path("static/app/04_chat_settings.js").read_text(encoding="utf-8")
    i18n = Path("static/app.js").read_text(encoding="utf-8")

    assert 'id="plaintextSecurityWarning"' in template
    assert 'role="alert"' in template
    assert "classList.toggle('hidden', !st.plaintext_warning)" in renderer
    assert i18n.count("'security.plaintext_warning':") == 3
    assert i18n.count("'security.local_no_password':") == 3
    assert i18n.count("'security.network_auth':") == 3
    assert "st.local_passwordless ? 'security.local_no_password' : 'security.network_auth'" in renderer
    assert "Без переменных панель открыта всем" not in i18n


def test_encryption_roundtrip(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    from app import security
    import importlib
    importlib.reload(security)

    plain = "oauth:my_secret_token_xyz"
    enc = security.encrypt_token(plain)
    assert enc != plain
    assert enc.startswith("enc::")
    assert security.decrypt_token(enc) == plain
    assert security.is_encryption_enabled() is True


def test_decrypt_plain_passthrough(monkeypatch):
    """Если в БД лежит plain (legacy), decrypt_token не должен падать."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    from app import security
    import importlib
    importlib.reload(security)

    legacy = "oauth:legacy_plain_token"
    assert security.decrypt_token(legacy) == legacy


def test_auth_credentials_not_configured_when_unset(monkeypatch):
    monkeypatch.delenv("PANEL_AUTH_USER", raising=False)
    monkeypatch.delenv("PANEL_AUTH_PASS", raising=False)
    from app import security
    import importlib
    importlib.reload(security)
    assert security.is_auth_enabled() is False


def test_auth_enabled_with_creds(monkeypatch):
    monkeypatch.setenv("PANEL_AUTH_USER", "admin")
    monkeypatch.setenv("PANEL_AUTH_PASS", "s3cret")
    from app import security
    import importlib
    importlib.reload(security)
    assert security.is_auth_enabled() is True


def test_check_ws_auth_pass_in_network_mode(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PANEL_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("PANEL_AUTH_USER", "admin")
    monkeypatch.setenv("PANEL_AUTH_PASS", "s3cret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("QA_PROFILE", raising=False)
    from app import security
    import importlib
    importlib.reload(security)
    encoded = base64.b64encode(b"admin:s3cret").decode()
    assert security.panel_access_mode() == "network_basic"
    assert security.check_ws_auth({"authorization": f"Basic {encoded}"}, "203.0.113.8") is True
    assert security.check_ws_auth({"authorization": "Basic invalid"}, "203.0.113.8") is False
    assert security.check_ws_auth({}, "203.0.113.8") is False


def test_check_ws_auth_localhost_needs_no_password(monkeypatch):
    monkeypatch.setenv("PANEL_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("PANEL_AUTH_USER", "old-user")
    monkeypatch.setenv("PANEL_AUTH_PASS", "old-password")
    monkeypatch.delenv("QA_PROFILE", raising=False)
    monkeypatch.delenv("PANEL_ALLOW_INSECURE_LOCAL", raising=False)
    from app import security
    import importlib
    importlib.reload(security)
    assert security.panel_access_mode() == "local_no_auth"
    assert security.check_ws_auth({}, "127.0.0.1") is True
    assert security.check_ws_auth({}, "::1") is True
    assert security.check_ws_auth({}, "203.0.113.8") is False


def test_network_mode_without_complete_protection_is_blocked(monkeypatch):
    monkeypatch.setenv("PANEL_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("PANEL_AUTH_USER", "partial")
    monkeypatch.delenv("PANEL_AUTH_PASS", raising=False)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("QA_PROFILE", raising=False)
    monkeypatch.setenv("PANEL_ALLOW_INSECURE_LOCAL", "1")
    from app import security
    import importlib
    importlib.reload(security)
    assert security.panel_access_mode() == "blocked"
    assert security.check_ws_auth({}, "127.0.0.1") is False
    assert security.check_ws_auth({}, "203.0.113.8") is False


@pytest.mark.asyncio
async def test_http_localhost_needs_no_password(monkeypatch):
    monkeypatch.setenv("PANEL_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("PANEL_AUTH_USER", "old-user")
    monkeypatch.setenv("PANEL_AUTH_PASS", "old-password")
    monkeypatch.delenv("QA_PROFILE", raising=False)
    monkeypatch.delenv("PANEL_ALLOW_INSECURE_LOCAL", raising=False)
    from app import security
    import importlib
    importlib.reload(security)
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    await security.auth_dependency(request)


@pytest.mark.asyncio
async def test_http_local_mode_rejects_remote_without_basic_challenge(monkeypatch):
    monkeypatch.setenv("PANEL_BIND_HOST", "127.0.0.1")
    monkeypatch.delenv("PANEL_AUTH_USER", raising=False)
    monkeypatch.delenv("PANEL_AUTH_PASS", raising=False)
    monkeypatch.delenv("QA_PROFILE", raising=False)
    from app import security
    import importlib
    importlib.reload(security)
    local = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    remote = Request({"type": "http", "headers": [], "client": ("203.0.113.8", 1234)})
    await security.auth_dependency(local)
    with pytest.raises(HTTPException) as exc:
        await security.auth_dependency(remote)
    assert exc.value.status_code == 403
    assert not exc.value.headers


@pytest.mark.asyncio
async def test_http_network_mode_requires_valid_basic_auth(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PANEL_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("PANEL_AUTH_USER", "admin")
    monkeypatch.setenv("PANEL_AUTH_PASS", "s3cret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("QA_PROFILE", raising=False)
    from app import security
    import importlib
    importlib.reload(security)

    missing = Request({"type": "http", "headers": [], "client": ("203.0.113.8", 1234)})
    with pytest.raises(HTTPException) as exc:
        await security.auth_dependency(missing)
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": 'Basic realm="Twitch AI Bot Panel"'}

    encoded = base64.b64encode(b"admin:s3cret")
    valid = Request({
        "type": "http",
        "headers": [(b"authorization", b"Basic " + encoded)],
        "client": ("203.0.113.8", 1234),
    })
    await security.auth_dependency(valid)


def test_owner_control_routers_share_the_panel_access_policy():
    from app import (
        brain_routes,
        dm_chat,
        log_routes,
        moderation_routes,
        role_routes,
        stream_tools_routes,
    )

    routers = {
        "brain": brain_routes.router,
        "dm": dm_chat.router,
        "logs": log_routes.router,
        "moderation": moderation_routes.router,
        "roles": role_routes.router,
        "stream-tools": stream_tools_routes.router,
    }
    for name, router in routers.items():
        assert router.routes, name
        for route in router.routes:
            dependencies = {
                (item.call.__module__, item.call.__name__)
                for item in route.dependant.dependencies
            }
            assert ("app.security", "auth_dependency") in dependencies, (
                f"{name}: {route.path} has no panel access policy"
            )


def test_docker_healthcheck_uses_public_data_free_endpoint():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "/healthz" in dockerfile and "/healthz" in compose
    assert "127.0.0.1:8000/api/version" not in dockerfile + compose


@pytest.mark.asyncio
async def test_healthz_is_data_free():
    from app.server import healthz

    assert await healthz() == {"ok": True}


@pytest.mark.asyncio
async def test_fastapi_owner_route_is_passwordless_only_for_loopback(monkeypatch):
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient
    from app import security

    monkeypatch.setenv("PANEL_BIND_HOST", "127.0.0.1")
    monkeypatch.delenv("QA_PROFILE", raising=False)
    app = FastAPI()

    @app.get("/owner", dependencies=[Depends(security.auth_dependency)])
    async def owner() -> dict[str, bool]:
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 1234)),
        base_url="http://localhost",
    ) as local:
        response = await local.get("/owner")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert "www-authenticate" not in response.headers

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.8", 1234)),
        base_url="http://panel.test",
    ) as remote:
        response = await remote.get("/owner")
        assert response.status_code == 403
        assert "www-authenticate" not in response.headers
