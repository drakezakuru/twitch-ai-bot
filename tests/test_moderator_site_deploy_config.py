"""MOD-22 gate: fail-closed config, owner port never published, honest readiness."""
from __future__ import annotations

import pytest

from app import moderator_site_deploy_config as cfg


@pytest.fixture
def base():
    return {"public_origin": "https://mod.example.com", "allowed_hosts": ["mod.example.com"],
            "tls_cert": "/etc/ssl/mod.crt", "tls_key": "/etc/ssl/mod.key",
            "gateway_port": 8443, "bridge_port": 12701, "published_ports": [8443]}


def test_valid_config_passes(base):
    validated = cfg.validate_config(base)
    assert validated["valid"] is True and validated["published_ports"] == [8443]


def test_missing_keys_fail_closed(base):
    for key in ("public_origin", "tls_cert", "tls_key", "allowed_hosts"):
        broken = dict(base)
        broken.pop(key)
        with pytest.raises(ValueError, match="config_invalid"):
            cfg.validate_config(broken)


def test_http_origin_rejected(base):
    base["public_origin"] = "http://mod.example.com"
    with pytest.raises(ValueError, match="public_origin_must_be_https"):
        cfg.validate_config(base)


def test_owner_ports_never_published(base):
    base["published_ports"] = [8443, 12701]  # bridge port leaked
    with pytest.raises(ValueError, match="owner_port_published"):
        cfg.validate_config(base)
    base["published_ports"] = [8443]
    base["owner_panel_port"] = 8000
    base["published_ports"] = [8443, 8000]  # panel port leaked
    with pytest.raises(ValueError, match="owner_port_published"):
        cfg.validate_config(base)


def test_invite_link_uses_configured_origin_not_panel_location():
    link = cfg.invite_link("https://mod.example.com", "tok123")
    assert link == "https://mod.example.com/moderator-site/join?invite=tok123"
    assert "localhost" not in link and ":8000" not in link  # панельный origin не используется
    with pytest.raises(ValueError, match="invite_requires_https_origin"):
        cfg.invite_link("http://mod.example.com", "tok123")


def test_readiness_is_honest(base):
    assert cfg.health_readiness(base, bridge_healthy=True, gateway_listening=True)["ready"] is True
    not_ready = cfg.health_readiness(base, bridge_healthy=False, gateway_listening=True)
    assert not_ready["ready"] is False and not_ready["public_origin"] is None  # не выдаёт фейк-ok
