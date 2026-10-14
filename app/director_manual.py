"""Q40b/Q35: ручной режим Режиссёра — оператор пишет сам и явно выбирает отправителя,
плюс текстовые заготовки с хоткеями (Q35) для быстрой отправки и общая очередь с
фиксированным темпом отправки (Q36).

В ручном режиме AI-сессия канала не запускается. Каждое сообщение отправляется
только по действию оператора: без таймеров, ротации отправителя и случайных
задержек. Текст проходит те же запреты, что и планы Режиссёра, плюс outgoing
moderation; общая экстренная остановка ставит fence и на ручной режим. Q36: несколько
отправок подряд для одного канала не уходят разом — общая очередь на канал с
фиксированным минимальным интервалом между фактическими отправками, без случайного
разброса (в отличие от Q34 — там рандомизируется вход ботов в стрим, не темп отправки).
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Awaitable, Callable

from app.database import get_db
from app.director import audit, normalize_channel
from app.director_plan import _safe_text

MODES = ("ai", "manual")
# Защита от двойного клика/Enter, а не темп отправки.
DUPLICATE_GUARD_SEC = 1.0
HISTORY_LIMIT = 50
# Q35: заготовки маппятся на хоткеи Alt+1..Alt+9 по своей позиции — больше не имеет смысла.
PRESET_LIMIT = 9
# Q36: фиксированный минимальный интервал между фактическими отправками одного канала.
SEND_RATE_LIMIT_SEC = 2.0

# per-channel FIFO: asyncio.Lock — очередь ожидающих своей очереди отправок этого канала.
_channel_locks: dict[str, asyncio.Lock] = {}
_channel_last_dispatch: dict[str, float] = {}
_channel_pending: dict[str, int] = {}


def _channel_lock(channel: str) -> asyncio.Lock:
    lock = _channel_locks.get(channel)
    if lock is None:
        lock = asyncio.Lock()
        _channel_locks[channel] = lock
    return lock


def queue_depth(channel: str) -> int:
    """Сколько ручных отправок этого канала сейчас в очереди (включая ту, что дошла до отправки)."""
    return _channel_pending.get(normalize_channel(channel), 0)

Deliver = Callable[[int, str, str], Awaitable[dict[str, Any]]]
Moderate = Callable[[int, str, str], Awaitable[tuple[bool, str]]]


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS director_control_modes (
      channel TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'ai',
      emergency_fence INTEGER NOT NULL DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS director_manual_messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, account_id INTEGER NOT NULL,
      text TEXT NOT NULL, state TEXT NOT NULL, reason TEXT, created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS director_manual_messages_channel ON director_manual_messages(channel, id);
    CREATE TABLE IF NOT EXISTS director_manual_presets (
      id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, text TEXT NOT NULL,
      position INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS director_manual_presets_channel ON director_manual_presets(channel, position);
    """)


async def _mode_row(db: Any, channel: str) -> tuple[str, bool]:
    row = await (await db.execute(
        "SELECT mode, emergency_fence FROM director_control_modes WHERE channel=?", (channel,)
    )).fetchone()
    return (row[0], bool(row[1])) if row else ("ai", False)


async def get_mode(channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        mode, fenced = await _mode_row(db, channel)
    finally:
        await db.close()
    return {"channel": channel, "mode": mode, "fenced": fenced}


async def list_modes() -> dict[str, Any]:
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute("SELECT channel, mode, emergency_fence FROM director_control_modes")).fetchall()
    finally:
        await db.close()
    return {"ok": True, "modes": {row[0]: {"mode": row[1], "fenced": bool(row[2])} for row in rows}}


async def set_mode(channel: str, mode: Any) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if mode not in MODES:
        raise ValueError("invalid_control_mode")
    db = await get_db()
    try:
        await ensure_schema(db)
        await db.execute("BEGIN IMMEDIATE")
        # Переключение только при остановленной AI-сессии — как правка конфига.
        active = await (await db.execute(
            "SELECT 1 FROM director_sessions WHERE channel=? AND state != 'stopped'", (channel,)
        )).fetchone()
        if active:
            raise ValueError("settings_locked")
        await db.execute(
            "INSERT INTO director_control_modes(channel, mode) VALUES (?, ?) "
            "ON CONFLICT(channel) DO UPDATE SET mode=excluded.mode, updated_at=CURRENT_TIMESTAMP",
            (channel, mode),
        )
        await db.commit()
    finally:
        await db.close()
    await audit(channel, "control_mode", mode)
    return await get_mode(channel)


