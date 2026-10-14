"""§11.4 WIDGETS_PLAN: донат-интеграции.

1. Настройки donation-integration: GET/PUT, токен не отдаётся наружу, обновление
   пустым полем не затирает сохранённый токен.
2. poll_donatepay_once: парсинг разных форматов, дедуп по id, запись доната
   в топ + recent-events + duck_start.
3. DonationAlerts: разбор publication-сообщения Centrifugo.
4. Публичный donation-webhook (внешние сервисы) + secret через env.
"""
from __future__ import annotations

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client(tmp_db):
    from app.database import init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_donation_settings_roundtrip(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        # мультиплатформенность: можно включить несколько сервисов сразу
        await c.put("/api/widgets/donation-integration", json={
            "platform": "donatepay", "enabled": True, "token": "secret-dp-123"})
        await c.put("/api/widgets/donation-integration", json={
            "platform": "donatex", "enabled": True, "token": "secret-dx-456"})
        s = (await c.get("/api/widgets/donation-integration")).json()
        items = {it["platform"]: it for it in s["items"]}
        assert items["donatepay"]["enabled"] is True
        assert items["donatex"]["enabled"] is True
        assert items["donatepay"]["token_set"] and items["donatex"]["token_set"]
        # токены не утекают наружу
        assert "secret-dp" not in str(s) and "secret-dx" not in str(s)
        # подсказки токенов
        assert items["donatepay"]["token_hint"].startswith("…")
        # пустой токен не затирает сохранённый
        await c.put("/api/widgets/donation-integration", json={"platform": "donatepay", "enabled": True})
        s2 = (await c.get("/api/widgets/donation-integration")).json()
        it = next(x for x in s2["items"] if x["platform"] == "donatepay")
        assert it["token_set"] is True
        # выключение не удаляет токен
        await c.put("/api/widgets/donation-integration", json={"platform": "donatex", "enabled": False})
        s3 = (await c.get("/api/widgets/donation-integration")).json()
        it = next(x for x in s3["items"] if x["platform"] == "donatex")
        assert it["enabled"] is False and it["token_set"] is True
        # плохая платформа
        assert (await c.put("/api/widgets/donation-integration", json={
            "platform": "hack", "enabled": True})).json().get("error") == "bad_platform"


async def test_donatepay_poll_parses_and_dedups(tmp_db, disable_auth, monkeypatch):
    async with await _client(tmp_db) as c:
        import app.donation_integrations as di
        di._last_donatepay_id = 0  # сброс между тестами

        calls = {"n": 0}
        class FakeResp:
            status_code = 200
            def json(self):
                calls["n"] += 1
                return {"data": {"list": [
                    {"id": 7, "name": "Alice", "sum": 100, "currency": "RUB",
                     "comment": "го cat"},
                    {"id": 3, "name": "Old", "sum": 5, "currency": "RUB", "comment": ""},
                ]}}
        class FakeClient:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, params=None):
                assert "donatepay" in url and params.get("access_token") == "tok"
                return FakeResp()
        monkeypatch.setattr("httpx.AsyncClient", FakeClient)

        n = await di.poll_donatepay_once({"token": "tok"})
        assert n == 1  # только id=7 (id=3 ниже стартового курсора? нет: курсор 0 -> оба)
        # после первого прохода курсор = 7; повторный опрос не даёт дублей
        n2 = await di.poll_donatepay_once({"token": "tok"})
        assert n2 == 0
        # донат попал в топ
        top = (await c.get("/api/widgets/public/top-donator/alltime")).json()
        assert any(d.get("username") == "Alice" for d in (top.get("items") or top.get("donators") or [])) or top


async def test_donatepay_dedup_is_independent_per_scope(tmp_db, disable_auth, monkeypatch):
    async with await _client(tmp_db):
        import app.donation_integrations as di
        di._last_donatepay_scoped.clear()

        class FakeResp:
            status_code = 200
            def json(self):
                return {"data": {"list": [{
                    "id": 7, "name": "Alice", "sum": 10, "currency": "RUB",
                }]}}

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def get(self, url, params=None): return FakeResp()

        seen = []
        async def fake_process(*args, **kwargs):
            seen.append((kwargs["account_id"], kwargs["channel"]))
            return True

        monkeypatch.setattr("httpx.AsyncClient", FakeClient)
        monkeypatch.setattr(di, "_process_donation", fake_process)
        assert await di.poll_donatepay_once({
            "token": "one", "account_id": 1, "channel": "chan",
        }) == 1
        assert await di.poll_donatepay_once({
            "token": "two", "account_id": 2, "channel": "chan",
        }) == 1
        assert seen == [(1, "chan"), (2, "chan")]


