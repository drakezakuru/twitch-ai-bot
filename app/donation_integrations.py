"""§11.4 WIDGETS_PLAN: интеграции с реальными донат-платформами.

* **DonatePay** — polling ``GET https://donatepay.ru/api/v2/notifications``
  c ``access_token``, раз в ~30с; дедуп по id уведомления.
* **DonateX** (donatex.gg) — polling ``GET /api/v1/donations`` с external-токеном,
  раз в ~30с; дедуп по uuid + пропуск донатов «до старта» и тестовых.
* **DonationAlerts** — Centrifugo WebSocket
  (``wss://centrifugo.donationalerts.com/connection/websocket``) c access-token.
  Подключение best-effort: если библиотека/сеть недоступны — цикл переподключается.

Все донаты идут в ``app.widgets.on_donation_event`` (топ донатеров,
donation-challenges), ``on_stream_event("donation", ...)`` (recent-events ticker)
и ``widget_bus.duck_start("donation")`` (авто-молчание TTS, §3).

Настройки (платформа/токен/вкл) — панель, вкладка «Виджеты»,
роуты в ``app/widgets.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DONATEPAY_URL = "https://donatepay.ru/api/v2/notifications"
_DA_WS_URL = "wss://centrifugo.donationalerts.com/connection/websocket"
_DONATEX_URL = "https://donatex.gg/api/v1/donations"
# Публичный роут целей (по докам donatex.gg/api-docs: GET /api/goals/:goalId)
_DONATEX_GOAL_URL = "https://donatex.gg/api/goals/"

# Состояние в памяти процесса: последний увиденный id (DonatePay) и статусы.
_last_donatepay_id = 0
_last_donatepay_scoped: dict[tuple[int, str], int] = {}
_last_status: dict[tuple[int, str, str], dict] = {}


def _settings_scope(settings: dict) -> tuple[int, str] | None:
    account_id = int(settings.get("account_id") or 0)
    channel = str(settings.get("channel") or "")
    return (account_id, channel) if account_id > 0 and channel else None


def _status_key(platform: str, scope: tuple[int, str] | None = None) -> tuple[int, str, str]:
    return (scope[0], scope[1], platform) if scope else (0, "", platform)


def _set_status(
    platform: str, ok: bool, state: str, scope: tuple[int, str] | None = None,
) -> None:
    previous = _last_status.get(_status_key(platform, scope), {})
    _last_status[_status_key(platform, scope)] = {
        "ok": ok,
        "state": state,
        "detail": state,
        "at": time.time(),
        "last_success_at": (
            datetime.now(timezone.utc).isoformat() if ok
            else previous.get("last_success_at")
        ),
    }


async def _record_provider_success(
    platform: str, scope: tuple[int, str] | None,
) -> None:
    from app.database import get_db

    db = await get_db()
    try:
        if scope is None:
            await db.execute(
                "UPDATE donation_integrations SET last_success_at = CURRENT_TIMESTAMP "
                "WHERE platform = ?", (platform,),
            )
        else:
            await db.execute(
                "UPDATE donation_integrations_scoped SET last_success_at = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND channel = ? AND platform = ?",
                (*scope, platform),
            )
        await db.commit()
    finally:
        await db.close()


async def get_platform_settings(
    platform: str, scope: tuple[int, str] | None = None,
) -> dict:
    """Настройки конкретной платформы: {platform, token, enabled}."""
    from app.widgets import _get_donation_integration_row
    return await _get_donation_integration_row(platform, scope)


def _receipt_scope(
    account_id: int | None, channel: str | None,
) -> tuple[int, str]:
    normalized_account_id = int(account_id or 0)
    if normalized_account_id <= 0:
        return (0, "")
    return (normalized_account_id, str(channel or "").strip().lower().lstrip("#"))


async def _claim_donation_event(
    platform: str, event_id: str, *,
    account_id: int | None, channel: str | None,
) -> bool:
    """Atomically claim a stable provider event before applying side effects."""
    event_id = str(event_id or "").strip()
    if not event_id:
        return False
    from app.database import get_db

    scope = _receipt_scope(account_id, channel)
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO donation_ingress_receipts "
            "(account_id, channel, source, event_id) VALUES (?, ?, ?, ?)",
            (*scope, platform, event_id),
        )
        await db.commit()
        return cursor.rowcount == 1
    finally:
        await db.close()


async def _release_donation_event(
    platform: str, event_id: str, *,
    account_id: int | None, channel: str | None,
) -> None:
    event_id = str(event_id or "").strip()
    if not event_id:
        return
    from app.database import get_db

    scope = _receipt_scope(account_id, channel)
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM donation_ingress_receipts "
            "WHERE account_id = ? AND channel = ? AND source = ? AND event_id = ?",
            (*scope, platform, event_id),
        )
        await db.commit()
    finally:
        await db.close()


async def _process_donation(platform: str, username: str, amount: float,
                            currency: str, message: str, *,
                            account_id: int | None = None,
                            channel: str | None = None,
                            event_id: str = "") -> bool | None:
    """§3 PLAN_FEEDBACK_2908: все платформы проходят через единый хук
    widgets.on_donation_received (топ донатеров, челленджи, recent-events)."""
    claimed = await _claim_donation_event(
        platform, event_id, account_id=account_id, channel=channel,
    )
    if not claimed:
        return False
    from app.widgets import on_donation_received
    try:
        await on_donation_received(
            platform, username, amount, currency, message,
            account_id=account_id, channel=channel,
        )
    except Exception as exc:
        await _release_donation_event(
            platform, event_id, account_id=account_id, channel=channel,
        )
        logger.warning("[donations] process failed: %s", exc)
        return None
    try:
        from app.song_request_service import handle_donation
        await handle_donation(
            account_id, channel, platform=platform, event_id=event_id,
            username=username, amount=amount, currency=currency, message=message,
        )
    except Exception as exc:
        logger.warning("[donations] song request entitlement failed: %s", exc)
    try:
        from app.widget_bus import duck_start
        await duck_start(source="donation", channel=channel, reason="donation")
    except Exception:
        pass
    logger.info("[donations] %s: %s: %.2f %s", platform, username, amount, currency)
    return True


# ── DonatePay ────────────────────────────────────────────────────

def _extract_items(data: dict) -> list[dict]:
    """DonatePay отдаёт список уведомлений в разных местах в зависимости от
    версии API: data.list / data.data / list / data — проверяем все пути."""
    if not isinstance(data, dict):
        return []
    for candidate in (
        data.get("list"),
        (data.get("data") or {}).get("list") if isinstance(data.get("data"), dict) else None,
        data.get("data") if isinstance(data.get("data"), list) else None,
        data if isinstance(data.get("data"), list) else None,
    ):
        if isinstance(candidate, list):
            return [x for x in candidate if isinstance(x, dict)]
    return []


async def poll_donatepay_once(settings: dict) -> int:
    """Один опрос DonatePay. Возвращает число обработанных донатов."""
    global _last_donatepay_id
    scope = _settings_scope(settings)
    token = (settings.get("token") or "").strip()
    if not token:
        return 0
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(_DONATEPAY_URL, params={"access_token": token})
        if resp.status_code != 200:
            raise RuntimeError(f"donatepay http {resp.status_code}")
        data = resp.json()
    items = _extract_items(data)
    processed = 0
    for item in items:
        try:
            nid = int(item.get("id") or 0)
        except (TypeError, ValueError):
            continue
        last_id = _last_donatepay_id if scope is None else _last_donatepay_scoped.get(scope, 0)
        if nid <= last_id:
            continue
        try:
            amount = float(item.get("sum") or item.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            if scope is None:
                _last_donatepay_id = nid
            else:
                _last_donatepay_scoped[scope] = nid
            continue
        processed_now = await _process_donation(
            "donatepay",
            str(item.get("name") or item.get("username") or "anonymous")[:100],
            amount,
            str(item.get("currency") or "RUB")[:10],
            str(item.get("comment") or item.get("message") or "")[:500],
            account_id=settings.get("account_id"), channel=settings.get("channel"),
            event_id=str(nid),
        )
        if processed_now is not None:
            if scope is None:
                _last_donatepay_id = nid
            else:
                _last_donatepay_scoped[scope] = nid
        processed += int(processed_now is True)
    return processed


async def donatepay_loop(settings: dict) -> None:
    scope = _settings_scope(settings)
    while True:
        try:
            fresh = await get_platform_settings("donatepay", scope)
            fresh.update({"account_id": scope[0], "channel": scope[1]} if scope else {})
            if not fresh.get("enabled") or not (fresh.get("token") or "").strip():
                _set_status("donatepay", False, "disabled", scope)
                return  # выключена — dispatcher поднимет при включении
            n = await poll_donatepay_once(fresh)
            _set_status("donatepay", True, "polling", scope)
            await _record_provider_success("donatepay", scope)
        except Exception as exc:
            _set_status("donatepay", False, "retrying", scope)
            logger.debug("[donatepay] poll failed: %s", exc)
        await asyncio.sleep(30)


# ── DonateX (donatex.gg) ─────────────────────────────────────────
# По докам https://donatex.gg/api-docs: external-токен (один стример),
# polling GET /api/v1/donations (skip/take/sortOrder, token в query).
# Дедуп по uuid + пропуск тестовых и донатов «до старта» (после рестарта
# последние 20 не переобрабатываются повторно).

_seen_donatex: set[str] = set()
_seen_donatex_scoped: dict[tuple[int, str], set[str]] = {}
_donatex_started_at = None


def _extract_donatex(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        return []
    for key in ("donations", "items", "data"):
        if isinstance(data.get(key), list):
            return [x for x in data[key] if isinstance(x, dict)]
    return []


async def poll_donatex_once(settings: dict) -> int:
    """Один опрос DonateX. Возвращает число обработанных донатов."""
    global _donatex_started_at
    import datetime as _dt
    token = (settings.get("token") or "").strip()
    if not token:
        return 0
    if _donatex_started_at is None:
        # окно «до старта» — не переобрабатываем старые донаты после рестарта
        _donatex_started_at = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            _DONATEX_URL,
            params={"skip": 0, "take": 20, "sortOrder": "NewestFirst", "token": token},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"donatex http {resp.status_code}")
        data = resp.json()
    processed = 0
    scope = _settings_scope(settings)
    seen = _seen_donatex if scope is None else _seen_donatex_scoped.setdefault(scope, set())
    for item in _extract_donatex(data):
        donation_id = str(item.get("uuid") or item.get("id") or "").strip()
        if not donation_id or donation_id in seen:
            continue
        try:
            amount = float(item.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0 or item.get("isTest"):
            continue
        ts = str(item.get("timestamp") or "")
        try:
            when = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=_dt.timezone.utc)
            if when < _donatex_started_at:
                continue
        except ValueError:
            pass
        processed_now = await _process_donation(
            "donatex",
            str(item.get("username") or "anonymous")[:100],
            amount,
            str(item.get("currency") or "RUB")[:10],
            str(item.get("message") or "")[:500],
            account_id=settings.get("account_id"), channel=settings.get("channel"),
            event_id=donation_id,
        )
        if processed_now is not None:
            seen.add(donation_id)
            if len(seen) > 2000:
                seen.clear()
                seen.add(donation_id)
        processed += int(processed_now is True)
    return processed


async def donatex_loop(settings: dict) -> None:
    scope = _settings_scope(settings)
    while True:
        try:
            fresh = await get_platform_settings("donatex", scope)
            fresh.update({"account_id": scope[0], "channel": scope[1]} if scope else {})
            if not fresh.get("enabled") or not (fresh.get("token") or "").strip():
                _set_status("donatex", False, "disabled", scope)
                return
            n = await poll_donatex_once(fresh)
            _set_status("donatex", True, "polling", scope)
            await _record_provider_success("donatex", scope)
        except Exception as exc:
            _set_status("donatex", False, "retrying", scope)
            logger.debug("[donatex] poll failed: %s", exc)
        await asyncio.sleep(30)


# ── DonationAlerts (Centrifugo) ──────────────────────────────────

async def donationalerts_loop(settings: dict) -> None:
    """Centrifugo WS: connect → subscribe $donation_alerts → слушаем донаты.

    Переподключается с backoff; при смене настроек в панели — мягкий выход.
    """
    import websockets  # уже в requirements.txt (EventSub WS)

    scope = _settings_scope(settings)
    while True:
        fresh = await get_platform_settings("donationalerts", scope)
        if not fresh.get("enabled") or not (fresh.get("token") or "").strip():
            _set_status("donationalerts", False, "disabled", scope)
            return
        token = (fresh.get("token") or "").strip()
        if not token:
            _set_status("donationalerts", False, "no token", scope)
            await asyncio.sleep(30)
            continue
        try:
            async with websockets.connect(_DA_WS_URL) as ws:
                await ws.send(json.dumps({"method": "connect", "params": {
                    "token": token, "client": "twitch-ai-bot"}}))
                await ws.send(json.dumps({"method": "subscribe", "params": {
                    "channel": "$donation_alerts"}}))
                _set_status("donationalerts", True, "connected", scope)
                await _record_provider_success("donationalerts", scope)
                logger.info("[donationalerts] connected")
                async for raw in ws:
                    await _da_handle_message(raw, scope)
        except Exception as exc:
            _set_status("donationalerts", False, "retrying", scope)
            logger.debug("[donationalerts] disconnected: %s", exc)
            await asyncio.sleep(10)


async def _da_handle_message(
    raw: str | bytes, scope: tuple[int, str] | None = None,
) -> None:
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return
    # Centrifugo push: {"method":"publication", "params":{"data":{"data":{...}}}}
    if msg.get("method") != "publication":
        return
    data = (msg.get("params", {}) or {}).get("data", {}) or {}
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(inner, dict) or not inner.get("alert_type") == "1":
        return
    try:
        amount = float(inner.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0:
        return
    await _process_donation(
        "donationalerts",
        str(inner.get("username") or "anonymous")[:100],
        amount,
        str(inner.get("currency") or "RUB")[:10],
        str(inner.get("message") or "")[:500],
        account_id=scope[0] if scope else None,
        channel=scope[1] if scope else None,
        event_id=str(inner.get("id") or ""),
    )


# ── Синхронизация DonateX-сборов → donation-challenge ───────────
# Решение владельца: внешний сбор (goal) автоматически двигает активные
# челленджи виджета donation-challenge. Каждый опрос применяет ДЕЛЬТУ
# внешнего currentAmount (локальные донаты не затираются); первый опрос
# задаёт базовую линию без дельты. Уменьшение сбора (правка цели) тоже
# переносится, но не даёт current_amount уйти ниже 0.


async def fetch_donatex_goal(goal_id: str) -> dict | None:
    """GET /api/goals/:goalId → {name, current, target, currency} или None."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_DONATEX_GOAL_URL + str(goal_id).strip())
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        logger.debug("[donatex] goal fetch failed: %s", exc)
        return None
    try:
        return {
            "name": str(data.get("name") or ""),
            "current": float(data.get("currentAmount") or 0),
            "target": float(data.get("targetAmount") or 0),
            "currency": str(data.get("currency") or "RUB")[:10],
        }
    except (TypeError, ValueError):
        return None


