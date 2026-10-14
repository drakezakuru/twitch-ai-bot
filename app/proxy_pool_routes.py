"""API-эндпоинты для управления общим пулом прокси (Proxy Pool)."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends

from app.proxy_pool import (
    add_proxies_to_pool,
    check_all_proxies_pool,
    check_single_proxy_health,
    claim_proxy_for_bot,
    clean_dead_proxies_from_pool,
    clean_duplicate_proxies_from_pool,
    clean_slow_proxies_from_pool,
    delete_proxy_from_pool,
    get_proxy_pool_items,
    get_proxy_pool_settings,
    release_proxy_for_bot,
    save_proxy_pool_settings,
)
from app.routes import log_action
from app.security import auth_dependency

router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["proxy-pool"])


@router.get("/api/proxy-pool")
async def get_proxy_pool() -> dict[str, Any]:
    """Возвращает весь список прокси пула и статистику."""
    items = await get_proxy_pool_items()
    total = len(items)
    assigned = sum(1 for x in items if x["is_assigned"])
    available = sum(1 for x in items if not x["is_assigned"] and x["status"] != "error")
    dead = sum(1 for x in items if x["status"] == "error")

    return {
        "ok": True,
        "items": items,
        "stats": {
            "total": total,
            "assigned": assigned,
            "available": available,
            "dead": dead,
        },
    }


@router.post("/api/proxy-pool/add")
async def add_proxies(data: dict[str, Any]) -> dict[str, Any]:
    """Массовое добавление прокси в пул."""
    raw_text = str(data.get("proxies_text") or data.get("text") or "")
    proto = str(data.get("default_protocol") or data.get("protocol") or "http")
    label = str(data.get("label") or "").strip()

    res = await add_proxies_to_pool(raw_text, proto, label)
    if res.get("ok"):
        await log_action("Пул прокси", f"Добавлено {res.get('added')} прокси, дублей: {res.get('duplicates')}")
    return res


@router.post("/api/proxy-pool/{proxy_id}/check")
async def check_proxy(proxy_id: int) -> dict[str, Any]:
    """Проверка одного прокси."""
    return await check_single_proxy_health(proxy_id)


@router.post("/api/proxy-pool/check-all")
async def check_all_proxies() -> dict[str, Any]:
    """Массовая проверка всех прокси в пуле."""
    res = await check_all_proxies_pool()
    counts = res.get("counts") or {}
    await log_action("Проверка пула прокси", f"ok={counts.get('ok', 0)} slow={counts.get('slow', 0)} error={counts.get('error', 0)}")
    return res


@router.delete("/api/proxy-pool/{proxy_id}")
@router.delete("/api/proxy-pool/{proxy_id}/delete")
@router.post("/api/proxy-pool/{proxy_id}/delete")
async def delete_proxy(proxy_id: int) -> dict[str, Any]:
    """Удаление прокси из пула."""
    ok = await delete_proxy_from_pool(proxy_id)
    await log_action("Пул прокси", f"Удален прокси #{proxy_id}")
    return {"ok": ok}


@router.post("/api/proxy-pool/clean-dead")
async def clean_dead_proxies() -> dict[str, Any]:
    """Удаляет все нерабочие прокси из пула."""
    count = await clean_dead_proxies_from_pool()
    await log_action("Очистка пула прокси", f"Удалено {count} нерабочих прокси")
    return {"ok": True, "deleted": count}


@router.post("/api/proxy-pool/clean-slow")
async def clean_slow_proxies(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Удаляет из пула все медленные прокси (latency_ms >= max_ping_ms) и ошибки."""
    d = data or {}
    max_ms = float(d.get("max_ping_ms") or 2000.0)
    count = await clean_slow_proxies_from_pool(max_ms)
    await log_action("Очистка пула прокси", f"Удалено {count} медленных/ошибочных прокси (> {max_ms:.0f} мс)")
    return {"ok": True, "deleted": count, "max_ping_ms": max_ms}


@router.post("/api/proxy-pool/clean-duplicates")
async def clean_duplicate_proxies() -> dict[str, Any]:
    """Удаляет повторяющиеся прокси из пула (сохраняя один наилучший)."""
    res = await clean_duplicate_proxies_from_pool()
    deleted = res.get("deleted", 0)
    await log_action("Очистка пула прокси", f"Удалено {deleted} повторок/дубликатов (осталось {res.get('unique_remaining', 0)} уникальных)")
    return {"ok": True, "deleted": deleted, "unique_remaining": res.get("unique_remaining", 0)}