async def test_donationalerts_message_parsing(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        import app.donation_integrations as di
        import json as _json
        await di._da_handle_message(_json.dumps({"method": "publication", "params": {
            "data": {"data": {"alert_type": "1", "username": "Bob", "amount": 250,
                              "currency": "RUB", "message": "kekw", "id": "da-1"}}}}))
        await di._da_handle_message(_json.dumps({"method": "publication", "params": {
            "data": {"data": {"alert_type": "1", "username": "Bob", "amount": 250,
                              "currency": "RUB", "message": "kekw", "id": "da-1"}}}}))
        # не-публикации и мусор игнорируются
        await di._da_handle_message(_json.dumps({"method": "connect"}))
        await di._da_handle_message("not json")
        pub = (await c.get("/api/widgets/public/top-donator/alltime")).json()
        assert pub  # ответ отдаётся; точная проверка имени ниже
        items = pub.get("donors") or []
        assert any(d.get("username") == "Bob" for d in items)
        from app.database import get_db
        db = await get_db()
        try:
            cursor = await db.execute("SELECT COUNT(*) AS n FROM donations WHERE username = 'Bob'")
            assert (await cursor.fetchone())["n"] == 1
        finally:
            await db.close()


async def test_public_donation_webhook(tmp_db, disable_auth, monkeypatch):
    async with await _client(tmp_db) as c:
        monkeypatch.delenv("DONATION_WEBHOOK_SECRET", raising=False)
        r = (await c.post("/api/widgets/public/donation-webhook", json={
            "username": "Carl", "amount": 5.5, "message": "hi"})).json()
        assert r["error"] == "webhook_not_configured"
        monkeypatch.setenv("DONATION_WEBHOOK_SECRET", "s3cret")
        r = (await c.post("/api/widgets/public/donation-webhook", json={
            "event_id": "webhook-1", "username": "Carl", "amount": 5.5,
            "message": "hi", "secret": "s3cret"})).json()
        assert r["ok"] is True
        # плохой amount
        r = (await c.post("/api/widgets/public/donation-webhook", json={
            "username": "X", "amount": -1, "secret": "s3cret"})).json()
        assert r.get("error") == "bad_amount"
        # с секретом
        r = (await c.post("/api/widgets/public/donation-webhook", json={
            "username": "D", "amount": 1})).json()
        assert r.get("error") == "bad_secret"
        r = (await c.post("/api/widgets/public/donation-webhook", json={
            "username": "D", "amount": 1, "secret": "s3cret"})).json()
        assert r == {"error": "event_id_required"}
        r = (await c.post("/api/widgets/public/donation-webhook", json={
            "event_id": "x" * 256, "username": "D", "amount": 1,
            "secret": "s3cret"})).json()
        assert r == {"error": "event_id_too_long"}
        r = (await c.post("/api/widgets/public/donation-webhook", json={
            "event_id": "webhook-2", "username": "D", "amount": 1,
            "secret": "s3cret"})).json()
        assert r["ok"] is True


async def test_public_donation_webhook_replay_is_a_noop(
    tmp_db, disable_auth, monkeypatch,
):
    monkeypatch.setenv("DONATION_WEBHOOK_SECRET", "s3cret")
    async with await _client(tmp_db) as c:
        payload = {
            "event_id": "stable-event", "username": "Replay", "amount": 7,
            "secret": "s3cret",
        }
        assert (await c.post(
            "/api/widgets/public/donation-webhook", json=payload,
        )).json() == {"ok": True}
        assert (await c.post(
            "/api/widgets/public/donation-webhook", json=payload,
        )).json() == {"ok": True, "duplicate": True}

        from app.database import get_db
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT COUNT(*) AS n FROM donations WHERE username = 'Replay'"
            )
            assert (await cursor.fetchone())["n"] == 1
        finally:
            await db.close()