async def _sync_donatex_goal_once(scope: tuple[int, str] | None = None) -> bool:
    """Один шаг синхронизации. False — синхронизация неактивна/не удалась."""
    from app.widgets import get_db
    db = await get_db()
    try:
        if scope is None:
            cursor = await db.execute(
                "SELECT platform, external_goal_id, enabled, last_amount, synced "
                "FROM donation_goal_sync WHERE id = 1"
            )
        else:
            cursor = await db.execute(
                "SELECT platform, external_goal_id, enabled, last_amount, synced "
                "FROM donation_goal_sync_scoped WHERE account_id = ? AND channel = ?", scope,
            )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row or not row["enabled"] or not (row["external_goal_id"] or "").strip():
        return False
    goal = await fetch_donatex_goal(row["external_goal_id"])
    if goal is None:
        return False
    delta = goal["current"] - float(row["last_amount"] or 0)
    already_synced = bool(row["synced"])
    db = await get_db()
    try:
        if not already_synced:
            # базовая линия: запоминаем текущее значение, ничего не добавляем
            if scope is None:
                await db.execute(
                    "UPDATE donation_goal_sync SET last_amount = ?, synced = 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = 1", (goal["current"],),
                )
            else:
                await db.execute(
                    "UPDATE donation_goal_sync_scoped SET last_amount = ?, synced = 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE account_id = ? AND channel = ?",
                    (goal["current"], *scope),
                )
        else:
            if abs(delta) >= 0.01:
                where = "account_id IS NULL AND channel IS NULL" if scope is None else (
                    "account_id = ? AND channel = ?"
                )
                await db.execute(
                    "UPDATE donation_challenges SET current_amount = "
                    f"MAX(0, current_amount + ?) WHERE {where} AND active = 1",
                    (delta, *(scope or ())),
                )
            if scope is None:
                await db.execute(
                    "UPDATE donation_goal_sync SET last_amount = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = 1", (goal["current"],),
                )
            else:
                await db.execute(
                    "UPDATE donation_goal_sync_scoped SET last_amount = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE account_id = ? AND channel = ?",
                    (goal["current"], *scope),
                )
        await db.commit()
    finally:
        await db.close()
    if already_synced and abs(delta) >= 0.01:
        logger.info("[donatex] сбор «%s»: дельта %+.2f → челлендж",
                    goal["name"], delta)
    return True


