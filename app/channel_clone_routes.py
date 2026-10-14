"""Эндпоинт клонирования / копирования настроек между Twitch-каналами.

Позволяет скопировать:
- Базу правил модерации канала (таблица moderation_channel_rules)
- Запретные темы (banned_topics:<channel>)
- Разрешённые темы (allowed_topics:<channel>)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from app.database import get_db, get_setting, set_setting
from app.routes import log_action
from app.channel_bans import normalize_channel as norm_chan, channel_key as bans_key
from app.channel_allowed import channel_allowed_key as allowed_key

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/channels/clone-settings")
async def clone_channel_settings(data: dict[str, Any]) -> dict:
    from_ch = norm_chan(data.get("from_channel") or "")
    to_ch = norm_chan(data.get("to_channel") or "")

    if not from_ch:
        return {"ok": False, "error": "Не указан исходный канал (from_channel)"}
    if not to_ch:
        return {"ok": False, "error": "Не указан целевой канал (to_channel)"}
    if from_ch == to_ch:
        return {"ok": False, "error": "Исходный и целевой каналы совпадают"}

    copy_rules = bool(data.get("copy_rules", True))
    copy_bans = bool(data.get("copy_bans", True))
    copy_allowed = bool(data.get("copy_allowed", True))

    rules_copied = 0
    bans_copied = False
    allowed_copied = False

    db = await get_db()
    try:
        if copy_rules:
            # Читаем правила исходного канала
            cur = await db.execute(
                "SELECT pattern, category, action, severity, action_ext, enabled "
                "FROM moderation_channel_rules WHERE channel = ?",
                (from_ch,),
            )
            rows = await cur.fetchall()
            for r in rows:
                await db.execute(
                    "INSERT OR IGNORE INTO moderation_channel_rules "
                    "(channel, pattern, category, action, severity, action_ext, enabled) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (to_ch, r["pattern"], r["category"], r["action"], r["severity"], r["action_ext"], r["enabled"]),
                )
                rules_copied += 1
            await db.commit()
            try:
                from app import moderation as _mod
                _mod.invalidate_cache()
            except Exception:
                pass

        if copy_bans:
            src_bans = await get_setting(bans_key(from_ch), "")
            if src_bans:
                await set_setting(bans_key(to_ch), src_bans)
                bans_copied = True

        if copy_allowed:
            src_allowed = await get_setting(allowed_key(from_ch), "")
            if src_allowed:
                await set_setting(allowed_key(to_ch), src_allowed)
                allowed_copied = True

        await log_action(
            "channel_clone_settings",
            f"из #{from_ch} в #{to_ch}: правил={rules_copied}, bans={bans_copied}, allowed={allowed_copied}",
        )
    finally:
        await db.close()

    return {
        "ok": True,
        "from_channel": from_ch,
        "to_channel": to_ch,
        "rules_copied": rules_copied,
        "bans_copied": bans_copied,
        "allowed_copied": allowed_copied,
    }
