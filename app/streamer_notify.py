"""v10.4.7 Wave 4.5 — Bot-to-streamer DM (Discord/Telegram/in-panel).

Бот шлёт стримеру приватные «мысли о стриме» — не публикуя в чат канала.

Каналы доставки:
- discord  — webhook URL (Discord channel webhook).
- telegram — bot token + chat_id (https://t.me/BotFather → /newbot).
- panel    — внутренняя БД streamer_notes (UI «🔔 Уведомления»).

Severity levels:
- info     — фоновые наблюдения («thread про Elden Ring длится 30 мин»)
- warning  — «viewer X кажется хейтером, проверь»
- highlight — «кадр кажется clip-worthy»

Дизайн:
- Pure: rate-limit decision, classify_severity, format_message.
- async: send_discord_webhook, send_telegram, save_panel_note.
- StreamerNotifier — orchestrates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Iterable, Literal

logger = logging.getLogger(__name__)

Severity = Literal["info", "warning", "highlight"]


@dataclass
class NotifySettings:
    discord_webhook: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    panel_enabled: bool = True
    rate_limit_per_min: int = 6  # макс уведомлений в минуту
    min_severity: Severity = "info"  # фильтр

    SEVERITY_ORDER: tuple[Severity, ...] = ("info", "warning", "highlight")

    def severity_passes(self, sev: Severity) -> bool:
        order = self.SEVERITY_ORDER
        return order.index(sev) >= order.index(self.min_severity)


@dataclass
class RateLimiter:
    """Сколько уведомлений было за последнюю минуту."""

    window_sec: float = 60.0
    max_per_window: int = 6
    timestamps: list[float] = field(default_factory=list)

    def allow(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        cutoff = now - self.window_sec
        self.timestamps = [t for t in self.timestamps if t >= cutoff]
        if len(self.timestamps) >= self.max_per_window:
            return False
        self.timestamps.append(now)
        return True


def format_discord_payload(severity: Severity, title: str, body: str, channel: str = "") -> dict:
    emoji = {"info": "💭", "warning": "⚠️", "highlight": "🎬"}.get(severity, "💬")
    head = f"{emoji} **{title}**"
    if channel:
        head = f"{emoji} **[{channel}]** {title}"
    embed = {
        "title": title,
        "description": body[:1900],
        "color": {"info": 0x5865F2, "warning": 0xED4245, "highlight": 0xFAA61A}.get(severity, 0x99AAB5),
        "footer": {"text": f"twitch-ai-bot · {severity}"},
    }
    return {"content": head, "embeds": [embed]}


def format_telegram_text(severity: Severity, title: str, body: str, channel: str = "") -> str:
    emoji = {"info": "💭", "warning": "⚠️", "highlight": "🎬"}.get(severity, "💬")
    prefix = f"{emoji} *{_md_escape(title)}*"
    if channel:
        prefix = f"{emoji} \\[{_md_escape(channel)}\\] *{_md_escape(title)}*"
    return f"{prefix}\n\n{_md_escape(body)[:3500]}"


def _md_escape(text: str) -> str:
    if not text:
        return ""
    for ch in ("_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
        text = text.replace(ch, f"\\{ch}")
    return text


async def send_discord_webhook(webhook_url: str, payload: dict, *, timeout: float = 10.0) -> bool:
    if not webhook_url:
        return False
    try:
        import aiohttp  # type: ignore
    except Exception:
        logger.debug("aiohttp missing, skip discord webhook")
        return False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(webhook_url, json=payload) as resp:
                return 200 <= resp.status < 300
    except Exception as exc:
        logger.warning("discord webhook error: %s", exc)
        return False


async def send_telegram(bot_token: str, chat_id: str, text: str, *, timeout: float = 10.0) -> bool:
    if not bot_token or not chat_id:
        return False
    try:
        import aiohttp  # type: ignore
    except Exception:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(url, json=payload) as resp:
                return 200 <= resp.status < 300
    except Exception as exc:
        logger.warning("telegram send error: %s", exc)
        return False


# ---------- DB part ----------

async def ensure_notes_table() -> None:
    from app import database as db_mod

    await db_mod._ensure_shared()
    async with db_mod._shared_db.execute(  # type: ignore[attr-defined]
        """
        CREATE TABLE IF NOT EXISTS streamer_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            channel TEXT,
            severity TEXT,
            title TEXT,
            body TEXT,
            created_at REAL,
            read_at REAL
        )
        """
    ):
        pass
    await db_mod._shared_db.commit()  # type: ignore[union-attr]


async def save_panel_note(account_id: int, channel: str, severity: Severity, title: str, body: str) -> int:
    from app import database as db_mod

    await ensure_notes_table()
    now = time.time()
    cur = await db_mod._shared_db.execute(  # type: ignore[union-attr]
        "INSERT INTO streamer_notes(account_id, channel, severity, title, body, created_at) VALUES (?,?,?,?,?,?)",
        (account_id, channel, severity, title, body, now),
    )
    await db_mod._shared_db.commit()  # type: ignore[union-attr]
    return cur.lastrowid or 0


async def list_panel_notes(account_id: int | None = None, channel: str | None = None, limit: int = 50, only_unread: bool = False) -> list[dict]:
    from app import database as db_mod

    await ensure_notes_table()
    parts = ["SELECT id, account_id, channel, severity, title, body, created_at, read_at FROM streamer_notes"]
    conds: list[str] = []
    args: list = []
    if account_id is not None:
        conds.append("account_id = ?")
        args.append(account_id)
    if channel:
        conds.append("channel = ?")
        args.append(channel)
    if only_unread:
        conds.append("read_at IS NULL")
    if conds:
        parts.append("WHERE " + " AND ".join(conds))
    parts.append("ORDER BY id DESC LIMIT ?")
    args.append(int(limit))
    async with db_mod._shared_db.execute(" ".join(parts), args) as cur:  # type: ignore[union-attr]
        rows = await cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "account_id": r[1], "channel": r[2], "severity": r[3],
            "title": r[4], "body": r[5], "created_at": r[6], "read_at": r[7],
        })
    return out


async def mark_panel_note_read(note_id: int) -> bool:
    from app import database as db_mod

    await ensure_notes_table()
    await db_mod._shared_db.execute(  # type: ignore[union-attr]
        "UPDATE streamer_notes SET read_at = ? WHERE id = ?",
        (time.time(), note_id),
    )
    await db_mod._shared_db.commit()  # type: ignore[union-attr]
    return True


async def delete_panel_note(note_id: int) -> bool:
    from app import database as db_mod

    await ensure_notes_table()
    await db_mod._shared_db.execute("DELETE FROM streamer_notes WHERE id = ?", (note_id,))  # type: ignore[union-attr]
    await db_mod._shared_db.commit()  # type: ignore[union-attr]
    return True


# ---------- Orchestrator ----------

@dataclass
class StreamerNotifier:
    """Per-account отправщик. Хранит rate-limiter и settings."""

    settings: NotifySettings = field(default_factory=NotifySettings)
    limiter: RateLimiter = field(default_factory=RateLimiter)

    async def notify(self, account_id: int, channel: str, severity: Severity, title: str, body: str) -> dict:
        if not self.settings.severity_passes(severity):
            return {"sent": [], "reason": "severity filtered"}
        if not self.limiter.allow():
            return {"sent": [], "reason": "rate-limit"}
        sent: list[str] = []
        if self.settings.discord_webhook:
            ok = await send_discord_webhook(self.settings.discord_webhook, format_discord_payload(severity, title, body, channel))
            if ok:
                sent.append("discord")
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            ok = await send_telegram(self.settings.telegram_bot_token, self.settings.telegram_chat_id, format_telegram_text(severity, title, body, channel))
            if ok:
                sent.append("telegram")
        if self.settings.panel_enabled:
            try:
                await save_panel_note(account_id, channel, severity, title, body)
                sent.append("panel")
            except Exception as exc:
                logger.debug("panel note error: %s", exc)
        return {"sent": sent}
