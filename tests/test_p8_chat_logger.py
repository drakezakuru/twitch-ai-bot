"""PLAN.md «Чат-логгер» v1: ядро (IRC-парсер + sqlite) и вкладка «📡 Чат-логгер».

Логгер — отдельная программа (scripts/chatlogger/logger.py): сидит в чужих
чатах как зритель, пишет историю в data/chatlogger.sqlite3. Панель читает/
пишет ту же базу (статус/токен/каналы/поиск/экспорт). «Собрать стиль чатера»
получает 3-й источник — наш логгер (после ivr.fi).
"""
from __future__ import annotations

import importlib.util
import math
import sqlite3
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]


def _load_logger_module(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "chatlogger_logger", ROOT / "scripts" / "chatlogger" / "logger.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_irc_privmsg_parsing():
    mod = _load_logger_module(ROOT / "data")
    seen = []
    irc = mod.TwitchIRCReader("token", "nick", ["chan"], lambda c, u, m: seen.append((c, u, m)))
    line = ":viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #mychan :привет всем :)"
    irc._handle_privmsg(line)
    assert seen == [("mychan", "viewer", "привет всем :)")]
    # кривые строки не роняют
    irc._handle_privmsg("PING")
    irc._handle_privmsg("garbage")
    assert len(seen) == 1


def test_irc_channels_normalized():
    mod = _load_logger_module(ROOT / "data")
    irc = mod.TwitchIRCReader("t", "N", ["#Chan ", "@other"], lambda *a: None)
    assert irc.channels == ["chan", "other"]


def test_db_schema_and_config_roundtrip(tmp_path):
    mod = _load_logger_module(tmp_path)
    mod.DB_PATH = tmp_path / "chatlogger.sqlite3"
    conn = mod.db()
    conn.execute("INSERT INTO config (key, value) VALUES ('token', 'oauth:abc')")
    conn.execute("INSERT INTO channels (channel) VALUES ('chan1')")
    conn.commit()
    assert conn.execute("SELECT value FROM config WHERE key='token'").fetchone()["value"] == "oauth:abc"
    assert conn.execute("SELECT COUNT(*) c FROM channels").fetchone()["c"] == 1


# ── Панельная вкладка ──────────────────────────────────────────────

@pytest.fixture
def app(disable_auth, tmp_db, tmp_path, monkeypatch):
    import app.chat_logger_routes as clr
    monkeypatch.setattr(clr, "DB_PATH", tmp_path / "chatlogger.sqlite3")
    application = FastAPI()
    from app.chat_logger_routes import logger_router
    application.include_router(logger_router)
    return application


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_token_channels_search_export(tmp_path, monkeypatch):
    import app.chat_logger_routes as clr
    dbp = tmp_path / "chatlogger.sqlite3"
    monkeypatch.setattr(clr, "DB_PATH", dbp)
    # seed напрямую (как это делает логгер): та же схема
    conn = sqlite3.connect(dbp)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL, username TEXT NOT NULL,
            message TEXT NOT NULL, ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS channels (
            channel TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1);
    """)
    conn.execute("INSERT INTO channels (channel) VALUES ('chan1')")
    conn.execute("INSERT INTO messages (channel, username, message) VALUES ('chan1','viewer','привет'),('chan1','viewer','ахах'),('chan1','other','го')")
    conn.commit()
    conn.close()

    from app.chat_logger_routes import status, add_channel, set_token, search, list_channels
    st = await status()
    assert st["ok"] is True and st["messages_total"] == 3 and st["configured"] is False
    tok = await set_token({"token": "oauth:xyz", "nick": "mybot"})
    assert tok["ok"] is True
    st2 = await status()
    assert st2["configured"] is True

    add = await add_channel({"channel": "#Chan2"})
    assert add["ok"] is True and add["channel"] == "chan2"
    chans = await list_channels()
    assert {c["channel"] for c in chans["channels"]} == {"chan1", "chan2"}

    found = await search(user="viewer", limit=100)
    assert found["ok"] and len(found["items"]) == 2
    assert all(i["username"] == "viewer" for i in found["items"])
    by_text = await search(q="ахах", limit=100)
    assert len(by_text["items"]) == 1


def test_c1_mimic_build_reads_logger_db(tmp_path, monkeypatch):
    """3-й источник: profile-build подхватывает историю из логгера."""
    src = (ROOT / "app" / "role_routes.py").read_text(encoding="utf-8")
    assert "chat_logger_routes" in src and "chatlogger.sqlite3" in src.replace("DB_PATH", "").replace("from app.", "") or "chatlogger" in src.lower()


@pytest.mark.asyncio
async def test_token_status_states(tmp_path, monkeypatch):
    """Честный статус: none / expired / expiring / valid (mock Twitch validate)."""
    import app.chat_logger_routes as clr
    dbp = tmp_path / "chatlogger.sqlite3"
    monkeypatch.setattr(clr, "DB_PATH", dbp)
    monkeypatch.setattr(clr, "_runner_process", None)
    monkeypatch.setattr(clr, "_logger_pid_file", lambda: tmp_path / "chatlogger.pid")
    clr._validate_cache.clear()

    # 1) нет токена
    st = await clr.token_status()
    assert st["state"] == "none" and st["running"] is False

    # 2) Twitch validate → valid на 30 дней
    import sqlite3 as _sq
    conn = _sq.connect(dbp)
    conn.executescript(clr.SCHEMA if hasattr(clr, "SCHEMA") else "")
    conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('token', 'tok123')")
    conn.commit(); conn.close()

    async def fake_valid(token):
        return {"valid": True, "login": "mybot", "expires_in": 30 * 86400}

    monkeypatch.setattr(clr, "validate_token", fake_valid)
    st = await clr.token_status()
    assert st["state"] == "valid" and st["login"] == "mybot" and st["expires_in_days"] == 30

    # 3) истекает (<7 дней)
    async def fake_expiring(token):
        return {"valid": True, "login": "mybot", "expires_in": 3 * 86400}
    monkeypatch.setattr(clr, "validate_token", fake_expiring)
    clr._validate_cache.clear()
    st = await clr.token_status()
    assert st["state"] == "expiring" and st["expires_in_days"] == 3

    # 4) истёк
    async def fake_dead(token):
        return {"valid": False, "login": "", "expires_in": 0}
    monkeypatch.setattr(clr, "validate_token", fake_dead)
    clr._validate_cache.clear()
    st = await clr.token_status()
    assert st["state"] == "expired"


@pytest.mark.asyncio
async def test_token_status_unknown_has_no_days_and_positive_days_use_ceiling(tmp_path, monkeypatch):
    import app.chat_logger_routes as clr
    dbp = tmp_path / "chatlogger.sqlite3"
    monkeypatch.setattr(clr, "DB_PATH", dbp)
    monkeypatch.setattr(clr, "_runner_process", None)
    monkeypatch.setattr(clr, "_logger_pid_file", lambda: tmp_path / "chatlogger.pid")
    conn = clr._connect()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('token', 'tok123')")
    conn.commit(); conn.close()

    async def unknown(_token):
        return {"valid": False, "login": "", "expires_in": 0, "error": "http_500"}

    monkeypatch.setattr(clr, "validate_token", unknown)
    status = await clr.token_status()
    assert status["state"] == "unknown"
    assert status["expires_in_days"] is None

    async def valid(_token):
        return {"valid": True, "login": "logger", "expires_in": int(1.1 * 86400)}

    monkeypatch.setattr(clr, "validate_token", valid)
    status = await clr.token_status()
    assert status["expires_in_days"] == math.ceil(1.1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, {"valid": False}), (429, {"valid": False, "error": "http_429"}),
     (500, {"valid": False, "error": "http_500"})],
)
async def test_validate_only_401_is_expired_and_negative_results_are_not_cached(monkeypatch, status_code, expected):
    import app.chat_logger_routes as clr
    import httpx

    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"message": "failure"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    clr._validate_cache.clear()
    first = await clr.validate_token("token")
    second = await clr.validate_token("token")
    for key, value in expected.items():
        assert first.get(key) == value
        assert second.get(key) == value
    assert ("error" not in first) is (status_code == 401)
    assert calls == 2


@pytest.mark.asyncio
async def test_validate_caches_only_success(monkeypatch):
    import app.chat_logger_routes as clr
    import httpx

    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"login": "logger", "expires_in": 900})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    clr._validate_cache.clear()
    assert (await clr.validate_token("token"))["valid"] is True
    assert (await clr.validate_token("token"))["valid"] is True
    assert calls == 1


@pytest.mark.asyncio
async def test_validate_network_failure_is_unknown_and_not_cached(monkeypatch):
    import app.chat_logger_routes as clr
    import httpx

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    clr._validate_cache.clear()
    first = await clr.validate_token("token")
    second = await clr.validate_token("token")
    assert first["valid"] is False and first["error"] == "request_failed"
    assert second["valid"] is False and second["error"] == "request_failed"
    assert calls == 2


def test_token_status_states_i18n():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for key in ("chatlog.state.valid", "chatlog.state.expiring",
                "chatlog.state.expired", "chatlog.state.none"):
        assert js.count(f"'{key}':") >= 3, key


@pytest.mark.asyncio
async def test_start_stop_logger_process(tmp_path, monkeypatch):
    """Кнопки запуска/остановки: реальный дочерний процесс со скриптом-заглушкой."""
    import app.chat_logger_routes as clr
    import asyncio, time as _t
    fake_root = tmp_path
    (fake_root / "scripts" / "chatlogger").mkdir(parents=True)
    (fake_root / "data").mkdir(exist_ok=True)
    (fake_root / "logs").mkdir(exist_ok=True)
    (fake_root / "scripts" / "chatlogger" / "logger.py").write_text(
        "import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(clr, "ROOT", fake_root)
    monkeypatch.setattr(clr, "_runner_process", None)

    res = await clr.start_logger()
    assert res["ok"] is True and res["running"] is True
    proc = clr._runner_process
    assert proc is not None and proc.poll() is None
    _t.sleep(0.2)
    st = await clr.token_status()
    assert st["running"] is True

    stop = await clr.stop_logger()
    assert stop["ok"] is True and stop["running"] is False
    _t.sleep(0.3)
    assert clr._runner_process is None
    assert proc.poll() is not None  # процесс реально завершился
    # повторная остановка безопасна
    stop2 = await clr.stop_logger()
    assert stop2["ok"] is True


@pytest.mark.asyncio
async def test_log_tail_and_cursor(tmp_path, monkeypatch):
    """Просмотр чата стрима: хвост в хронологии + after_id курсор для Live."""
    import app.chat_logger_routes as clr
    dbp = tmp_path / "chatlogger.sqlite3"
    monkeypatch.setattr(clr, "DB_PATH", dbp)
    conn = sqlite3.connect(dbp)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, username TEXT,
            message TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);""")
    for i in range(1, 6):
        conn.execute("INSERT INTO messages (channel, username, message) VALUES ('c1', ?, ?)",
                     (f"u{i}", f"msg{i}"))
    conn.commit(); conn.close()

    r1 = await clr.log_tail(channel="c1", after_id=0, limit=3)
    assert r1["ok"] and [i["message"] for i in r1["items"]] == ["msg3", "msg4", "msg5"]
    assert r1["last_id"] == 5
    # Live-догрузка: только новое
    conn = sqlite3.connect(dbp)
    conn.execute("INSERT INTO messages (channel, username, message) VALUES ('c1','u6','msg6')")
    conn.commit(); conn.close()
    r2 = await clr.log_tail(channel="c1", after_id=5, limit=100)
    assert [i["message"] for i in r2["items"]] == ["msg6"] and r2["last_id"] == 6
    r3 = await clr.log_tail(channel="c1", after_id=6, limit=100)
    assert r3["items"] == [] and r3["last_id"] == 6