async def goal_sync_loop() -> None:
    """Фоновый цикл синхронизации внешних сборов (раз в 60с)."""
    logger.info("[donatex] goal sync loop запущен")
    while True:
        try:
            await _sync_donatex_goal_once()
            from app.widgets import _all_donation_goal_sync_scopes
            for scope in await _all_donation_goal_sync_scopes():
                await _sync_donatex_goal_once(scope)
        except Exception as exc:
            logger.debug("[donatex] goal sync error: %s", exc)
        await asyncio.sleep(60)


# ── Диспетчер (мультиплатформенный) ──────────────────────────────
# Решение владельца 28.08: DonatePay + DonateX + DonationAlerts могут быть
# включены ОДНОВРЕМЕННО — у каждой платформы свой параллельный цикл и статус.

_integration_tasks: dict[tuple[int, str, str], asyncio.Task] = {}

_PLATFORM_LOOPS = {
    "donatepay": donatepay_loop,
    "donatex": donatex_loop,
    "donationalerts": donationalerts_loop,
}


async def _stop_integration_task(key: tuple[int, str, str]) -> None:
    task = _integration_tasks.pop(key, None)
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def stop_integrations() -> None:
    tasks = tuple(_integration_tasks.values())
    _integration_tasks.clear()
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _task_name(platform: str, scope: tuple[int, str] | None) -> str:
    scope_name = "legacy" if scope is None else f"{scope[0]}-{scope[1]}"
    return f"donation-{platform}-{scope_name}"