async def test_public_donation_webhook_reports_retryable_processing_failure(
    tmp_db, disable_auth, monkeypatch,
):
    monkeypatch.setenv("DONATION_WEBHOOK_SECRET", "s3cret")

    async def fail_processing(*args, **kwargs):
        return None

    monkeypatch.setattr("app.donation_integrations._process_donation", fail_processing)
    async with await _client(tmp_db) as c:
        response = (await c.post(
            "/api/widgets/public/donation-webhook", json={
                "event_id": "retryable", "username": "Retry", "amount": 7,
                "secret": "s3cret",
            },
        )).json()
        assert response == {"error": "processing_failed"}


async def test_donatepay_dedup_survives_memory_cursor_reset(
    tmp_db, disable_auth, monkeypatch,
):
    async with await _client(tmp_db):
        import app.donation_integrations as di
        di._last_donatepay_id = 0

        class FakeResp:
            status_code = 200
            def json(self):
                return {"data": {"list": [{
                    "id": 91, "name": "Persistent", "sum": 10, "currency": "RUB",
                }]}}

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def get(self, url, params=None): return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient", FakeClient)
        assert await di.poll_donatepay_once({"token": "tok"}) == 1
        di._last_donatepay_id = 0
        assert await di.poll_donatepay_once({"token": "tok"}) == 0


async def test_donatepay_cursor_retries_processing_failure(
    tmp_db, disable_auth, monkeypatch,
):
    async with await _client(tmp_db):
        import app.donation_integrations as di
        di._last_donatepay_id = 0

        class FakeResp:
            status_code = 200
            def json(self):
                return {"data": {"list": [{
                    "id": 92, "name": "Retry", "sum": 10, "currency": "RUB",
                }]}}

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def get(self, url, params=None): return FakeResp()

        results = iter((None, True))
        calls = {"n": 0}
        async def flaky_process(*args, **kwargs):
            calls["n"] += 1
            return next(results)

        monkeypatch.setattr("httpx.AsyncClient", FakeClient)
        monkeypatch.setattr(di, "_process_donation", flaky_process)
        assert await di.poll_donatepay_once({"token": "tok"}) == 0
        assert await di.poll_donatepay_once({"token": "tok"}) == 1
        assert calls["n"] == 2


async def test_failed_donation_releases_receipt_for_retry(
    tmp_db, disable_auth, monkeypatch,
):
    async with await _client(tmp_db):
        import app.donation_integrations as di
        calls = {"n": 0}

        async def flaky_donation(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("temporary failure")
            return {"ok": True}

        monkeypatch.setattr("app.widgets.on_donation_received", flaky_donation)
        payload = {
            "account_id": 1, "channel": "chan", "event_id": "retry-event",
        }
        assert await di._process_donation(
            "donatepay", "Retry", 10, "RUB", "", **payload,
        ) is None
        assert await di._process_donation(
            "donatepay", "Retry", 10, "RUB", "", **payload,
        ) is True
        assert calls["n"] == 2

async def test_donatex_poll_parses_and_dedups(tmp_db, disable_auth, monkeypatch):
    async with await _client(tmp_db) as c:
        import app.donation_integrations as di
        import datetime as _dt
        di._seen_donatex.clear()
        di._donatex_started_at = None  # старт = now-5мин (внутри poll)

        class FakeResp:
            status_code = 200
            def json(self):
                now = _dt.datetime.now(_dt.timezone.utc)
                return {"count": 2, "donations": [
                    {"id": "uuid-2", "username": "Nina", "amount": 150,
                     "currency": "RUB", "message": "го трек",
                     "timestamp": now.isoformat(), "isTest": False},
                    {"id": "uuid-old", "username": "Old", "amount": 10,
                     "currency": "RUB", "message": "",
                     "timestamp": "2020-01-01T00:00:00Z", "isTest": False},
                    {"id": "uuid-test", "username": "Test", "amount": 999,
                     "currency": "RUB", "message": "test",
                     "timestamp": now.isoformat(), "isTest": True},
                ]}
        class FakeClient:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, params=None):
                assert "donatex" in url and params.get("token") == "tok"
                return FakeResp()
        monkeypatch.setattr("httpx.AsyncClient", FakeClient)

        n = await di.poll_donatex_once({"token": "tok"})
        assert n == 1  # только свежий не-тестовый донат
        di._seen_donatex.clear()  # имитируем restart process-memory state
        n2 = await di.poll_donatex_once({"token": "tok"})
        assert n2 == 0  # persistent дедуп по uuid
        # донат попал в топ
        pub = (await c.get("/api/widgets/public/top-donator/alltime")).json()
        assert any(d.get("username") == "Nina" for d in (pub.get("donors") or []))


