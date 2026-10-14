"""Эндпоинты для управления флотом ботов, проверки здоровья и автоматизации каналов."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.bot_fleet import (
    ensure_schema,
    get_channel_fleet_settings,
    run_fleet_health_check,
    save_channel_fleet_settings,
)
from app.database import get_db
from app.routes import log_action
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["bot-fleet"])


@router.get("/api/channels/{channel}/fleet-settings")
async def get_fleet_settings(channel: str) -> dict[str, Any]:
    """Возвращает настройки автоматизации, квот и джиттера для канала."""
    s = await get_channel_fleet_settings(channel)
    return {"ok": True, "settings": s, **s}


@router.post("/api/channels/{channel}/fleet-settings")
async def update_fleet_settings(channel: str, data: dict[str, Any]) -> dict[str, Any]:
    """Сохраняет настройки автоматизации канала (квоты, авто-старт, джиттер)."""
    saved = await save_channel_fleet_settings(channel, data)
    await log_action("Настройки флота канала", f"#{channel} обновлены")
    return {"ok": True, "settings": saved}


@router.post("/api/accounts/health-check")
async def start_health_check(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Запускает массовую проверку здоровья токенов и прокси (Светофор: 🟢/🟡/🔴)."""
    d = data or {}
    limit = int(d.get("limit") or 150)
    account_ids = d.get("account_ids")
    res = await run_fleet_health_check(account_ids=account_ids, limit=limit)
    counts = res.get("counts") or {}
    await log_action("Проверка базы ботов", f"green={counts.get('green', 0)} yellow={counts.get('yellow', 0)} red={counts.get('red', 0)}")
    return res


_HEALTH_TO_STATUS = {
    "green": "ok",
    "yellow": "proxy_error",
    "red": "auth_error",
}
_STATUS_RU = {
    "ok": "Токен валиден, прокси в норме",
    "proxy_error": "Ошибка прокси",
    "auth_error": "Ошибка токена",
    "unknown": "Ещё не проверен",
}


@router.get("/api/accounts/health-status")
async def get_health_status() -> dict[str, Any]:
    """Возвращает закэшированные статусы здоровья ботов из БД.

    Формат тот же, что у POST /api/accounts/health-check: `statuses` — словарь
    {id_accounta: {...}}, чтобы фронт мог делать Object.assign(_botHealthStatuses, ...).
    """
    await ensure_schema()
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT a.id, a.nickname, s.token_status, s.proxy_status, s.health, s.last_checked_at, s.error_message
            FROM accounts a
            LEFT JOIN account_health_status s ON a.id = s.account_id
            ORDER BY a.id ASC
        """)
        rows = await cur.fetchall()
    finally:
        await db.close()

    results: list[dict[str, Any]] = []
    for r in rows:
        health = (r["health"] or "").strip()
        status = _HEALTH_TO_STATUS.get(health, "unknown")
        results.append({
            "account_id": r["id"],
            "nickname": r["nickname"],
            "token_status": r["token_status"] or "unknown",
            "proxy_status": r["proxy_status"] or "none",
            "health": health or "unknown",
            "status": status,
            "status_ru": _STATUS_RU[status],
            "error": r["error_message"] or "",
            "checked_at": r["last_checked_at"] or 0,
        })

    counts = {
        "green": sum(1 for r in results if r["health"] == "green"),
        "yellow": sum(1 for r in results if r["health"] == "yellow"),
        "red": sum(1 for r in results if r["health"] == "red"),
        "unknown": sum(1 for r in results if r["health"] == "unknown"),
        "total": len(results),
    }
    return {
        "ok": True,
        "counts": counts,
        "total": len(results),
        "statuses": {str(r["account_id"]): r for r in results},
        "results": results,
    }


@router.post("/api/accounts/bulk-action")
async def bulk_account_action(data: dict[str, Any]) -> dict[str, Any]:
    """Массовые действия над выбранными чекбоксами ботами.

    action: 'set_role' | 'add_channel' | 'remove_dead' | 'delete'
    """
    action = str(data.get("action") or "").strip()
    raw_ids = data.get("account_ids") or data.get("ids") or []
    account_ids = [int(x) for x in raw_ids if int(x) > 0]
    if not account_ids and action != "remove_dead":
        return {"ok": False, "error": "Выберите хотя бы одного бота"}

    db = await get_db()
    try:
        if action == "set_role":
            role = str(data.get("role") or "lurker").strip().lower()
            if role not in {"chatter", "lurker", "moderator", "director"}:
                return {"ok": False, "error": "Некорректная роль"}
            placeholders = ",".join("?" for _ in account_ids)
            await db.execute(f"UPDATE accounts SET bot_role = ? WHERE id IN ({placeholders})", [role] + account_ids)
            await db.commit()
            await log_action("Массовая смена роли", f"роль={role} для {len(account_ids)} ботов")
            return {"ok": True, "affected": len(account_ids)}

        elif action == "add_channel":
            channel = str(data.get("channel") or "").lower().strip().lstrip("#")
            if not channel:
                return {"ok": False, "error": "Укажите канал"}
            added = 0
            for aid in account_ids:
                try:
                    await db.execute(
                        "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
                        (aid, channel),
                    )
                    added += 1
                except Exception:
                    pass
            await db.commit()
            await log_action("Массовая привязка к каналу", f"#{channel} ← {added} ботов")
            return {"ok": True, "affected": added}

        elif action == "remove_dead":
            # Удаляет всех ботов с health == 'red' (токен протух)
            cur = await db.execute("SELECT account_id FROM account_health_status WHERE health = 'red'")
            dead_ids = [r["account_id"] for r in await cur.fetchall()]
            if not dead_ids:
                return {"ok": True, "affected": 0, "message": "Мёртвых ботов не найдено"}

            placeholders = ",".join("?" for _ in dead_ids)
            await db.execute(f"DELETE FROM accounts WHERE id IN ({placeholders})", dead_ids)
            await db.execute(f"DELETE FROM account_health_status WHERE account_id IN ({placeholders})", dead_ids)
            await db.commit()
            await log_action("Удаление мёртвых ботов", f"удалено {len(dead_ids)} аккаунтов")
            return {"ok": True, "affected": len(dead_ids)}

        elif action == "delete":
            placeholders = ",".join("?" for _ in account_ids)
            await db.execute(f"DELETE FROM accounts WHERE id IN ({placeholders})", account_ids)
            await db.execute(f"DELETE FROM account_health_status WHERE account_id IN ({placeholders})", account_ids)
            await db.commit()
            await log_action("Массовое удаление ботов", f"удалено {len(account_ids)} аккаунтов")
            return {"ok": True, "affected": len(account_ids)}

        return {"ok": False, "error": "Неизвестное действие"}
    finally:
        await db.close()
