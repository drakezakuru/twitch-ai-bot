"""PLAN_SESSION_ROLES §R2: mod-feed — единый канал событий ролей.

События (действия модератора / намерения с одобрением / нарушения / луркер-
наблюдения / «мат проскочил») летят сюда; OBS-виджет /widget/mod-feed и тосты
панели их показывают. Дедуп не даёт завалить оверлей одинаковыми нарушениями.

Admin (auth панели):
    POST /api/mod-feed/events            — publish (из рантайма/тестов)
    GET  /api/mod-feed/events            — последние N (панель)
    POST /api/mod-feed/intents/{id}/{approve|reject}

Public (OBS-оверлей, без auth):
    GET  /api/mod-feed/public/poll?since=N — новые события курсором
"""
from __future__ import annotations

import itertools
import logging
import time
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.security import auth_dependency
from app.mod_feed_i18n import caption, sanitize_localization

logger = logging.getLogger(__name__)

admin_router = APIRouter(dependencies=[Depends(auth_dependency)])
public_router = APIRouter()

# --- in-memory store (панель-процесс; рестарт = пустой фид, виджет живёт) ---
_BUFFER: deque[dict] = deque(maxlen=200)
_SEQ = itertools.count(1)
# дедуп: ключ (account_id, channel, user, kind[, action]) → ts последнего события
_DEDUP: dict[tuple, float] = {}
_DEDUP_WINDOW = 60.0
# намерения, ждущие одобрения: id → payload; исполнители отдельно (не сериализуются)
_INTENTS: dict[str, dict] = {}
_INTENT_EXECUTORS: dict[str, Any] = {}
# §R5: последний нарушитель per exact bot/channel scope.
_LAST_VIOLATOR: dict[tuple[int, str], dict] = {}


def _normalize_channel(channel: str) -> str:
    return str(channel or "").strip().lower().lstrip("#")


async def _moderator_action(
    account_id: int, channel: str, action: str, value: str = "",
) -> dict:
    """§R5: действия модератора для hotkey-биндингов (widget='moderation').

    timeout_last / warn_last — наказать последнего нарушителя (лестница t1
    из role_config); slow_on/slow_off/emote_on/emote_off/clear — режимы чата
    через Helix. Account и channel всегда берутся из scope биндинга.
    """
    from app.database import get_db
    from app.twitch_helix import clear_chat_messages, timeout_user, update_chat_settings

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, nickname, bot_role, role_config_json FROM accounts "
            "WHERE id = ? AND bot_role = 'moderator' AND enabled = 1",
            (account_id,),
        )
        row = await cur.fetchone()
        channel = _normalize_channel(channel)
        ch_row = await (await db.execute(
            "SELECT 1 FROM channels WHERE account_id = ? AND enabled = 1 "
            "AND lower(ltrim(trim(channel_name), '#')) = ?",
            (account_id, channel),
        )).fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "no_moderator_bot"}
    if not ch_row:
        return {"error": "no_channel"}
    account_id = int(row["id"])
    nickname = row["nickname"] or ""
    from app.bot_roles import load_role_config
    cfg = load_role_config(row["role_config_json"], row["bot_role"] or "moderator")

    info = _LAST_VIOLATOR.get((account_id, channel))
    if action in ("timeout_last", "warn_last") and not info:
        return {"error": "no_last_violator"}

    token = ""
    try:
        from app.server import chat_analyzer
        token = chat_analyzer._account_token.get(account_id, "")
    except Exception:
        pass

    if action == "timeout_last":
        minutes = int(cfg.get("ladder_t1_min", 1) or 1)
        ok, err = await timeout_user(
            token, channel, nickname, info["user"],
            duration_sec=minutes * 60, reason=f"mod-feed hotkey: {(info or {}).get('text', '')[:100]}",
        )
        publish_event(account_id, channel, "action", user=(info or {}).get("user", ""),
                      text="таймаут по хоткею" if ok else f"ошибка: {err}",
                      action=f"timeout {minutes} мин",
                      localization={"text": caption("mod-feed.caption.hotkey_timeout" if ok else "mod-feed.caption.failed"),
                                    "action": caption("mod-feed.caption.timeout", minutes=minutes)})
        return {"ok": ok, "error": err}
    if action == "warn_last":
        publish_event(account_id, channel, "action", user=(info or {}).get("user", ""),
                      text="предупреждение по хоткею", action="warn",
                      localization={"text": caption("mod-feed.caption.hotkey_warn"), "action": caption("mod-feed.caption.tool.warn")})
        return {"ok": True, "warned": (info or {}).get("user", "")}

    # режимы чата — токен обязателен
    if not token:
        return {"error": "no_token"}
    if action == "clear":
        ok, err = await clear_chat_messages(token, channel, nickname)
        if ok:
            publish_event(account_id, channel, "action", user="",
                          text="чат очищен по хоткею", action="clear",
                          localization={"text": caption("mod-feed.caption.hotkey_clear"), "action": caption("mod-feed.caption.tool.clear")})
        return {"ok": ok, "error": err}
    mapping = {
        "slow_on": {"slow_mode": True, "slow_mode_wait_time": int(value or 5)},
        "slow_off": {"slow_mode": False},
        "emote_on": {"emote_mode": True},
        "emote_off": {"emote_mode": False},
        "unique_on": {"unique_chat_mode": True},
        "unique_off": {"unique_chat_mode": False},
    }
    if action not in mapping:
        return {"error": "unsupported", "action": action}
    ok, err = await update_chat_settings(token, channel, nickname, **mapping[action])
    if ok:
        publish_event(account_id, channel, "action", user="",
                      text=f"{action} применён", action=action,
                      localization={"text": caption("mod-feed.caption.hotkey_applied", tool=action),
                                    "action": caption(f"mod-feed.caption.tool.{action}")})
    return {"ok": ok, "error": err}