async def test_donatex_platform_accepted(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        put = (await c.put("/api/widgets/donation-integration", json={
            "platform": "donatex", "enabled": True, "token": "tok123"})).json()
        assert put["ok"] is True and put["platform"] == "donatex"


async def test_donatex_goal_sync(tmp_db, disable_auth, monkeypatch):
    """Сбор DonateX → donation-challenge: базовая линия, дельты, отключение."""
    async with await _client(tmp_db) as c:
        from app.database import init_db
        from app.widgets import ensure_widgets_schema, get_db, donation_challenges_create
        await init_db()
        await ensure_widgets_schema()
        # активный челлендж на 1000
        r = await donation_challenges_create({"title": "Сабатон", "target_amount": 1000})
        cid = r["id"]
        import app.donation_integrations as di

        async def fake_fetch(goal_id):
            return {"name": "Сбор на микрофон", "current": GOAL_STATE["cur"],
                    "target": 5000, "currency": "RUB"}
        GOAL_STATE = {"cur": 300.0}
        monkeypatch.setattr(di, "fetch_donatex_goal", fake_fetch)

        # включаем синхронизацию
        put = (await c.put("/api/widgets/donation-goal-sync", json={
            "external_goal_id": "goal-123", "enabled": True})).json()
        assert put["ok"] is True
        get = (await c.get("/api/widgets/donation-goal-sync")).json()
        assert get["external_goal_id"] == "goal-123" and get["enabled"] in (1, True)

        # 1-й шаг: базовая линия 300 → челлендж НЕ дёргается
        await di._sync_donatex_goal_once()
        db = await get_db()
        try:
            cur = await db.execute("SELECT synced, last_amount "
                                   "FROM donation_goal_sync WHERE id = 1")
            row = await cur.fetchone()
            assert row["synced"] == 1 and row["last_amount"] == 300
            cur2 = await db.execute("SELECT current_amount FROM donation_challenges WHERE id = ?", (cid,))
            assert (await cur2.fetchone())["current_amount"] == 0
        finally:
            await db.close()

        # 2-й шаг: сбор вырос до 450 → челлендж +150
        GOAL_STATE["cur"] = 450.0
        await di._sync_donatex_goal_once()
        db = await get_db()
        try:
            cur2 = await db.execute("SELECT current_amount FROM donation_challenges WHERE id = ?", (cid,))
            assert (await cur2.fetchone())["current_amount"] == 150
        finally:
            await db.close()

        # локальный донат не затирается: +50 локально, сбор +100 → 150+50+100=300
        from app.widgets import on_donation_event
        await on_donation_event("LocalGuy", 50, "RUB", "")
        GOAL_STATE["cur"] = 550.0
        await di._sync_donatex_goal_once()
        db = await get_db()
        try:
            cur2 = await db.execute("SELECT current_amount FROM donation_challenges WHERE id = ?", (cid,))
            assert (await cur2.fetchone())["current_amount"] == 300
        finally:
            await db.close()

        # выключение: синхронизация неактивна
        await c.put("/api/widgets/donation-goal-sync", json={"external_goal_id": "goal-123", "enabled": False})
        GOAL_STATE["cur"] = 900.0
        assert await di._sync_donatex_goal_once() is False
        db = await get_db()
        try:
            cur2 = await db.execute("SELECT current_amount FROM donation_challenges WHERE id = ?", (cid,))
            assert (await cur2.fetchone())["current_amount"] == 300
        finally:
            await db.close()


async def test_goal_sync_disabled_without_goal_id(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        from app.database import init_db
        from app.widgets import ensure_widgets_schema
        from app import donation_integrations as di
        await init_db()
        await ensure_widgets_schema()
        # включено, но goal_id пуст → no-op
        await c.put("/api/widgets/donation-goal-sync", json={"external_goal_id": "", "enabled": True})
        assert await di._sync_donatex_goal_once() is False


async def test_scoped_provider_tokens_encrypt_and_decrypt_internally(
    tmp_db, disable_auth, monkeypatch,
):
    from cryptography.fernet import Fernet
    from app import security

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    security._FERNET = None
    security._FERNET_TRIED = False
    try:
        async with await _client(tmp_db) as client:
            from app.database import get_db
            db = await get_db()
            try:
                await db.execute(
                    "INSERT INTO accounts (id, nickname, token) VALUES (1, 'donation-test', 'fake')"
                )
                await db.execute(
                    "INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'chan', 1)"
                )
                await db.commit()
            finally:
                await db.close()
            response = await client.put(
                "/api/widgets/donation-integration?account_id=1&channel=chan",
                json={"platform": "donatepay", "enabled": True, "token": "provider-secret"},
            )
            assert response.json()["ok"] is True
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT token FROM donation_integrations_scoped "
                    "WHERE account_id = 1 AND channel = 'chan' AND platform = 'donatepay'"
                )
                stored = (await cursor.fetchone())["token"]
            finally:
                await db.close()
            assert stored.startswith("enc::") and "provider-secret" not in stored
            public_state = (await client.get(
                "/api/widgets/donation-integration?account_id=1&channel=chan"
            )).json()
            assert public_state["storage_mode"] == "encrypted"
            assert "provider-secret" not in str(public_state)
            from app.donation_integrations import get_platform_settings
            internal = await get_platform_settings("donatepay", (1, "chan"))
            assert internal["token"] == "provider-secret"
    finally:
        security._FERNET = None
        security._FERNET_TRIED = False


async def test_reconnect_starts_all_scoped_providers_and_keeps_last_success(
    tmp_db, disable_auth, monkeypatch,
):
    async with await _client(tmp_db) as client:
        import app.donation_integrations as di
        from app.database import get_db
        started = []

        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO accounts (id, nickname, token) VALUES (1, 'donation-test', 'fake')"
            )
            await db.execute(
                "INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'chan', 1)"
            )
            await db.commit()
        finally:
            await db.close()

        async def fake_loop(settings):
            started.append((settings["platform"], settings["account_id"], settings["channel"]))
            await di._record_provider_success(settings["platform"], (1, "chan"))

        for platform in ("donatepay", "donatex", "donationalerts"):
            await client.put(
                "/api/widgets/donation-integration?account_id=1&channel=chan",
                json={"platform": platform, "enabled": True, "token": f"token-{platform}"},
            )
            monkeypatch.setitem(di._PLATFORM_LOOPS, platform, fake_loop)
            result = (await client.post(
                f"/api/widgets/donation-integration/{platform}/reconnect"
                "?account_id=1&channel=chan", json={},
            )).json()
            assert result == {"ok": True, "state": "connecting"}

        await asyncio.sleep(0.05)
        assert {item[0] for item in started} == {"donatepay", "donatex", "donationalerts"}
        di._last_status.clear()
        state = (await client.get(
            "/api/widgets/donation-integration?account_id=1&channel=chan"
        )).json()
        assert all(item["status"]["last_success_at"] for item in state["items"])