async def _start_integration_task(platform: str, scope: tuple[int, str] | None) -> bool:
    loop_fn = _PLATFORM_LOOPS.get(platform)
    if loop_fn is None:
        return False
    settings = await get_platform_settings(platform, scope)
    if scope is not None:
        settings.update({"account_id": scope[0], "channel": scope[1]})
    if not settings.get("enabled") or not (settings.get("token") or "").strip():
        _set_status(platform, False, "disabled" if not settings.get("enabled") else "missing_token", scope)
        return False
    key = _status_key(platform, scope)
    _integration_tasks[key] = asyncio.create_task(
        loop_fn(settings), name=_task_name(platform, scope),
    )
    _set_status(platform, False, "connecting", scope)
    return True


async def reconnect_integration(
    platform: str, scope: tuple[int, str] | None,
) -> dict:
    key = _status_key(platform, scope)
    await _stop_integration_task(key)
    started = await _start_integration_task(platform, scope)
    state = "connecting" if started else _last_status[key]["state"]
    return {"ok": started, "state": state}


async def _dispatcher_loop() -> None:
    """Держит по одному циклу на каждую включённую платформу с токеном."""
    while True:
        try:
            from app.widgets import _all_donation_integration_rows
            configured = await _all_donation_integration_rows()
            for settings in configured:
                platform = settings["platform"]
                loop_fn = _PLATFORM_LOOPS.get(platform)
                if loop_fn is None:
                    continue
                scope = _settings_scope(settings)
                key = _status_key(platform, scope)
                task = _integration_tasks.get(key)
                if task and not task.done():
                    if settings.get("enabled") and (settings.get("token") or "").strip():
                        continue
                    await _stop_integration_task(key)
                    continue
                if settings.get("enabled") and (settings.get("token") or "").strip():
                    await _start_integration_task(platform, scope)
                    logger.info("[donations] интеграция запущена: %s scope=%s", platform, scope)
                else:
                    _integration_tasks.pop(key, None)
        except Exception as exc:
            logger.debug("[donations] dispatcher error: %s", exc)
        await asyncio.sleep(15)


def get_status(
    platform: str | None = None, scope: tuple[int, str] | None = None,
    persisted_last_success: str | None = None,
) -> dict | None:
    if platform is not None:
        status = _last_status.get(_status_key(platform, scope))
        if status:
            result = {**status}
            result["last_success_at"] = result.get("last_success_at") or persisted_last_success
            return result
        return {
            "ok": False,
            "state": "idle",
            "detail": "idle",
            "at": None,
            "last_success_at": persisted_last_success,
        }
    return {f"{key[0]}:{key[1]}:{key[2]}": {**status} for key, status in _last_status.items()}


async def integration_loop() -> None:
    """Фоновая задача (server.lifespan, одна строка)."""
    logger.info("[donations] integrations loop запущен")
    goal_task = asyncio.create_task(goal_sync_loop(), name="donation-goal-sync")
    try:
        await _dispatcher_loop()
    finally:
        goal_task.cancel()
        await asyncio.gather(goal_task, return_exceptions=True)
        await stop_integrations()
