"""Дашборд «здоровье эфира» (владелец, 27.09.2026 вечером, размер M).

Одна таблица: кто из ботов в канале подключён, кто отвечает, кто молчит и
почему — вместо чтения логов по одному боту. Это live-снимок, не журнал:
причина молчания читается из того же гейта, что решает в реальном чате
(``ChatAnalyzer._role_reply_gate``), без изменений в самом пайплайне чата —
гейт зависит только от роли/конфига аккаунта, не от конкретного сообщения.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.database import get_db

router = APIRouter()


def _friendly_reason(raw: str) -> str:
    """Причины из ``_role_reply_gate`` местами на смеси ru/en — причёсываем
    только известные фиксированные варианты, не трогая сам гейт."""
    if raw == "director account never chats":
        return "Режиссёр не пишет в чат — только наблюдает и планирует"
    if raw.startswith("moderator chat_activity="):
        activity = raw.split("=", 1)[1]
        return f"Модератор молчит (chat_activity={activity})"
    return raw


async def _last_activity(db: Any, account_id: int, channel: str) -> dict[str, str]:
    cur = await db.execute(
        "SELECT message, created_at FROM bot_logs "
        "WHERE account_id = ? AND channel = ? AND category IN ('chat', 'ai') "
        "ORDER BY id DESC LIMIT 1",
        (account_id, channel),
    )
    row = await cur.fetchone()
    if not row:
        return {"at": "", "excerpt": ""}
    return {"at": row["created_at"] or "", "excerpt": (row["message"] or "")[:120]}


@router.get("/api/stream-health")
async def stream_health(channel: str = "") -> dict[str, Any]:
    from app.server import bot_manager, chat_analyzer

    db = await get_db()
    try:
        query = (
            "SELECT c.channel_name, c.account_id, c.enabled AS binding_enabled, "
            "a.nickname, a.bot_role, a.enabled AS account_enabled, a.proxy "
            "FROM channels c JOIN accounts a ON a.id = c.account_id "
        )
        params: tuple[Any, ...] = ()
        ch_filter = channel.strip().lstrip("#").lower()
        if ch_filter:
            query += "WHERE c.channel_name = ? "
            params = (ch_filter,)
        query += "ORDER BY c.channel_name, a.nickname"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        proxy_info_map: dict[str, dict[str, Any]] = {}
        try:
            p_cur = await db.execute("SELECT url, latency_ms, status FROM proxy_pool")
            for pr in await p_cur.fetchall():
                proxy_info_map[pr["url"]] = {"latency_ms": pr["latency_ms"], "status": pr["status"]}
        except Exception:
            pass

        from app.irc.types import mask_proxy

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            ch = row["channel_name"]
            entry = grouped.setdefault(ch, {"channel": ch, "bots": []})

            account_id = row["account_id"]
            status = bot_manager.get_status(account_id)
            connected = bool(status.get("connected") and ch in (status.get("channels") or []))

            if not row["account_enabled"]:
                silent, reason = True, "бот выключен"
            elif not row["binding_enabled"]:
                silent, reason = True, "канал отключён у этого бота"
            elif not connected:
                silent, reason = True, status.get("last_error") or "не подключён"
            else:
                allowed, gate_reason = await chat_analyzer._role_reply_gate(account_id, is_mention=False)
                silent, reason = (not allowed), _friendly_reason(gate_reason)

            raw_proxy = row["proxy"] or ""
            runtime_proxy = status.get("proxy_raw") or status.get("proxy") or raw_proxy
            p_stat = proxy_info_map.get(raw_proxy) or proxy_info_map.get(runtime_proxy) or {}

            activity = await _last_activity(db, account_id, ch)
            entry["bots"].append({
                "account_id": account_id,
                "nickname": row["nickname"],
                "role": row["bot_role"] or "chatter",
                "connected": connected,
                "silent": silent,
                "reason": reason if silent else "",
                "last_activity_at": activity["at"],
                "last_activity_excerpt": activity["excerpt"],
                "proxy": mask_proxy(runtime_proxy) if runtime_proxy else "",
                "proxy_latency_ms": p_stat.get("latency_ms", 0.0),
                "proxy_status": p_stat.get("status", "none") if runtime_proxy else "none",
            })

        # Helix Live State (is_live, viewer_count, game_name, title)
        from app.routes import decrypt_token, get_channel_info, is_helix_configured

        helix_configured = is_helix_configured()
        for ch, entry in grouped.items():
            entry["is_live"] = None
            entry["viewer_count"] = 0
            entry["game_name"] = ""
            entry["title"] = ""
            if helix_configured:
                token_to_use = None
                for b in entry["bots"]:
                    aid = b["account_id"]
                    cur_t = await db.execute("SELECT token FROM accounts WHERE id = ?", (aid,))
                    row_t = await cur_t.fetchone()
                    if row_t and row_t["token"]:
                        dec = decrypt_token(row_t["token"])
                        if dec:
                            token_to_use = dec
                            break
                if token_to_use:
                    try:
                        info = await get_channel_info(ch, token_to_use)
                        if info:
                            entry["is_live"] = bool(info.get("is_live"))
                            entry["viewer_count"] = info.get("viewer_count", 0)
                            entry["game_name"] = info.get("game_name", "")
                            entry["title"] = info.get("title", "")
                        else:
                            entry["is_live"] = False
                    except Exception:
                        entry["is_live"] = None
    finally:
        await db.close()

    return {"channels": list(grouped.values())}