async def fence_all(db: Any) -> None:
    """Runs inside emergency_stop_all's transaction; manual sends stay blocked until unfenced."""
    # Без executescript: он делает неявный COMMIT посреди аварийной транзакции.
    try:
        await db.execute("UPDATE director_control_modes SET emergency_fence=1, updated_at=CURRENT_TIMESTAMP")
    except sqlite3.OperationalError:
        pass  # таблицы ещё нет — значит, и ручных каналов нет


async def unfence(channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        await db.execute("UPDATE director_control_modes SET emergency_fence=0, updated_at=CURRENT_TIMESTAMP WHERE channel=?", (channel,))
        await db.commit()
    finally:
        await db.close()
    await audit(channel, "manual_unfence", "ok")
    return await get_mode(channel)


async def _default_moderate(account_id: int, channel: str, text: str) -> tuple[bool, str]:
    from app.moderation import check_outgoing
    verdict = await check_outgoing(account_id, channel, text, source="director_manual")
    return bool(verdict.ok), verdict.text


async def _default_deliver(account_id: int, channel: str, text: str) -> dict[str, Any]:
    from app.server import bot_manager
    return await bot_manager.send_message_detailed(account_id, channel, text)


moderate: Moderate = _default_moderate
deliver: Deliver = _default_deliver


async def _record(channel: str, account_id: int, text: str, state: str, reason: str | None) -> dict[str, Any]:
    now = time.time()
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO director_manual_messages(channel, account_id, text, state, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (channel, account_id, text, state, reason, now),
        )
        await db.commit()
        message_id = cursor.lastrowid
    finally:
        await db.close()
    await audit(channel, "manual_send", state, details={"message_id": message_id, "account_id": account_id, "reason": reason})
    return {"id": message_id, "channel": channel, "account_id": account_id, "text": text, "state": state, "reason": reason, "created_at": now}


def _failed(code: str, record: dict[str, Any], params: dict | None = None) -> dict[str, Any]:
    # Панельный api() читает error.code и показывает локализованный текст.
    return {"ok": False, "error": {"code": code, "params": params or {}}, "message": record}


async def send(channel: str, account_id: Any, text: Any) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id < 1:
        raise ValueError("manual_sender_required")
    if isinstance(text, str):
        text = text.strip()
    reason = _safe_text(text)
    if reason:
        raise ValueError(f"manual_{reason}")
    # Q36: заявка встаёт в очередь канала сразу — счётчик пред отражает и время, потраченное
    # на ожидание слота, а не только на сам блок ниже.
    _channel_pending[channel] = _channel_pending.get(channel, 0) + 1
    try:
        async with _channel_lock(channel):
            wait = _channel_last_dispatch.get(channel, 0.0) + SEND_RATE_LIMIT_SEC - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            _channel_last_dispatch[channel] = time.time()

            db = await get_db()
            try:
                await ensure_schema(db)
                mode, fenced = await _mode_row(db, channel)
                if mode != "manual":
                    raise ValueError("director_manual_required")
                if fenced:
                    raise ValueError("director_manual_fenced")
                sender = await (await db.execute(
                    "SELECT 1 FROM accounts a JOIN channels c ON c.account_id=a.id "
                    "WHERE a.id=? AND a.enabled=1 AND a.bot_role='lurker' AND c.enabled=1 AND c.channel_name=?",
                    (account_id, channel),
                )).fetchone()
                if not sender:
                    raise ValueError("manual_sender_not_channel_lurker")
                last = await (await db.execute(
                    "SELECT created_at FROM director_manual_messages WHERE channel=? ORDER BY id DESC LIMIT 1", (channel,)
                )).fetchone()
                if last and time.time() - float(last[0]) < DUPLICATE_GUARD_SEC:
                    raise ValueError("manual_send_too_fast")
            finally:
                await db.close()

            ok, moderated = await moderate(account_id, channel, text)
            if not ok:
                return _failed("moderation_blocked", await _record(channel, account_id, text, "blocked", "moderation_blocked"))
            # Экстренная остановка могла прийти, пока шла модерация.
            if (await get_mode(channel))["fenced"]:
                return _failed("director_manual_fenced", await _record(channel, account_id, moderated, "blocked", "director_manual_fenced"))
            try:
                result = await deliver(account_id, channel, moderated)
            except Exception as exc:  # noqa: BLE001 — сбой транспорта фиксируем в журнале, а не роняем запрос
                result = {"ok": False, "reason": type(exc).__name__}
            state = "sent" if result.get("ok") else "error"
            reason = None if state == "sent" else str(result.get("reason") or "send_failed")
            record = await _record(channel, account_id, moderated, state, reason)
            return {"ok": True, "message": record} if state == "sent" else _failed("manual_send_failed", record, {"reason": reason})
    finally:
        _channel_pending[channel] = max(0, _channel_pending.get(channel, 1) - 1)


async def list_messages(channel: str, limit: int = 20) -> dict[str, Any]:
    channel = normalize_channel(channel)
    limit = max(1, min(int(limit), HISTORY_LIMIT))
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute(
            "SELECT m.id, m.account_id, a.nickname, m.text, m.state, m.reason, m.created_at FROM director_manual_messages m "
            "LEFT JOIN accounts a ON a.id=m.account_id WHERE m.channel=? ORDER BY m.id DESC LIMIT ?",
            (channel, limit),
        )).fetchall()
    finally:
        await db.close()
    keys = ("id", "account_id", "nickname", "text", "state", "reason", "created_at")
    return {"ok": True, "channel": channel, "messages": [dict(zip(keys, row)) for row in rows]}


