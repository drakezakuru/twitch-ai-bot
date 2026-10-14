"""§13 WIDGETS_PLAN: Blur Guard — настройки, вердикт-парсер, фидбек+правила,
ручные бинды, оверлей-роут."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


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


async def test_verdict_parser():
    from app.blur_guard import _parse_verdict
    v = _parse_verdict('{"nsfw": true, "categories": ["нагота"], "confidence": 0.9}')
    assert v == {"nsfw": True, "categories": ["нагота"], "confidence": 0.9}
    # JSON внутри текста
    v = _parse_verdict('Ответ: {"nsfw": false, "categories": [], "confidence": 0.1} ок')
    assert v["nsfw"] is False
    # фолбэк
    assert _parse_verdict("yes, definitely")["nsfw"] is True
    assert _parse_verdict("nothing wrong here")["nsfw"] is False
    assert _parse_verdict("") is None


async def test_settings_roundtrip(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        s = (await c.get("/api/blur-guard")).json()
        assert s["enabled"] in (0, False)
        s2 = (await c.put("/api/blur-guard", json={
            "enabled": True, "sensitivity": 85, "interval_sec": 5,
            "pre_delay_ms": 300, "blur_duration_sec": 20,
            "blur_percent": 1,
            "custom_prompt": "Проверь спойлеры",
            "categories": ["спойлеры"],
        })).json()
        assert s2["enabled"] in (1, True) and s2["sensitivity"] == 85
        assert s2["custom_categories"] == ["спойлеры"]
        # §13.3: интенсивность блюра 1-100%
        assert s2["blur_percent"] == 1
        s2b = (await c.put("/api/blur-guard", json={"blur_percent": 250})).json()
        assert s2b["blur_percent"] == 100  # clamp
        # clamp
        s3 = (await c.put("/api/blur-guard", json={"sensitivity": 999, "interval_sec": 0})).json()
        assert s3["sensitivity"] == 100 and s3["interval_sec"] == 3


async def test_manual_binds_and_state(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        st = (await c.get("/api/widgets/public/blur-guard/state")).json()
        assert st["blur"] is False
        assert st["cover_percent"] == st["blur_percent"] == 100
        assert {"mode", "region", "always_zones", "blur_mode"} <= st.keys()
        assert (await c.post("/api/widgets/public/blur-guard/on")).json()["blur"] is True
        st = (await c.get("/api/widgets/public/blur-guard/state")).json()
        assert st["blur"] is True
        assert (await c.post("/api/widgets/public/blur-guard/off")).json()["ok"]
        st = (await c.get("/api/widgets/public/blur-guard/state")).json()
        assert st["blur"] is False
        r = (await c.post("/api/widgets/public/blur-guard/temp", json={"seconds": 7})).json()
        assert r["seconds"] == 7
        st = (await c.get("/api/widgets/public/blur-guard/state")).json()
        assert st["blur"] is True  # временный блюр активен


async def test_feedback_and_local_rules(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        # 3+ фидбека «AI зря блюрил» по категории → порог +10%
        for _ in range(4):
            await c.post("/api/widgets/public/blur-guard/feedback", json={
                "ai_decision": True, "user_decision": False,
                "category": "оружие", "confidence": 0.8, "model": "ollama-vision"})
        fb = (await c.get("/api/blur-guard/feedback")).json()
        assert len(fb) >= 4 and fb[0]["category"] == "оружие"
        from app.blur_guard import _rule_threshold_delta
        assert await _rule_threshold_delta(["оружие"]) == 10  # одноразовая поправка на 3-м фидбеке
        # обратные фидбеки «юзер хотел блюр» — отдельная колонка правила
        for _ in range(3):
            await c.post("/api/widgets/public/blur-guard/feedback", json={
                "ai_decision": False, "user_decision": True, "category": "нагота"})
        assert await _rule_threshold_delta(["нагота"]) == -10


async def test_blur_guard_widget_route_and_loop_state():
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.widgets import public_router
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Q36: старый /obs/blur-guard — alias на v2, отдаёт ровно тот же оверлей.
        r = await c.get("/obs/blur-guard")
        assert r.status_code == 200
        assert "blur_guard" in r.text and "feedback" in r.text
        assert "deactivateBlur" in r.text and "applyConfig" in r.text
        v2 = await c.get("/obs/blur-guard-v2")
        assert r.text == v2.text, "alias должен отдавать актуальный blur-guard-v2"


async def test_trigger_blur_broadcasts(tmp_db, disable_auth, monkeypatch):
    async with await _client(tmp_db):
        from app import blur_guard as bg
        events = []
        async def fake_broadcast(kind, extra=None):
            events.append((kind, extra))
        monkeypatch.setattr(bg, "_broadcast", fake_broadcast)
        await bg.trigger_blur(5, source="test")
        assert events and events[0][0] == "blur_on"
        assert events[0][1]["cover_percent"] == 100
        assert events[0][1]["persistent"] is False
        assert {"mode", "region", "always_zones", "blur_mode"} <= events[0][1].keys()
        assert bg.is_blur_active()
        bg.manual_off(seconds=30)
        assert not bg.is_blur_active()
        # manual_on держит блюр даже после trigger
        bg.manual_on()
        await bg.trigger_blur(5, source="test")
        assert bg.is_blur_active()
        bg.manual_off()


async def test_runtime_config_broadcast_is_complete(tmp_db, disable_auth, monkeypatch):
    async with await _client(tmp_db) as c:
        from app import blur_guard as bg
        events = []

        async def fake_broadcast(kind, extra=None):
            events.append((kind, extra))

        monkeypatch.setattr(bg, "_broadcast", fake_broadcast)
        await c.put("/api/blur-guard", json={
            "blur_percent": 73,
            "blur_mode": "combo",
            "region": "10,20,300,200",
            "always_zones": "5%,5%,10%,10%",
            "consecutive_clean_frames": 7,
        })
        kind, config = events[-1]
        assert kind == "blur_config"
        assert config == {
            "mode": "ai",
            "blur_percent": 73,
            "cover_percent": 73,
            "blur_mode": "combo",
            "region": "10,20,300,200",
            "always_zones": "5%,5%,10%,10%",
            "consecutive_clean_frames": 7,
            "persistent": False,
            "protection_mode": "mask",
            "cover_image_url": "/api/widgets/public/blur-guard/image",
            "obs_source_name": "",
            "obs_filter_name": "",
        }


async def test_broadcast_uses_live_panel_websocket(monkeypatch):
    from app import blur_guard as bg
    from app import routes
    events = []

    async def fake_broadcast(payload):
        events.append(payload)

    monkeypatch.setattr(routes, "broadcast_log", fake_broadcast)
    await bg._broadcast("blur_on", {"cover_percent": 100})
    assert events[0]["type"] == "blur_guard"
    assert events[0]["kind"] == "blur_on"
    assert events[0]["cover_percent"] == 100


async def test_overlay_uses_opaque_privacy_mask_and_reconnect_sync():
    html = (Path(__file__).parents[1] / "widgets/blur-guard-v2/index.html").read_text(
        encoding="utf-8"
    )
    assert "background: rgb(15, 15, 25)" in html
    assert "state.coverPercent / 100" in html
    assert "syncRuntimeState();" in html
    assert "/api/widgets/public/blur-guard/state" in html
    assert '&& !qs.has("blur")' in html
    assert "&& !CFG.zones" in html
    assert 'state.protectionMode === "image"' in html
    assert 'state.protectionMode === "obs_filter"' in html


async def test_custom_cover_image_upload_and_public_delivery(
    tmp_db, disable_auth, tmp_path, monkeypatch
):
    import io
    from PIL import Image
    from app import runtime_paths

    monkeypatch.setattr(runtime_paths, "BLUR_GUARD_DIR", tmp_path / "blur-guard")
    image = Image.new("RGB", (32, 18), "purple")
    payload = io.BytesIO()
    image.save(payload, "PNG")

    async with await _client(tmp_db) as c:
        saved = await c.post(
            "/api/blur-guard/image",
            files={"file": ("cover.png", payload.getvalue(), "image/png")},
        )
        assert saved.status_code == 200
        delivered = await c.get("/api/widgets/public/blur-guard/image")
        assert delivered.status_code == 200
        assert delivered.headers["content-type"] == "image/webp"
        assert delivered.content.startswith(b"RIFF")

        settings = (await c.put("/api/blur-guard", json={
            "protection_mode": "image",
            "obs_source_name": "Gameplay",
            "obs_filter_name": "Privacy Blur",
        })).json()
        assert settings["protection_mode"] == "image"
        state = (await c.get("/api/widgets/public/blur-guard/state")).json()
        assert state["protection_mode"] == "image"
        assert state["cover_image_url"].endswith("/blur-guard/image")

        broken = await c.post(
            "/api/blur-guard/image",
            files={"file": ("broken.png", b"not an image", "image/png")},
        )
        assert broken.status_code == 400


async def test_obs_websocket_toggles_existing_filter(monkeypatch):
    from app import obs_blur

    class FakeSocket:
        def __init__(self):
            self.replies = iter((
                '{"op":0,"d":{"rpcVersion":1}}',
                '{"op":2,"d":{"negotiatedRpcVersion":1}}',
                '{"op":7,"d":{"requestStatus":{"result":true,"code":100}}}',
            ))
            self.sent = []

        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def recv(self): return next(self.replies)
        async def send(self, message): self.sent.append(message)

    socket = FakeSocket()
    monkeypatch.setattr(obs_blur.websockets, "connect", lambda *a, **k: socket)
    await obs_blur.set_filter_enabled("Gameplay", "Privacy Blur", True)

    import json
    request = json.loads(socket.sent[-1])
    assert request["d"]["requestType"] == "SetSourceFilterEnabled"
    assert request["d"]["requestData"] == {
        "sourceName": "Gameplay",
        "filterName": "Privacy Blur",
        "filterEnabled": True,
    }