@router.post("/api/accounts/{account_id}/claim-proxy")
async def claim_proxy(account_id: int, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Столбит прокси за ботом (автовыбор из свободных или конкретный proxy_id)."""
    d = data or {}
    proxy_id = int(d.get("proxy_id") or 0)
    res = await claim_proxy_for_bot(account_id, proxy_id if proxy_id > 0 else None)
    if res.get("ok"):
        await log_action("Привязка прокси", f"Бот #{account_id} ({res.get('nickname')}) застолбил прокси {res.get('masked_url')}")
    return res


@router.post("/api/accounts/{account_id}/release-proxy")
async def release_proxy(account_id: int) -> dict[str, Any]:
    """Отвязывает прокси от бота и возвращает его в свободный пул."""
    res = await release_proxy_for_bot(account_id)
    await log_action("Отвязка прокси", f"Бот #{account_id} освободил прокси")
    return res


@router.post("/api/accounts/bulk-claim-proxies")
async def bulk_claim_proxies(data: dict[str, Any]) -> dict[str, Any]:
    """Массовая раздача свободных прокси выбранным чекбоксами ботам."""
    raw_ids = data.get("account_ids") or data.get("ids") or []
    account_ids = [int(x) for x in raw_ids if int(x) > 0]
    if not account_ids:
        return {"ok": False, "error": "Не выбраны боты"}

    claimed = []
    failed = []

    for aid in account_ids:
        r = await claim_proxy_for_bot(aid)
        if r.get("ok"):
            claimed.append({"account_id": aid, "nickname": r.get("nickname"), "masked_url": r.get("masked_url")})
        else:
            failed.append({"account_id": aid, "reason": r.get("error")})

    await log_action("Массовая раздача прокси", f"Успешно: {len(claimed)}, без прокси: {len(failed)}")
    return {
        "ok": True,
        "claimed_count": len(claimed),
        "failed_count": len(failed),
        "claimed": claimed,
        "failed": failed,
    }


@router.post("/api/accounts/claim-proxies-for-active")
async def claim_proxies_for_active() -> dict[str, Any]:
    """Массовая раздача свободных прокси только включенным активным ботам (enabled=1).

    Боты, которые выключены (которых владелец не хочет юзать, например 5, 6), пропускаются.
    """
    from app.database import get_db
    db = await get_db()
    active_ids: list[int] = []
    try:
        cur = await db.execute("SELECT id, nickname, proxy FROM accounts WHERE enabled = 1")
        rows = await cur.fetchall()
        active_ids = [int(r["id"]) for r in rows]
    finally:
        await db.close()

    if not active_ids:
        return {"ok": False, "error": "Нет включенных активных ботов (все выключены)"}

    claimed = []
    failed = []
    for aid in active_ids:
        r = await claim_proxy_for_bot(aid)
        if r.get("ok"):
            claimed.append({"account_id": aid, "nickname": r.get("nickname"), "masked_url": r.get("masked_url")})
        else:
            failed.append({"account_id": aid, "reason": r.get("error")})

    await log_action("Раздача прокси активным", f"Выдано: {len(claimed)}, без прокси: {len(failed)}")
    return {
        "ok": True,
        "active_total": len(active_ids),
        "claimed_count": len(claimed),
        "failed_count": len(failed),
        "claimed": claimed,
        "failed": failed,
    }


@router.get("/api/proxy-pool/settings")
async def get_settings() -> dict[str, Any]:
    """Возвращает настройки авто-замены и уведомлений пула."""
    return await get_proxy_pool_settings()


@router.post("/api/proxy-pool/settings")
async def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Сохраняет настройки авто-замены, авто-чистки и уведомлений."""
    auto_failover = bool(data.get("auto_failover", True))
    notify_owner = bool(data.get("notify_owner", True))
    auto_clean = bool(data.get("auto_clean", True))
    res = await save_proxy_pool_settings(auto_failover, notify_owner, auto_clean)
    await log_action("Настройки пула прокси", f"auto_failover={auto_failover}, notify_owner={notify_owner}, auto_clean={auto_clean}")
    return res