# ── Q35: заготовки (пресеты) с хоткеями Alt+1..Alt+9 по позиции ──

async def list_presets(channel: str) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute(
            "SELECT id, text, position FROM director_manual_presets WHERE channel=? ORDER BY position", (channel,)
        )).fetchall()
    finally:
        await db.close()
    return {"ok": True, "channel": channel, "presets": [{"id": r[0], "text": r[1], "position": r[2]} for r in rows]}


async def create_preset(channel: str, text: Any) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if isinstance(text, str):
        text = text.strip()
    reason = _safe_text(text)
    if reason:
        raise ValueError(f"manual_{reason}")
    now = time.time()
    db = await get_db()
    try:
        await ensure_schema(db)
        count, next_pos = await (await db.execute(
            "SELECT COUNT(*), COALESCE(MAX(position), -1) + 1 FROM director_manual_presets WHERE channel=?", (channel,)
        )).fetchone()
        if count >= PRESET_LIMIT:
            raise ValueError("manual_preset_limit_reached")
        await db.execute(
            "INSERT INTO director_manual_presets(channel, text, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (channel, text, next_pos, now, now),
        )
        await db.commit()
    finally:
        await db.close()
    await audit(channel, "manual_preset_create", "ok")
    return await list_presets(channel)


async def _own_preset(db: Any, channel: str, preset_id: Any) -> int:
    if isinstance(preset_id, bool) or not isinstance(preset_id, int):
        raise ValueError("manual_preset_not_found")
    row = await (await db.execute(
        "SELECT id FROM director_manual_presets WHERE id=? AND channel=?", (preset_id, channel)
    )).fetchone()
    if not row:
        raise ValueError("manual_preset_not_found")
    return row[0]


async def update_preset(channel: str, preset_id: Any, text: Any) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if isinstance(text, str):
        text = text.strip()
    reason = _safe_text(text)
    if reason:
        raise ValueError(f"manual_{reason}")
    db = await get_db()
    try:
        await ensure_schema(db)
        await _own_preset(db, channel, preset_id)
        await db.execute(
            "UPDATE director_manual_presets SET text=?, updated_at=? WHERE id=?", (text, time.time(), preset_id)
        )
        await db.commit()
    finally:
        await db.close()
    await audit(channel, "manual_preset_update", "ok", details={"preset_id": preset_id})
    return await list_presets(channel)


async def delete_preset(channel: str, preset_id: Any) -> dict[str, Any]:
    channel = normalize_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        await _own_preset(db, channel, preset_id)
        await db.execute("DELETE FROM director_manual_presets WHERE id=?", (preset_id,))
        await db.commit()
    finally:
        await db.close()
    await audit(channel, "manual_preset_delete", "ok", details={"preset_id": preset_id})
    return await list_presets(channel)


async def reorder_presets(channel: str, order: Any) -> dict[str, Any]:
    channel = normalize_channel(channel)
    if not isinstance(order, list) or not order:
        raise ValueError("manual_preset_order_invalid")
    db = await get_db()
    try:
        await ensure_schema(db)
        rows = await (await db.execute(
            "SELECT id FROM director_manual_presets WHERE channel=?", (channel,)
        )).fetchall()
        existing = {row[0] for row in rows}
        ids = [int(i) for i in order if not isinstance(i, bool)]
        if set(ids) != existing or len(ids) != len(existing):
            raise ValueError("manual_preset_order_invalid")
        await db.execute("BEGIN IMMEDIATE")
        for position, preset_id in enumerate(ids):
            await db.execute(
                "UPDATE director_manual_presets SET position=?, updated_at=? WHERE id=? AND channel=?",
                (position, time.time(), preset_id, channel),
            )
        await db.commit()
    finally:
        await db.close()
    await audit(channel, "manual_preset_reorder", "ok")
    return await list_presets(channel)
