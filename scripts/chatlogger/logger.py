"""PLAN.md «Чат-логгер» v1 — ядро: IRC-зритель + SQLite + мини-API.

Отдельная программа (НЕ панель, НЕ бот-болтун): заходит в Twitch-чат как
зритель (IRC, oauth токен с chat:read), ЧИТАЕТ публичные чаты и складывает
каждое сообщение в SQLite (channel, username, message, ts) + дневной файл
logs/<channel>/<YYYY-MM-DD>.log. Одно соединение держит десятки каналов.

Запуск (из папки проекта, рядом с twitch-ai-bot/):
    python3 scripts/chatlogger/logger.py                # конфиг из data/chatlogger.sqlite3
    python3 scripts/chatlogger/logger.py --config X.sqlite3

Мини-API (по умолчанию 127.0.0.1:8765, только localhost):
    GET /health                       — {ok, connected, channels, messages_total}
    GET /history?channel=X&user=Y     — сообщения юзера (формат ivr.fi-подобный)
    GET /users?channel=X&q=...        — активные юзеры канала

Токен владельца добавляет владелец САМ: sqlite-таблица config (token, channels),
вкладка «📡 Чат-логгер» в панели пишет туда же (v1: панель — отдельный шаг).

Хостинг: Steam Deck рядом с панелью; VPS/бесплатный tier — потом.
docker-compose (chatlogger.yml) лежит рядом для будущего VPS.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import socket
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .../twitch-ai-bot
sys.path.insert(0, str(ROOT))

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6667
PING_INTERVAL = 60
DB_PATH = ROOT / "data" / "chatlogger.sqlite3"
LOGS_DIR = ROOT / "data" / "chatlogger_logs"
API_HOST = "127.0.0.1"
API_PORT = 8765

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS channel_status (
    channel TEXT PRIMARY KEY,
    connected INTEGER NOT NULL DEFAULT 0,
    msg_count INTEGER NOT NULL DEFAULT 0,
    last_msg_ts TIMESTAMP
);
"""


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


_db_conn: sqlite3.Connection | None = None


def _db_exec(sql: str, params: tuple = ()) -> None:
    if _db_conn is not None:
        _db_conn.execute(sql, params)
        _db_conn.commit()