KINDS = ("violation", "intent", "action", "lurker", "beep")


def publish_event(
    account_id: int,
    channel: str,
    kind: str,
    *,
    user: str = "",
    text: str = "",
    severity: int = 0,
    action: str = "",
    intent: dict | None = None,
    localization: dict | None = None,
    dedup: bool = True,
) -> dict | None:
    """Положить событие в фид. Возвращает событие или None (дедуп/мусор)."""
    if kind not in KINDS:
        return None
    normalized_channel = _normalize_channel(channel)
    key = (int(account_id), normalized_channel, (user or "").lower(), kind)
    if kind == "action":
        key += (action,)
    now = time.time()
    if dedup and _DEDUP.get(key, 0.0) > now - _DEDUP_WINDOW:
        return None
    _DEDUP[key] = now
    ev = {
        "id": next(_SEQ),
        "ts": now,
        "account_id": int(account_id),
        "channel": normalized_channel,
        "kind": kind,
        "user": user,
        "text": text,
        "severity": severity,
        "action": action,
        "intent": intent,
        "status": "pending" if kind == "intent" else "done",
    }
    localized = sanitize_localization(localization)
    if localized:
        ev["localization"] = localized
    _BUFFER.append(ev)
    if kind == "violation" and user:
        # §R5: запоминаем последнего нарушителя (для хоткея timeout_last)
        _LAST_VIOLATOR[(int(account_id), ev["channel"])] = {
            "channel": ev["channel"], "user": user, "ts": now,
            "severity": severity, "text": text,
        }
    if isinstance(intent, dict):
        # callable-исполнитель не сериализуем в JSON — храним отдельно
        executor = intent.pop("_executor", None)
        if executor is not None:
            _INTENT_EXECUTORS[str(ev["id"])] = executor
        _INTENTS[str(ev["id"])] = ev
    # WS-тосты панели (видеть без OBS)
    try:
        import asyncio
        from app.server import broadcast_log
        payload = {k: v for k, v in ev.items() if k != "intent"}
        payload["type"] = "mod_feed"
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcast_log(payload))
        except RuntimeError:
            pass
    except Exception:
        pass
    return ev


def _cleanup_dedup(now: float) -> None:
    for k in [k for k, ts in _DEDUP.items() if now - ts > 600]:
        _DEDUP.pop(k, None)


