"""Эндпоинты для получения сводного мини-досье зрителя (1 клик).

Агрегирует историю сообщений, статус модерации, факты памяти ботов и взаимоотношения.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends

from app.database import get_db
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["viewer-dossier"])


@router.get("/api/viewers/{channel}/{username}/dossier")
async def get_viewer_dossier(channel: str, username: str) -> dict[str, Any]:
    """Возвращает агрегированное мини-досье зрителя в канале."""
    channel_clean = channel.strip().lower().lstrip("#")
    username_clean = username.strip().lower()

    if not channel_clean or not username_clean:
        return {"ok": False, "error": "channel and username required"}

    db = await get_db()
    try:
        # 1. Статистика сообщений в chat_log
        cur = await db.execute(
            "SELECT COUNT(*) as msg_count, MIN(timestamp) as first_seen, MAX(timestamp) as last_seen "
            "FROM chat_log WHERE LOWER(channel) = ? AND LOWER(author) = ?",
            (channel_clean, username_clean),
        )
        row = await cur.fetchone()
        total_messages = int(row["msg_count"]) if row and row["msg_count"] else 0
        first_seen = row["first_seen"] if row else None
        last_seen = row["last_seen"] if row else None

        # Последние 5 сообщений
        cur = await db.execute(
            "SELECT message as text, timestamp FROM chat_log "
            "WHERE LOWER(channel) = ? AND LOWER(author) = ? ORDER BY id DESC LIMIT 5",
            (channel_clean, username_clean),
        )
        recent_messages = [dict(r) for r in await cur.fetchall()]

        # 2. Статус в белом списке (moderation_protected)
        cur = await db.execute(
            "SELECT note, created_at FROM moderation_protected "
            "WHERE LOWER(channel) = ? AND LOWER(username) = ? LIMIT 1",
            (channel_clean, username_clean),
        )
        prot_row = await cur.fetchone()
        is_protected = prot_row is not None
        protected_note = prot_row["note"] if prot_row else ""

        # 3. Последнее наказание и история из moderation_journal
        cur = await db.execute(
            "SELECT id, action, severity, rule_name, duration_sec, status, detail, created_at "
            "FROM moderation_journal "
            "WHERE LOWER(channel) = ? AND LOWER(username) = ? AND action IN ('ban', 'timeout') "
            "ORDER BY id DESC LIMIT 1",
            (channel_clean, username_clean),
        )
        last_punish_row = await cur.fetchone()
        last_punish = dict(last_punish_row) if last_punish_row else None

        cur = await db.execute(
            "SELECT id, category, severity, rule_name, action, duration_sec, status, detail, created_at "
            "FROM moderation_journal "
            "WHERE LOWER(channel) = ? AND LOWER(username) = ? "
            "ORDER BY id DESC LIMIT 10",
            (channel_clean, username_clean),
        )
        mod_history = [dict(r) for r in await cur.fetchall()]

        # 4. Память ботов (user_memory)
        cur = await db.execute(
            "SELECT um.account_id, a.nickname, um.facts, um.msg_count, um.last_seen "
            "FROM user_memory um "
            "LEFT JOIN accounts a ON a.id = um.account_id "
            "WHERE LOWER(um.username) = ?",
            (username_clean,),
        )
        mem_rows = await cur.fetchall()
        memory_data = []
        for r in mem_rows:
            facts_raw = r["facts"] or ""
            facts_list = []
            if facts_raw.startswith("["):
                try:
                    parsed = json.loads(facts_raw)
                    if isinstance(parsed, list):
                        facts_list = [str(f.get("text", f) if isinstance(f, dict) else f) for f in parsed]
                    else:
                        facts_list = [str(parsed)]
                except Exception:
                    facts_list = [facts_raw]
            else:
                facts_list = [f.strip() for f in facts_raw.splitlines() if f.strip()]
            memory_data.append({
                "account_id": r["account_id"],
                "bot_nickname": r["nickname"] or f"Бот #{r['account_id']}",
                "facts": facts_list,
                "msg_count": r["msg_count"],
                "last_seen": r["last_seen"],
            })

        # 5. Отношение ботов к зрителю (bot_affinity) если таблица существует
        affinities = []
        try:
            cur = await db.execute(
                "SELECT ba.account_id, a.nickname, ba.affinity_score, ba.affinity_level "
                "FROM bot_affinity ba "
                "LEFT JOIN accounts a ON a.id = ba.account_id "
                "WHERE LOWER(ba.username) = ?",
                (username_clean,),
            )
            affinities = [dict(r) for r in await cur.fetchall()]
        except Exception:
            pass

        return {
            "ok": True,
            "channel": channel_clean,
            "username": username_clean,
            "stats": {
                "total_messages": total_messages,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "recent_messages": recent_messages,
            },
            "status": {
                "is_protected": is_protected,
                "protected_note": protected_note,
                "last_punish": last_punish,
            },
            "moderation_history": mod_history,
            "bot_memories": memory_data,
            "affinities": affinities,
        }
    finally:
        await db.close()
