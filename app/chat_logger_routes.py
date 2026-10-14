"""PLAN.md «Чат-логгер»: вкладка «📡 Чат-логгер» — статус, токен/каналы,
поиск, экспорт, источник для C1 «Собрать стиль чатера».

Архитектура: логгер — ОТДЕЛЬНАЯ программа (scripts/chatlogger/logger.py),
сидит в чужих чатах и пишет в data/chatlogger.sqlite3. Панель НЕ запускает
логгер — она читает/пишет его sqlite (это безопасно: WAL-режим, отдельная база,
логгер живёт в другом процессе; тесты tmp-базой изолируются).

Роуты:
    GET  /api/chat-logger/status              — жив/каналы/всего сообщений/размер
    POST /api/chat-logger/token               — {token, nick} (chat:read)
    GET/POST/DELETE /api/chat-logger/channels — список каналов (+ add/soft-del)
    GET  /api/chat-logger/search              — ?channel&user&q&limit
    GET  /api/chat-logger/export.csv          — ?channel&user
"""
from __future__ import annotations

import csv
import io
import math
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.security import auth_dependency

logger_router = APIRouter(prefix="/api/chat-logger", tags=["chat-logger"],
                          dependencies=[Depends(auth_dependency)])

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "chatlogger.sqlite3"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Своя база логгера (может ещё не существовать — тогда создаём пустую).

    Схема идентична scripts/chatlogger/logger.py::SCHEMA (логгер и панель
    работают с одной базой)."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            username TEXT NOT NULL,
            message TEXT NOT NULL,
            ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(channel, username, ts);
        CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(ts);
        CREATE TABLE IF NOT EXISTS channels (
            channel TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    return conn


def _norm(ch: str) -> str:
    return (ch or "").strip().lstrip("#").lower()


@logger_router.get("/status")
async def status() -> dict:
    """Полный статус вкладки: токен/каналы/объёмы + per-канальный статус.

    Per-канал: connected (🟢 логгер в чате) / msg_count / last_msg_ts — из
    channel_status, куда пишет сам логгер. running — pid-файл + процесс.
    """
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
        chans = [dict(r) for r in conn.execute(
            "SELECT c.channel, c.enabled FROM channels c ORDER BY c.channel").fetchall()]
        last = conn.execute("SELECT MAX(ts) m FROM messages").fetchone()["m"]
        token = conn.execute("SELECT value FROM config WHERE key='token'").fetchone()
        nick = conn.execute("SELECT value FROM config WHERE key='nick'").fetchone()
        try:
            per = {r["channel"]: dict(r) for r in conn.execute(
                "SELECT * FROM channel_status").fetchall()}
        except sqlite3.OperationalError:
            per = {}
        st_row = conn.execute("SELECT value FROM config WHERE key='status'").fetchone()
    finally:
        conn.close()

    for ch in chans:
        cs = per.get(ch["channel"]) or {}
        ch["connected"] = bool(cs.get("connected"))
        ch["msg_count"] = int(cs.get("msg_count") or 0)
        ch["last_msg_ts"] = cs.get("last_msg_ts")

    pid = _find_running_pid()
    logger_status = (st_row["value"] if st_row else "") or ""
    if pid is None and logger_status == "running":
        logger_status = "died"  # pid-файла нет, а статус не сброшен (kill -9?)
    return {
        "ok": True,
        "configured": bool(token and str(token["value"]).strip()),
        "nick": (nick["value"] if nick else "") or "",
        "messages_total": total,
        "messages_24h": _count_24h(),
        "last_message_ts": last,
        "channels": chans,
        "channels_connected": sum(1 for c in chans if c["connected"]),
        "db_path": str(DB_PATH),
        "db_size_mb": round(DB_PATH.stat().st_size / 1_048_576, 2) if DB_PATH.exists() else 0,
        "running": pid is not None,
        "pid": pid,
        "logger_status": logger_status,
    }


def _count_24h() -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE ts > datetime('now', '-1 day')")
        return int(cur.fetchone()["c"])
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


# ── P8-чатлоггер: честный статус токена (Twitch oauth2/validate) ──
# Кэш на 10 минут, чтобы не дёргать Twitch на каждый рендер вкладки.
_validate_cache: dict[str, tuple[float, dict]] = {}


async def validate_token(token: str) -> dict:
    """Twitch /oauth2/validate without treating provider failures as expiry."""
    now = time.time()
    cached = _validate_cache.get(token)
    if cached and now - cached[0] < 600:
        return cached[1]
    result: dict = {"valid": False, "login": "", "expires_in": 0, "error": "request_failed"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://id.twitch.tv/oauth2/validate",
                headers={"Authorization": f"OAuth {token.removeprefix('oauth:')}"},
            )
        if resp.status_code == 200:
            body = resp.json()
            result = {"valid": True,
                      "login": str(body.get("login") or ""),
                      "expires_in": int(body.get("expires_in") or 0)}
            _validate_cache[token] = (now, result)
        elif resp.status_code == 401:
            result = {"valid": False, "login": "", "expires_in": 0}
        else:
            result["error"] = f"http_{resp.status_code}"
    except Exception:
        pass
    return result


@logger_router.get("/token-status")
async def token_status() -> dict:
    """Честный статус токена логгера: valid / expiring (<7 дней) / expired / none.

    running-статус отдаётся только при наличии ключа запуска (панельная кнопка).
    """
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM config WHERE key='token'").fetchone()
        token = (str(row["value"]) if row else "").strip().removeprefix("oauth:")
    finally:
        conn.close()
    if not token:
        return {"ok": True, "state": "none", "login": "", "expires_in_days": None,
                "running": _find_running_pid() is not None}
    v = await validate_token(token)
    if not v["valid"]:
        # различаем «точно невалиден» и «не удалось проверить»
        state = "unknown" if v.get("error") else "expired"
        return {"ok": True, "state": state, "login": "", "expires_in_days": None,
                "running": _find_running_pid() is not None}
    days = v["expires_in"] / 86400
    return {"ok": True, "state": "expiring" if days < 7 else "valid",
            "login": v["login"], "expires_in_days": math.ceil(days),
            "expires_in_hours": round(v["expires_in"] / 3600),
            "running": _find_running_pid() is not None}


@logger_router.post("/token")
async def set_token(data: dict[str, Any]) -> dict:
    token = str(data.get("token") or "").strip().removeprefix("oauth:").strip()
    nick = str(data.get("nick") or "").strip()
    if not token:
        return {"ok": False, "error": "empty_token"}
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO config (key, value) VALUES ('token', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (token,))
        if nick:
            conn.execute(
                "INSERT INTO config (key, value) VALUES ('nick', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (nick,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@logger_router.get("/channels")
async def list_channels() -> dict:
    conn = _connect()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT channel, enabled FROM channels ORDER BY channel").fetchall()]
        return {"ok": True, "channels": rows}
    finally:
        conn.close()


@logger_router.post("/channels")
async def add_channel(data: dict[str, Any]) -> dict:
    ch = _norm(str(data.get("channel") or ""))
    if not ch:
        return {"ok": False, "error": "empty_channel"}
    conn = _connect()
    try:
        conn.execute("INSERT OR IGNORE INTO channels (channel) VALUES (?)", (ch,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "channel": ch}


@logger_router.delete("/channels/{channel}")
async def remove_channel(channel: str) -> dict:
    conn = _connect()
    try:
        conn.execute("DELETE FROM channels WHERE channel = ?", (_norm(channel),))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@logger_router.get("/search")
async def search(
    channel: str = "",
    user: str = "",
    q: str = "",
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    conn = _connect()
    try:
        sql = "SELECT channel, username, message, ts FROM messages WHERE 1=1"
        params: list[Any] = []
        if channel:
            sql += " AND channel = ?"
            params.append(_norm(channel))
        if user:
            sql += " AND username = ?"
            params.append(user.lower().lstrip("@"))
        if q:
            sql += " AND message LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        return {"ok": True, "items": rows}
    finally:
        conn.close()


@logger_router.get("/export.csv")
async def export_csv(channel: str = "", user: str = "", limit: int = 5000):
    conn = _connect()
    try:
        sql = "SELECT channel, username, message, ts FROM messages WHERE 1=1"
        params: list[Any] = []
        if channel:
            sql += " AND channel = ?"
            params.append(_norm(channel))
        if user:
            sql += " AND username = ?"
            params.append(user.lower().lstrip("@"))
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["channel", "username", "message", "ts"])
    for r in reversed(rows):
        writer.writerow([r["channel"], r["username"], r["message"], r["ts"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=chat-logger-export.csv"},
    )


# ── Запуск/остановка логгера прямо из панели (кнопки вкладки) ──
# Логгер — дочерний процесс python3 scripts/chatlogger/logger.py.
# _runner_process живёт только в памяти панели: при рестарте панели кнопка
# «Статус» честно покажет running=false, даже если старый процесс ещё висит
# (его можно «Остановить» — по PID-файлу, см. stop).
_runner_process: subprocess.Popen | None = None


def _logger_pid_file() -> Path:
    return ROOT / "data" / "chatlogger.pid"


def _logger_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _find_running_pid() -> int | None:
    """Панельный дочерний процесс ИЛИ чужой запущенный (по pid-файлу)."""
    global _runner_process
    if _runner_process is not None and _runner_process.poll() is None:
        return _runner_process.pid
    pidf = _logger_pid_file()
    if pidf.exists():
        try:
            pid = int(pidf.read_text().strip())
            if _logger_alive(pid):
                return pid
        except (ValueError, OSError):
            pass
    return None


@logger_router.post("/start")
async def start_logger() -> dict:
    global _runner_process
    pid = _find_running_pid()
    if pid is not None:
        return {"ok": True, "running": True, "pid": pid, "already": True}
    script = ROOT / "scripts" / "chatlogger" / "logger.py"
    if not script.exists():
        return {"ok": False, "error": "script_missing"}
    _logger_pid_file().parent.mkdir(parents=True, exist_ok=True)
    logf = open(ROOT / "logs" / "chatlogger.out", "ab")
    _runner_process = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # не умирает вместе с панелью
    )
    _logger_pid_file().write_text(str(_runner_process.pid))
    return {"ok": True, "running": True, "pid": _runner_process.pid}


@logger_router.post("/stop")
async def stop_logger() -> dict:
    global _runner_process
    stopped: list[int] = []
    if _runner_process is not None and _runner_process.poll() is None:
        try:
            os.killpg(_runner_process.pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        stopped.append(_runner_process.pid)
        _runner_process = None
    # чужой процесс по pid-файлу (запущен вручную/docker) — тоже гасим
    pidf = _logger_pid_file()
    if pidf.exists():
        try:
            pid = int(pidf.read_text().strip())
            if pid not in stopped and _logger_alive(pid):
                os.kill(pid, signal.SIGTERM)
                stopped.append(pid)
        except (ValueError, OSError):
            pass
        try:
            pidf.unlink()
        except OSError:
            pass
    return {"ok": True, "running": False, "stopped": stopped}


@logger_router.get("/log")
async def log_tail(
    channel: str = Query(...),
    after_id: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Хвост лога канала (для «смотреть чат стрима» во вкладке).

    after_id=0 → последние `limit` сообщений (в хронологическом порядке);
    after_id=N → только сообщения с id > N (для Live-догрузки). Возвращает
    last_id — курсор для следующего запроса.
    """
    ch = _norm(channel)
    if not ch:
        return {"ok": False, "error": "empty_channel"}
    conn = _connect()
    try:
        if after_id > 0:
            cur = conn.execute(
                "SELECT id, username, message, ts FROM messages "
                "WHERE channel = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (ch, after_id, limit))
            rows = [dict(r) for r in cur.fetchall()]
        else:
            cur = conn.execute(
                "SELECT * FROM (SELECT id, username, message, ts FROM messages "
                "WHERE channel = ? ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                (ch, limit))
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return {"ok": True, "channel": ch, "items": rows,
            "last_id": (rows[-1]["id"] if rows else after_id)}
