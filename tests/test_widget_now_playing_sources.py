"""§11.2 WIDGETS_PLAN: автозаполнение Now Playing (Last.fm / MPRIS / !np).

1. Таблица now_playing_settings сеётся, GET/PUT source-роутов работают.
2. poll_lastfm/poll_mpris — мок-тесты парсинга (без реальной сети).
3. handle_now_playing_command: только стример/мод, !np clear, !np <ссылка>.
4. apply_now_playing — единая точка записи (панель + авто + !np).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
import shutil
import subprocess

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client(tmp_db):
    from app.database import get_db, init_db
    from app.widgets import admin_router, public_router, ensure_widgets_schema
    await init_db()
    await ensure_widgets_schema()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'np_bot', 'fake')"
        )
        await db.executemany(
            "INSERT OR IGNORE INTO channels (account_id, channel_name) VALUES (1, ?)",
            [("chan",), ("other",)],
        )
        await db.commit()
    finally:
        await db.close()

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_np_source_settings_roundtrip(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        s = (await c.get("/api/widgets/now-playing/source")).json()
        assert s["source"] == "manual"
        put = (await c.put("/api/widgets/now-playing/source", json={
            "source": "lastfm", "lastfm_user": "streamer",
            "lastfm_api_key": "key123", "poll_seconds": 10,
        })).json()
        assert put["ok"] is True and put["source"] == "lastfm"
        assert put["has_lastfm_api_key"] is True
        assert "lastfm_api_key" not in put
        s = (await c.get("/api/widgets/now-playing/source")).json()
        assert s["lastfm_user"] == "streamer" and s["poll_seconds"] == 10
        assert s["has_lastfm_api_key"] is True
        assert "lastfm_api_key" not in s
        await c.put("/api/widgets/now-playing/source", json={
            "source": "lastfm", "lastfm_api_key": "",
        })
        from app.widgets import _get_np_source_settings
        assert (await _get_np_source_settings())["lastfm_api_key"] == "key123"
        # невалидный источник -> manual
        put = (await c.put("/api/widgets/now-playing/source", json={"source": "hack"})).json()
        assert put["source"] == "manual"


async def test_np_lastfm_key_panel_runtime_is_write_only():
    html = Path("templates/partials/widgets.html").read_text(encoding="utf-8")
    assert 'type="password" id="waNpLastfmKey"' in html

    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/test_widget_now_playing_source_ui.test.js"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )


async def test_np_source_manual_poll_returns_none(tmp_db, disable_auth):
    from app.database import init_db
    from app.widgets import ensure_widgets_schema
    from app.now_playing_sources import poll_once
    await init_db()
    await ensure_widgets_schema()
    # source=manual -> loop ничего не пишет
    assert await poll_once() is None


async def test_poll_lastfm_parses_nowplaying(tmp_db, monkeypatch):
    from app import now_playing_sources as nps

    class FakeResp:
        status_code = 200
        def json(self):
            return {"recenttracks": {"track": [{
                "name": "Believer", "artist": {"#text": "Imagine Dragons"},
                "@attr": {"nowplaying": "true"},
            }]}}
    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            assert "audioscrobbler" in url
            return FakeResp()
    monkeypatch.setattr(nps.httpx if hasattr(nps, "httpx") else sys.modules["httpx"],
                        "AsyncClient", FakeClient)

    data = await nps.poll_lastfm({"lastfm_user": "u", "lastfm_api_key": "k"})
    assert data == {"text": "Believer", "subtext": "Imagine Dragons", "kind": "music"}
    # без ключа/юзера — None
    assert await nps.poll_lastfm({}) is None


async def test_poll_mpris_parses_playerctl(tmp_db, monkeypatch):
    from app.now_playing_sources import poll_mpris

    class FakeProc:
        returncode = 0
        async def communicate(self):
            return (b"Believer|||Imagine Dragons\n", b"")
    async def fake_exec(*args, **kwargs):
        return FakeProc()
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    data = await poll_mpris({"mpris_player": ""})
    assert data["text"] == "Believer" and data["subtext"] == "Imagine Dragons"
    # playerctl отсутствует
    async def fake_exec_missing(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec_missing)
    assert await poll_mpris({}) is None


async def test_np_command_roles_and_clear(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        from app.widgets import handle_now_playing_command
        # зритель — forbidden
        r = await handle_now_playing_command("!np test", "viewer1", 1, "chan", role="viewer")
        assert r["error"] == "forbidden"
        # модер — ок
        r = await handle_now_playing_command(
            "!np https://www.youtube.com/watch?v=abc12345678", "mod1", 1, "chan", role="mod")
        assert r["ok"] is True and r["action"] == "set"
        # oembed мог не отработать (нет сети) — но text обязан заполниться
        scoped_url = "/api/widgets/now-playing?account_id=1&channel=chan"
        assert (await c.get(scoped_url)).json()["text"]
        assert (await c.get("/api/widgets/now-playing")).json()["text"] == ""
        # clear
        r = await handle_now_playing_command("!np clear", "mod1", 1, "chan", role="broadcaster")
        assert r["action"] == "cleared"
        assert (await c.get(scoped_url)).json()["text"] == ""


async def test_apply_now_playing_shared_write_path(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        from app.widgets import apply_now_playing
        r = await apply_now_playing({"text": "Track A", "subtext": "X", "kind": "music"})
        assert r["ok"] is True
        # через PUT (панель) то же состояние видно
        data = (await c.get("/api/widgets/now-playing")).json()
        assert data["text"] == "Track A"


async def test_now_playing_scopes_are_isolated(tmp_db, disable_auth):
    async with await _client(tmp_db) as c:
        await c.put(
            "/api/widgets/now-playing?account_id=1&channel=chan",
            json={"text": "Track A", "kind": "music"},
        )
        await c.put(
            "/api/widgets/now-playing?account_id=1&channel=other",
            json={"text": "Track B", "kind": "music"},
        )
        a = (await c.get(
            "/api/widgets/public/now-playing?account_id=1&channel=%23CHAN"
        )).json()
        b = (await c.get(
            "/api/widgets/public/now-playing?account_id=1&channel=other"
        )).json()
        legacy = (await c.get("/api/widgets/public/now-playing")).json()
        assert a["text"] == "Track A"
        assert b["text"] == "Track B"
        assert legacy["playing"] is False
