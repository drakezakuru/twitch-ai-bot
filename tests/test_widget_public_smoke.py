"""§11.7 WIDGETS_PLAN: smoke ВСЕХ публичных read-API виджетов + инварианты
standalone-работы (мутации без auth-сессии панели) + публичные роуты не требуют
Basic-auth."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio

# Публичные read-эндпоинты, которые читают OBS-виджеты (§11.7).
PUBLIC_READS = [
    "/api/widgets/public/goals",
    "/api/widgets/public/sub-goal",
    "/api/widgets/public/now-playing",
    "/api/widgets/public/schedule",
    "/api/widgets/public/recent-events",
    "/api/widgets/public/counter/death",
    "/api/widgets/public/stream-session",
    "/api/widgets/public/top-donator/alltime",
    "/api/widgets/public/top-donator/month",
    "/api/widgets/public/top-donator/day",
    "/api/widgets/public/subathon",
    "/api/widgets/public/emoji-leaderboard",
    "/api/widgets/public/blur-guard/state",
]

# Публичные мутации — работают при закрытой панели (OBS-хоткей/curl/биндинги).
PUBLIC_MUTATIONS = [
    ("/api/widgets/counters/death/increment", {"delta": 1}),
    ("/api/widgets/public/donation-webhook", {
        "event_id": "smoke-event", "username": "t", "amount": 1, "secret": "smoke-secret",
    }),
    ("/api/widgets/public/blur-guard/temp", {"seconds": 5}),
]

HTML_ROUTES = [
    "/widget/goals", "/widget/now-playing", "/widget/sub-goal", "/widget/schedule",
    "/widget/counter?key=death", "/widget/countdown", "/widget/song-request",
    "/widget/emoji-chat", "/widget/hype-meter", "/widget/subathon-timer",
    "/widget/poll-overlay", "/widget/emoji-leaderboard", "/widget/tts-bot",
    "/widget/tts-chat-overlay", "/widget/typing-indicator", "/widget/chat-reader",
    "/obs/blur-guard",
]


async def _client(tmp_db):
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    from app.blur_guard_routes import admin_router as bg_admin, public_router as bg_public
    await init_db()
    await ensure_widgets_schema()

    from fastapi import FastAPI
    app = FastAPI()
    for r in (admin_router, public_router, bg_admin, bg_public):
        app.include_router(r)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_all_public_reads_smoke(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        for url in PUBLIC_READS:
            r = await c.get(url)
            assert r.status_code == 200, f"{url} -> {r.status_code}"
            assert r.json() is not None


async def test_public_mutations_work_without_panel(tmp_db, disable_auth, monkeypatch):
    """§11.6: виджеты живут без открытой панели — мутации идут через API."""
    monkeypatch.setenv("DONATION_WEBHOOK_SECRET", "smoke-secret")
    async with await _client(tmp_db) as c:
        for url, payload in PUBLIC_MUTATIONS:
            r = await c.post(url, json=payload)
            assert r.status_code == 200, f"{url} -> {r.status_code}"
            assert r.json().get("ok") or r.json().get("id") or r.json().get("error") is None


async def test_widget_html_routes_serve(tmp_db):
    async with await _client(tmp_db) as c:
        for url in HTML_ROUTES:
            r = await c.get(url)
            assert r.status_code == 200, f"{url} -> {r.status_code}"
            assert "<html" in r.text.lower() or "<!DOCTYPE" in r.text[:60].upper()


async def test_admin_requires_auth_when_basic_auth_enabled(tmp_db, monkeypatch):
    """§11.7: при Basic-auth auth_dependency кидает 401; публичные роуты
    не имеют auth-зависимости (виджеты/OBS работают без сессии панели)."""
    monkeypatch.setenv("PANEL_AUTH_USER", "admin")
    monkeypatch.setenv("PANEL_AUTH_PASS", "secret")
    # QA-профиль из conftest глушит auth: для этого теста нужен реальный
    # network_basic-режим (не-loopback bind + шифрование + без QA_PROFILE).
    monkeypatch.delenv("QA_PROFILE", raising=False)
    monkeypatch.setenv("PANEL_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", 'ZFKTJT15yZCSMl66cLRp_D0AqkcaD8QoFHXYCoMwSH0=')
    from fastapi import Request
    from app import security as security_mod
    from app.security import auth_dependency, is_auth_enabled

    # _get_fernet кэширует первую попытку: сбрасываем под новые env
    monkeypatch.setattr(security_mod, "_FERNET", None)
    monkeypatch.setattr(security_mod, "_FERNET_TRIED", False)
    assert is_auth_enabled()

    # удалённый клиент (не loopback): парольless-доступ только локальной панели
    scope = {"type": "http", "method": "GET", "url": "http://test/api/widgets/goals",
             "headers": [], "query_string": b"", "client": ("203.0.113.7", 44456)}
    request = Request(scope)
    with pytest.raises(Exception) as exc:
        await auth_dependency(request)
    assert getattr(getattr(exc.value, "status_code", None), "__int__", None) and exc.value.status_code == 401

    # С заголовком Basic — пропускает
    import base64
    scope2 = {"type": "http", "method": "GET", "url": "http://test/api/widgets/goals",
              "headers": [(b"authorization", b"Basic " + base64.b64encode(b"admin:secret"))],
              "query_string": b"", "client": ("203.0.113.7", 44456)}
    await auth_dependency(Request(scope2))  # не бросает

    # Публичные роуты виджетов не имеют auth-зависимости
    from app.widgets import public_router
    for route in public_router.routes:
        deps = getattr(route, "dependencies", []) or []
        assert not deps, f"public route {route.path} has auth dependency"