def day_log_line(channel: str, username: str, message: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    day_dir = LOGS_DIR / channel.lower()
    day_dir.mkdir(exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(day_dir / f"{name}.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {username}: {message}\n")


class TwitchIRCReader:
    """Минимальный IRC-клиент: PASS/NICK/JOIN + PING, парс PRIVMSG."""

    def __init__(self, token: str, nick: str, channels: list[str],
                 on_message, channels_provider=None) -> None:
        self.token = token if token.startswith("oauth:") else f"oauth:{token}"
        self.nick = (nick or "justinfan12345").lower()
        self.channels = [c.strip().lower().lstrip("#").lstrip("@") for c in channels
                         if c.strip()]
        # P8-чатлоггер: каналы можно добавлять на лету (панель пишет в БД,
        # логгер подхватывает без перезапуска)
        self.channels_provider = channels_provider
        self.on_message = on_message
        self.connected = False
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._session()
            except (OSError, socket.timeout) as exc:
                print(f"[chatlogger] irc error: {exc}; reconnect in 5s")
            self.connected = False
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    async def _session(self) -> None:
        reader, writer = await asyncio.open_connection(IRC_HOST, IRC_PORT)
        try:
            writer.write(f"PASS {self.token}\r\n".encode())
            writer.write(f"NICK {self.nick}\r\n".encode())
            writer.write("CAP REQ :twitch.tv/tags\r\n".encode())
            self.channels = list(self.channels or [])
            for ch in self.channels:
                writer.write(f"JOIN #{ch}\r\n".encode())
            await writer.drain()
            self.connected = True
            self._mark_channels(self.channels, connected=1)
            print(f"[chatlogger] connected, channels: {len(self.channels)}")
            last_ping = time.time()
            last_sync = time.time()
            joined = set(self.channels)
            while not self._stop.is_set():
                if time.time() - last_ping > PING_INTERVAL:
                    writer.write("PING :tmi.twitch.tv\r\n".encode())
                    await writer.drain()
                    last_ping = time.time()
                try:
                    line_bytes = await asyncio.wait_for(reader.readline(), timeout=5)
                except asyncio.TimeoutError:
                    line_bytes = b""
                if line_bytes:
                    line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.startswith("PING"):
                        writer.write(f"PONG {line.split(':', 1)[-1]}\r\n".encode())
                        await writer.drain()
                        continue
                    if "PRIVMSG" in line:
                        self._handle_privmsg(line)
                # живая синхронизация каналов каждые 10с (добавил в панели —
                # подключилось само, без перезапуска)
                if self.channels_provider and time.time() - last_sync > 10:
                    last_sync = time.time()
                    target = set(self.channels_provider())
                    for ch in sorted(target - joined):
                        writer.write(f"JOIN #{ch}\r\n".encode())
                        print(f"[chatlogger] +#{ch}")
                    for ch in sorted(joined - target):
                        writer.write(f"PART #{ch}\r\n".encode())
                        print(f"[chatlogger] -#{ch}")
                    await writer.drain()
                    joined = target
                    self.channels = list(target)
                    self._mark_channels(target, connected=1)
        finally:
            self.connected = False
            try:
                writer.close()
            except Exception:
                pass

    def _mark_channels(self, chans, *, connected: int) -> None:
        """Обновляет channel_status.connected (панель показывает 🟢/⚫ у канала)."""
        try:
            for ch in chans:
                _db_exec("INSERT INTO channel_status (channel, connected) VALUES (?, ?) "
                         "ON CONFLICT(channel) DO UPDATE SET connected = excluded.connected",
                         (ch, connected))
        except Exception as exc:
            print(f"[chatlogger] channel_status error: {exc}")

    def _handle_privmsg(self, line: str) -> None:
        # [tags ]:nick!nick@nick.tmi.twitch.tv PRIVMSG #channel :message
        try:
            marker = " PRIVMSG #"
            i = line.index(marker)
            head = line[:i]
            rest = line[i + len(marker):]
            channel, _, msg = rest.partition(":")
            prefix = head.split(" ", 1)[-1].lstrip(":").split("!")[0]
            channel = channel.strip().lower()
            if prefix and channel and msg.strip():
                self.on_message(channel, prefix, msg.strip())
        except (ValueError, IndexError):
            pass


def main() -> None:
    global DB_PATH
    parser = argparse.ArgumentParser(description="Twitch chat logger v1 (PLAN.md)")
    parser.add_argument("--config", default=str(DB_PATH), help="путь к sqlite-конфигу")
    parser.add_argument("--api-host", default=API_HOST)
    parser.add_argument("--api-port", type=int, default=API_PORT)
    args = parser.parse_args()
    DB_PATH = Path(args.config)

    global _db_conn
    conn = db()
    _db_conn = conn
    token = conn.execute("SELECT value FROM config WHERE key='token'").fetchone()
    nick = conn.execute("SELECT value FROM config WHERE key='nick'").fetchone()
    channels = [r["channel"] for r in conn.execute(
        "SELECT channel FROM channels WHERE enabled = 1").fetchall()]
    token = (token["value"] if token else "").strip()
    if not channels:
        print("[chatlogger] нет каналов — добавь их в таблицу channels (или из панели)")
    if not token:
        print("[chatlogger] НЕТ ТОКЕНА — владелец добавляет САМ (config.token, oauth chat:read)")
        token = "kappa"  # justinfan-анонимный режим всё равно требует любой PASS

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def on_message(channel: str, username: str, message: str) -> None:
        ch = channel.lower()
        conn.execute(
            "INSERT INTO messages (channel, username, message) VALUES (?, ?, ?)",
            (ch, username.lower(), message))
        conn.execute(
            "INSERT INTO channel_status (channel, connected, msg_count, last_msg_ts) "
            "VALUES (?, 1, 1, CURRENT_TIMESTAMP) "
            "ON CONFLICT(channel) DO UPDATE SET msg_count = msg_count + 1, "
            "last_msg_ts = CURRENT_TIMESTAMP", (ch,))
        conn.commit()
        day_log_line(channel, username, message)

    def channels_provider():
        # панель пишет channels (enabled=1) — логгер подхватывает за ≤10с
        return [r["channel"] for r in conn.execute(
            "SELECT channel FROM channels WHERE enabled = 1").fetchall()]

    irc = TwitchIRCReader(token, (nick["value"] if nick else ""), channels, on_message,
                          channels_provider=channels_provider)

    from aiohttp import web

    async def health(_req):
        total = conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
        chans = conn.execute("SELECT COUNT(*) c FROM channels WHERE enabled=1").fetchone()["c"]
        return web.json_response({"ok": True, "connected": irc.connected,
                                  "channels": chans, "messages_total": total})

    async def history(req):
        ch = req.query.get("channel", "").lower().lstrip("#")
        user = req.query.get("user", "").lower().lstrip("@")
        limit = min(1000, int(req.query.get("limit", 200)))
        rows = conn.execute(
            "SELECT username, message, ts FROM messages WHERE channel=? AND username=? "
            "ORDER BY id DESC LIMIT ?", (ch, user, limit)).fetchall()
        return web.json_response({
            "channel": ch, "user": user,
            "lines": [{"username": r["username"], "message": r["message"], "ts": r["ts"]}
                      for r in reversed(rows)]})

    async def users(req):
        ch = req.query.get("channel", "").lower().lstrip("#")
        q = req.query.get("q", "").lower()
        rows = conn.execute(
            "SELECT username, COUNT(*) cnt FROM messages WHERE channel=? "
            "AND username LIKE ? GROUP BY username ORDER BY cnt DESC LIMIT 50",
            (ch, f"%{q}%")).fetchall()
        return web.json_response({"users": [dict(r) for r in rows]})

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/history", history)
    app.router.add_get("/users", users)

    async def _api():
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, args.api_host, args.api_port)
        await site.start()
        print(f"[chatlogger] mini-API on http://{args.api_host}:{args.api_port}")

    async def _runner():
        await asyncio.gather(irc.run(), _api())

    # pid-файл + статус процесса: панель по ним честно показывает «работает»
    pidf = DB_PATH.parent / "chatlogger.pid"
    pidf.parent.mkdir(parents=True, exist_ok=True)
    pidf.write_text(str(os.getpid()))
    _db_exec("INSERT INTO config (key, value) VALUES ('status', 'running') "
             "ON CONFLICT(key) DO UPDATE SET value = 'running'")

    def _cleanup():
        _db_exec("INSERT INTO config (key, value) VALUES ('status', 'stopped') "
                 "ON CONFLICT(key) DO UPDATE SET value = 'stopped'")
        _db_exec("UPDATE channel_status SET connected = 0")
        try:
            if pidf.exists() and pidf.read_text().strip() == str(os.getpid()):
                pidf.unlink()
        except OSError:
            pass

    try:
        loop.run_until_complete(_runner())
    except KeyboardInterrupt:
        irc.stop()
    finally:
        _cleanup()
        loop.close()
        conn.close()


if __name__ == "__main__":
    main()
