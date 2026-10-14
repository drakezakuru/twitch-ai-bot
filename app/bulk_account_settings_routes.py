"""Q39: массовое применение одной настройки сразу к большому числу ботов/аккаунтов.

По аналогии с пачками ботов (Q34) — берём уже выбранный на панели набор account_id
и применяем одно и то же значение поля ко всем сразу, с отчётом по каждому боту.

Явно НЕ делает авто-подгонку числа аккаунтов под число зрителей (исключено из
исходного списка владельца) — только применение значения к явно выбранным ботам.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.bot_roles import VALID_ROLES
from app.database import get_db
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["bulk-account-settings"])

# Белый список полей, которые можно применить массово, и их типы значений.
_BOOL_FIELDS = ("enabled", "observation_only", "eventsub_enabled")
_MAX_IDS = 500


def _coerce_value(field: str, value: Any) -> tuple[bool, Any, str | None]:
    if field in _BOOL_FIELDS:
        if isinstance(value, bool):
            return True, value, None
        return False, None, "invalid_value"
    if field == "bot_role":
        role = str(value or "").strip()
        if role not in VALID_ROLES:
            return False, None, "invalid_value"
        return True, role, None
    return False, None, "unknown_field"


async def _account_names(db: Any, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    cursor = await db.execute(f"SELECT id, nickname FROM accounts WHERE id IN ({placeholders})", ids)
    return {row["id"]: row["nickname"] for row in await cursor.fetchall()}


@router.post("/api/bulk/account-settings")
async def bulk_account_settings(data: dict[str, Any]) -> dict[str, Any]:
    field = str(data.get("field") or "").strip()
    ids_raw = data.get("ids")
    if not isinstance(ids_raw, list) or not ids_raw:
        return {"ok": False, "error": "ids_required"}
    try:
        ids = [int(item) for item in ids_raw]
    except (TypeError, ValueError):
        return {"ok": False, "error": "ids_invalid"}
    ids = list(dict.fromkeys(ids))[:_MAX_IDS]
    ok, value, error = _coerce_value(field, data.get("value"))
    if not ok:
        return {"ok": False, "error": error or "invalid_value"}

    db = await get_db()
    try:
        names = await _account_names(db, ids)
    finally:
        await db.close()

    results: list[dict[str, Any]] = []
    if field == "bot_role":
        from app.role_routes import bulk_set_role
        for account_id in ids:
            if account_id not in names:
                results.append({"account_id": account_id, "nickname": f"#{account_id}", "ok": False, "reason": "not_found"})
                continue
            outcome = await bulk_set_role(account_id, value)
            results.append({
                "account_id": account_id, "nickname": names.get(account_id, f"#{account_id}"),
                "ok": outcome.get("ok", False), "reason": outcome.get("reason"),
            })
    else:
        from app.routes import update_account
        for account_id in ids:
            if account_id not in names:
                results.append({"account_id": account_id, "nickname": f"#{account_id}", "ok": False, "reason": "not_found"})
                continue
            row = await update_account(account_id, {field: value})
            ok_item = bool(row and row.get("id") == account_id)
            results.append({
                "account_id": account_id, "nickname": names.get(account_id, f"#{account_id}"),
                "ok": ok_item, "reason": None if ok_item else "update_failed",
            })

    updated = sum(1 for item in results if item["ok"])
    try:
        from app.routes import log_action
        await log_action("bulk_account_settings", f"field={field} value={value!r} ids={len(ids)} ok={updated}")
    except Exception:
        pass
    return {"ok": True, "field": field, "value": value, "updated": updated, "total": len(ids), "results": results}