@admin_router.post("/api/mod-feed/events")
async def mod_feed_publish(data: dict) -> dict:
    ev = publish_event(
        int(data.get("account_id") or 0),
        str(data.get("channel") or ""),
        str(data.get("kind") or ""),
        user=str(data.get("user") or ""),
        text=str(data.get("text") or ""),
        severity=int(data.get("severity") or 0),
        action=str(data.get("action") or ""),
        intent=data.get("intent"),
        localization=data.get("localization"),
        dedup=bool(data.get("dedup", True)),
    )
    if ev is None:
        return {"ok": False, "error": "dedup_or_bad_kind"}
    return {"ok": True, "event": ev}


@admin_router.get("/api/mod-feed/events")
async def mod_feed_list(
    limit: int = 30, account_id: int | None = None, channel: str | None = None,
) -> dict:
    normalized_channel = _normalize_channel(channel or "")
    items = [
        e for e in _BUFFER
        if (account_id is None or e["account_id"] == account_id)
        and (not normalized_channel or e["channel"] == normalized_channel)
    ]
    return {"ok": True, "items": list(items)[-max(1, min(limit, 200)):][::-1],
            "intents": [e for e in items if e["kind"] == "intent" and e["status"] == "pending"]}


def _is_coro(fn: Any) -> bool:
    import inspect
    return inspect.iscoroutinefunction(fn)


@admin_router.post("/api/mod-feed/intents/{intent_id}/{decision}")
async def mod_feed_intent(intent_id: str, decision: str) -> dict:
    """Одобрить/отклонить НАМЕРЕНИЕ модератора (confirm_mode=confirm)."""
    ev = _INTENTS.pop(str(intent_id), None)
    if not ev:
        return {"ok": False, "error": "not_found"}
    if decision not in ("approve", "reject"):
        return {"ok": False, "error": "bad_decision"}
    ev["status"] = "approved" if decision == "approve" else "rejected"
    ev["intent"]["decision"] = ev["status"]
    executor = _INTENT_EXECUTORS.pop(str(intent_id), None)
    if decision == "approve" and executor is not None:
        try:
            ev["intent"]["executed"] = await executor() if _is_coro(executor) else executor()
        except Exception as exc:
            logger.warning("intent executor failed: %s", exc)
            ev["intent"]["executed"] = False
    return {"ok": True, "event": ev}


@admin_router.get("/api/mod-feed/roles-summary")
async def mod_feed_roles_summary() -> dict:
    """§R5 дашборд: боты по ролям с цветами + счётчики событий за фид."""
    from app.database import get_db
    from app.bot_roles import ROLE_COLORS, VALID_ROLES
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, nickname, bot_role, enabled FROM accounts ORDER BY id")
        bots = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute(
            "SELECT account_id, COUNT(*) AS cnt FROM channels WHERE enabled = 1 "
            "GROUP BY account_id")
        chans = {r["account_id"]: r["cnt"] for r in await cur.fetchall()}
    finally:
        await db.close()
    counts: dict[int, dict[str, int]] = {}
    for e in _BUFFER:
        c = counts.setdefault(e["account_id"], {})
        c[e["kind"]] = c.get(e["kind"], 0) + 1
    for b in bots:
        role = b["bot_role"] if b["bot_role"] in VALID_ROLES else "chatter"
        b["bot_role"] = role
        b["color"] = ROLE_COLORS.get(role, "#22c55e")
        b["channels"] = chans.get(b["id"], 0)
        c = counts.get(b["id"], {})
        b["violations"] = c.get("violation", 0)
        b["actions"] = c.get("action", 0) + c.get("intent", 0)
    return {"ok": True, "bots": bots}


@public_router.get("/api/mod-feed/public/poll")
async def mod_feed_poll(since: int = 0, kinds: str = "") -> dict:
    """Курсорный поллинг для OBS-виджета (после рестарта панели отдаёт пусто)."""
    _cleanup_dedup(time.time())
    allowed = {k.strip() for k in kinds.split(",") if k.strip() in KINDS}
    items = [
        e for e in _BUFFER
        if e["id"] > since and (not allowed or e["kind"] in allowed)
    ]
    cursor = max([e["id"] for e in items], default=since)
    return {"ok": True, "events": items, "cursor": cursor}


@public_router.get("/widget/mod-feed", response_class=HTMLResponse)
async def widget_mod_feed() -> str:
    """OBS-оверлей всплывашек ролей (позиция/длительность/фильтр — через URL)."""
    from app.widgets import _widget_html
    return _widget_html("mod-feed")
