"""PLAN_SESSION_ROLES §R3: роль-сторона Helix стрим-инструментов.

Мод-бот «предлагает» стрим-действия (категория/название/режимы чата) согласно
stream_tool_modes из role_config модератора:
    off     — инструмент выключен, предложение игнорируется;
    suggest — публикуется НАМЕРЕНИЕ в mod-feed, ждёт одобрения [Одобрить];
    auto    — исполняется сразу, в фид летит событие-действие.

Сам HTTP-клиент Helix живёт в app/twitch_helix.py и app/stream_tools_routes.py
(зона session/stream); здесь только решение роли + журнал + фид.

История: bot_logs (category='event'), details JSON с "stream_tool": true.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# инструменты роли → требуемый OAuth scope (для честной ошибки «нет права»)
TOOL_SCOPES: dict[str, str] = {
    "category": "channel:manage:broadcast",
    "ai_category": "channel:manage:broadcast",
    "title": "channel:manage:broadcast",
    "slow": "moderator:manage:chat_settings",
    "follower": "moderator:manage:chat_settings",
    "emote_only": "moderator:manage:chat_settings",
    "unique": "moderator:manage:chat_settings",
}
DEV_CONSOLE_URL = "https://dev.twitch.tv/console"

Executor = Callable[[], Awaitable[dict]]


async def _load_moderator(account_id: int) -> tuple[dict, dict] | None:
    """Аккаунт модератора + его role_config. None — бот не найден/не модератор."""
    from app.database import get_db
    from app.bot_roles import load_role_config

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, nickname, bot_role, role_config_json FROM accounts WHERE id = ?",
            (int(account_id),),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return None
    d = dict(row)
    role = d.get("bot_role") or "chatter"
    if role != "moderator":
        return None
    cfg = load_role_config(d.get("role_config_json"), role)
    return d, cfg


async def _first_channel(account_id: int) -> str:
    from app.database import get_db

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1 "
            "ORDER BY id LIMIT 1",
            (int(account_id),),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    return (row["channel_name"] if row else "") or ""


def _account_token(account_id: int) -> str:
    try:
        from app.server import chat_analyzer
        entry = chat_analyzer._account_token.get(int(account_id), "")
    except Exception:
        return ""
    if isinstance(entry, dict):
        return entry.get("access_token") or entry.get("token") or ""
    return entry or ""


async def _update_channel_info(
    token: str, channel: str, *, title: str | None = None, game_name: str | None = None,
) -> dict:
    """PATCH /channels (категория/название). Возвращает {ok, error}."""
    import httpx
    from app import twitch_helix as th

    if not th.is_helix_configured():
        return {"ok": False, "error": "helix_not_configured"}
    bare = th._strip_oauth(token)
    if not bare:
        return {"ok": False, "error": "no_token"}
    broadcaster_id = await th.get_user_id(channel.lower().lstrip("#"), token)
    if not broadcaster_id:
        return {"ok": False, "error": "broadcaster_not_found"}
    headers = {"Authorization": f"Bearer {bare}", "Client-Id": th._client_id()}
    body: dict[str, Any] = {}
    if title:
        body["title"] = title[:140]
    if game_name:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{th.HELIX_BASE}/games", headers=headers, params={"name": game_name})
            if resp.status_code == 200 and resp.json().get("data"):
                body["game_id"] = resp.json()["data"][0]["id"]
            else:
                return {"ok": False, "error": "game_not_found"}
        except Exception as exc:
            return {"ok": False, "error": f"exception: {exc}"}
    if not body:
        return {"ok": False, "error": "nothing_to_update"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                f"{th.HELIX_BASE}/channels", headers=headers,
                params={"broadcaster_id": broadcaster_id}, json=body)
        if resp.status_code in (200, 204):
            return {"ok": True, "error": ""}
        return {"ok": False, "error": f"helix_{resp.status_code}: {resp.text[:200]}"}
    except Exception as exc:
        return {"ok": False, "error": f"exception: {exc}"}


def _is_scope_error(error: str) -> bool:
    return error.startswith("helix_401") or error.startswith("helix_403")


def _scope_hint(tool: str) -> str:
    scope = TOOL_SCOPES.get(tool, "")
    return f"нет права {scope} — добавьте scope на {DEV_CONSOLE_URL} и перелогиньте бота"


def _make_executor(
    account_id: int, nickname: str, channel: str, tool: str, params: dict,
) -> Executor:
    """Замыкание-исполнитель: дергает Helix, возвращает {ok, error, scope_error}."""

    async def _run() -> dict:
        token = _account_token(account_id)
        if tool in ("category", "ai_category", "title"):
            res = await _update_channel_info(
                token, channel,
                title=params.get("title"),
                game_name=params.get("game_name"),
            )
        else:
            from app.twitch_helix import update_chat_settings
            kwargs: dict[str, Any] = {}
            if tool == "slow":
                kwargs["slow_mode"] = bool(params.get("enabled", True))
                if params.get("wait"):
                    kwargs["slow_mode_wait_time"] = int(params["wait"])
            elif tool == "follower":
                kwargs["follower_mode"] = bool(params.get("enabled", True))
                if params.get("duration"):
                    kwargs["follower_mode_duration"] = int(params["duration"])
            elif tool == "emote_only":
                kwargs["emote_mode"] = bool(params.get("enabled", True))
            elif tool == "unique":
                kwargs["unique_chat_mode"] = bool(params.get("enabled", True))
            ok, err = await update_chat_settings(token, channel, nickname, **kwargs)
            res = {"ok": ok, "error": err}
        res["scope_error"] = _is_scope_error(str(res.get("error", "")))
        return res

    return _run


async def _log_history(
    account_id: int, channel: str, *, tool: str, params: dict, mode: str,
    source: str, decision: str, result: dict, level: str = "info",
) -> None:
    from app.database import get_db

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO bot_logs (account_id, channel, level, category, message, details) "
            "VALUES (?, ?, ?, 'event', ?, ?)",
            (
                int(account_id), channel, level, f"stream-tool {tool}",
                json.dumps({
                    "stream_tool": True, "tool": tool, "params": params,
                    "mode": mode, "source": source, "decision": decision,
                    "result": {"ok": result.get("ok"), "error": result.get("error", "")},
                }, ensure_ascii=False),
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def propose_stream_action(
    account_id: int, tool: str, params: dict | None = None, *,
    source: str = "manual",
) -> dict:
    """Главный вход роли: предложить/исполнить стрим-действие.

    source: manual (кнопка в панели) | vision (кадры stream_vision) | runtime.
    Возвращает {ok, mode, event?} или {ok: False, error}.
    """
    from app.mod_feed_routes import publish_event
    from app.mod_feed_i18n import stream_localization

    params = dict(params or {})
    if tool not in TOOL_SCOPES:
        return {"ok": False, "error": "unknown_tool"}
    loaded = await _load_moderator(account_id)
    if not loaded:
        return {"ok": False, "error": "not_moderator"}
    row, cfg = loaded
    nickname = row.get("nickname") or ""
    modes = cfg.get("stream_tool_modes") or {}
    mode = str(modes.get(tool, "off"))
    if mode not in ("auto", "suggest"):
        return {"ok": False, "error": "disabled", "mode": mode}

    channel = (params.pop("channel", "") or await _first_channel(account_id)).lstrip("#").lower()
    if not channel:
        return {"ok": False, "error": "no_channel"}

    executor = _make_executor(int(account_id), nickname, channel, tool, params)
    label = _describe(tool, params)

    if mode == "suggest":
        base_executor = executor

        async def _approved_executor() -> dict:
            res = await base_executor()
            await _log_history(
                account_id, channel, tool=tool, params=params, mode=mode,
                source=source, decision="approved", result=res,
                level="warning" if not res.get("ok") else "info",
            )
            return res

        executor = _approved_executor
        ev = publish_event(
            int(account_id), channel, "intent", dedup=True,
            text=label, action=tool,
            localization=stream_localization(tool, params, "pending"),
            intent={"tool": tool, "params": params, "source": source,
                    "channel": channel, "_executor": executor},
        )
        if ev is None:
            return {"ok": False, "error": "dedup"}
        await _log_history(account_id, channel, tool=tool, params=params, mode=mode,
                           source=source, decision="pending", result={"ok": None})
        return {"ok": True, "mode": mode,
                "event": {k: v for k, v in ev.items() if k != "intent"}}

    # auto — исполняем сразу
    result = await executor()
    ev = publish_event(
        int(account_id), channel, "action", severity=2 if not result.get("ok") else 0,
        text=(f"{label} — выполнено" if result.get("ok")
              else (f"{label} — ошибка: {_scope_hint(tool)}" if result.get("scope_error")
                    else f"{label} — ошибка: {result.get('error')}")),
        action=tool,
        localization=stream_localization(tool, params, "done" if result.get("ok") else
                                         "scope_failed" if result.get("scope_error") else "failed"),
    )
    await _log_history(
        account_id, channel, tool=tool, params=params, mode=mode, source=source,
        decision="auto", result=result,
        level="warning" if not result.get("ok") else "info",
    )
    return {"ok": True, "mode": mode, "executed": result, "event": ev}


def _describe(tool: str, params: dict) -> str:
    if tool in ("category", "ai_category"):
        return f"сменить категорию на «{params.get('game_name', '?')}»"
    if tool == "title":
        return f"сменить название на «{(params.get('title') or '')[:60]}»"
    state = "включить" if params.get("enabled", True) else "выключить"
    names = {"slow": "slow-режим", "follower": "фоллоу-режим",
             "emote_only": "только эмодзи", "unique": "уникальный чат"}
    return f"{state} {names.get(tool, tool)}"


async def suggest_from_vision(account_id: int, detected_game: str) -> dict:
    """§R3 авто-категория по vision-кадрам: роли решает КОГДА предложить.

    Helix-PATCH остаётся за исполнением предложения (approve/auto).
    """
    return await propose_stream_action(
        account_id, "ai_category", {"game_name": detected_game}, source="vision")