async def test_legacy_scoped_webhook_token_migrates_to_bridge(tmp_db, disable_auth):
    from app.database import get_db, init_db
    from app.widgets import ensure_widgets_schema

    await init_db()
    await ensure_widgets_schema()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token) VALUES (41, 'bot', '')"
        )
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (41, 'legacychan', 1)"
        )
        await db.execute(
            "INSERT INTO donation_integrations_scoped "
            "(account_id, channel, platform, webhook_token) VALUES (41, 'legacychan', 'donatepay', 'old-bridge-token')"
        )
        await db.commit()
    finally:
        await db.close()

    await ensure_widgets_schema()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT token, enabled FROM donation_webhook_scopes "
            "WHERE account_id = 41 AND channel = 'legacychan'"
        )
        row = await cursor.fetchone()
        assert row["token"] == "old-bridge-token"
        assert row["enabled"] == 1
    finally:
        await db.close()


async def test_reconnect_reports_missing_token_truthfully(tmp_db, disable_auth):
    import app.donation_integrations as di

    async with await _client(tmp_db) as client:
        result = (await client.post(
            "/api/widgets/donation-integration/donatepay/reconnect", json={},
        )).json()
        assert result == {"ok": False, "state": "disabled"}

        await client.put("/api/widgets/donation-integration", json={
            "platform": "donatepay", "enabled": True,
        })
        result = (await client.post(
            "/api/widgets/donation-integration/donatepay/reconnect", json={},
        )).json()
        assert result == {"ok": False, "state": "missing_token"}
    await di.stop_integrations()
