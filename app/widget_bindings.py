"""§11.3 WIDGETS_PLAN: биндинги виджетов — бот меняет виджеты автоматически.

Единая таблица ``widget_bindings`` (CRUD и схема — в ``app/widgets.py``):
    {id, account_id, channel, enabled, source: chat_command|eventsub,
     match, widget, widget_key, action, value, role}

Каждый lookup и dispatch требует exact ``account_id + normalized channel``.

``source=chat_command``: первый токен/префикс команды точно совпадает с ``match``
(например ``!death``, ``!цель +10``, ``!cd start``) → действие над виджетом.
``source=eventsub``: событие ``channel.subscribe`` / ``channel.cheer`` /
``channel.follow`` / ``channel.raid`` → действие (sub-goal +1 и т.п.).

Права для chat_command (``role``): streamer | mod | any.
Поддерживаемые плейсхолдеры в ``value``: ``{user}``, ``{amount}``.

Исполнитель действий переиспользует публичные функции ``app/widgets.py``
(те же, что дергают админ-формы) — никакой дублирующей записи в БД.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# W6 canonical contract. Backend validation and the panel builder consume this
# same manifest; ``counter`` remains backend-only for legacy stored bindings.
BINDING_CONTRACT = {
    "version": 2,
    "sources": {
        "chat_command": {
            "label": "bindings.source_chat", "roles": ["mod", "streamer"],
        },
        "eventsub": {
            "label": "bindings.source_event", "roles": ["any"],
            "matches": [
                "channel.follow", "channel.subscribe", "channel.cheer", "channel.raid",
            ],
        },
        "hotkey": {
            "label": "bindings.source_hotkey", "roles": ["streamer"],
        },
    },
    "roles": {
        "mod": {"label": "bindings.role_mod"},
        "streamer": {"label": "bindings.role_streamer"},
        "any": {"label": "bindings.role_any"},
    },
    "widgets": {
        "goals": {
            "label": "bindings.widget_goals",
            "key": {"type": "positive_integer", "required": True, "kind": "goal"},
            "actions": {
                "add_percent": {"label": "bindings.action_add_percent", "value": {"type": "integer_or_amount", "required": False}},
                "reset": {"label": "bindings.action_reset", "value": {"type": "none", "required": False}},
            },
        },
        "sub_goal": {
            "label": "bindings.widget_sub_goal",
            "actions": {
                "increment": {"label": "bindings.action_increment", "value": {"type": "integer_or_amount", "required": False}},
                "set": {"label": "bindings.action_set", "value": {"type": "integer_or_amount", "required": False}},
                "reset": {"label": "bindings.action_reset", "value": {"type": "none", "required": False}},
            },
        },
        "countdown": {
            "label": "bindings.widget_countdown",
            "actions": {
                "start": {"label": "bindings.action_start", "value": {"type": "none", "required": False}},
                "pause": {"label": "bindings.action_pause", "value": {"type": "none", "required": False}},
                "reset": {"label": "bindings.action_reset", "value": {"type": "none", "required": False}},
                "add_time": {"label": "bindings.action_add_time", "value": {"type": "integer", "required": False, "maximum": 86400}},
            },
        },
        "now_playing": {
            "label": "bindings.widget_now_playing",
            "actions": {
                "set": {"label": "bindings.action_set", "value": {"type": "string", "required": True}},
                "clear": {"label": "bindings.action_clear", "value": {"type": "none", "required": False}},
            },
        },
        "lower_third": {
            "label": "bindings.widget_lower_third",
            "actions": {
                "show": {"label": "bindings.action_show", "value": {"type": "string", "required": False}},
                "hide": {"label": "bindings.action_hide", "value": {"type": "none", "required": False}},
            },
        },
        "soundboard": {
            "label": "bindings.widget_soundboard", "actions": {},
            "dynamic_action": {"prefix": "play_track:", "parameter": "positive_integer", "label": "bindings.action_play_track"},
        },
        "moderation": {
            "label": "bindings.widget_moderation", "sources": ["hotkey"],
            "actions": {
                "timeout_last": {"label": "bindings.action_timeout_last", "value": {"type": "none", "required": False}},
                "warn_last": {"label": "bindings.action_warn_last", "value": {"type": "none", "required": False}},
                "slow_on": {"label": "bindings.action_slow_on", "value": {"type": "integer", "required": False}},
                "slow_off": {"label": "bindings.action_slow_off", "value": {"type": "none", "required": False}},
            },
        },
        # ── Q27a (DEC-OWNER-017 п.4): контракт v2 — осмысленные действия
        # для остальных виджетов каталога. Виджеты без осмысленных
        # действий над собой (tts*, chat-*, emoji-*, top-donator, schedule,
        # animated-bg, follower-ticker, hype-meter, media-share, mod-feed,
        # latest-event-card, anime-runner, clip-moments) в контракт
        # сознательно не входят — у виджета без контракта в UI нет
        # ни одного упоминания биндингов (Q11b).
        "mascot": {
            "label": "bindings.widget_mascot",
            "actions": {
                "preset": {"label": "bindings.action_preset", "value": {"type": "string", "required": True}},
            },
        },
        "uptime": {
            "label": "bindings.widget_uptime",
            "actions": {
                "start": {"label": "bindings.action_start", "value": {"type": "none", "required": False}},
                "stop": {"label": "bindings.action_stop", "value": {"type": "none", "required": False}},
            },
        },
        "subathon_timer": {
            "label": "bindings.widget_subathon",
            "actions": {
                "extend": {"label": "bindings.action_extend", "value": {"type": "integer", "required": False, "maximum": 86400}},
                "start": {"label": "bindings.action_start", "value": {"type": "none", "required": False}},
                "stop": {"label": "bindings.action_stop", "value": {"type": "none", "required": False}},
            },
        },
        "donation_challenge": {
            "label": "bindings.widget_donation_challenge",
            "actions": {
                "add_funds": {"label": "bindings.action_add_funds", "value": {"type": "integer_or_amount", "required": False}},
            },
        },
        "song_request": {
            "label": "bindings.widget_song_request",
            "actions": {
                "skip": {"label": "bindings.action_skip", "value": {"type": "none", "required": False}},
                "clear": {"label": "bindings.action_clear", "value": {"type": "none", "required": False}},
            },
        },
        "chat_highlight": {
            "label": "bindings.widget_chat_highlight",
            "actions": {
                "highlight": {"label": "bindings.action_highlight", "value": {"type": "string", "required": True}},
            },
        },
        "chat_roulette": {
            "label": "bindings.widget_chat_roulette",
            "actions": {
                "spin": {"label": "bindings.action_spin", "value": {"type": "none", "required": False}},
            },
        },
        "recent_events": {
            "label": "bindings.widget_recent_events",
            "actions": {
                "clear": {"label": "bindings.action_clear", "value": {"type": "none", "required": False}},
            },
        },
        "blur_guard_v2": {
            "label": "bindings.widget_blur_guard",
            "actions": {
                "blur_on": {"label": "bindings.action_blur_on", "value": {"type": "none", "required": False}},
                "blur_off": {"label": "bindings.action_blur_off", "value": {"type": "none", "required": False}},
            },
        },
    },
}

_LEGACY_WIDGET_ACTIONS = {"counter": ("increment", "set", "reset")}
ALLOWED_ACTIONS = {
    **{slug: tuple(spec["actions"]) for slug, spec in BINDING_CONTRACT["widgets"].items()},
    **_LEGACY_WIDGET_ACTIONS,
}
WIDGETS = tuple(ALLOWED_ACTIONS)
ACTIONS = tuple(sorted({a for actions in ALLOWED_ACTIONS.values() for a in actions}))


def validate_widget_action(widget: str, action: str) -> str | None:
    if widget == "soundboard" and action.startswith("play_track:"):
        track_id = action.split(":", 1)[1]
        return None if track_id.isdigit() and int(track_id) > 0 else "unknown_action"
    if widget not in ALLOWED_ACTIONS:
        return "unknown_widget"
    if action not in ACTIONS:
        return "unknown_action"
    if action not in ALLOWED_ACTIONS[widget]:
        return "incompatible_widget_action"
    return None

SOURCES = tuple(BINDING_CONTRACT["sources"])
ROLES = tuple(BINDING_CONTRACT["roles"])
EVENTSUB_MATCHES = tuple(BINDING_CONTRACT["sources"]["eventsub"]["matches"])


def validate_binding_contract(
    source: str, match: str, widget: str, widget_key: str,
    action: str, value: str, role: str,
) -> str | None:
    compatibility_error = validate_widget_action(widget, action)
    if compatibility_error:
        return compatibility_error
    if source not in SOURCES:
        return "bad_source"
    if not match.strip():
        return "match_required"
    source_contract = BINDING_CONTRACT["sources"][source]
    if role not in source_contract["roles"]:
        return "role_not_allowed"
    if source == "eventsub":
        if match not in EVENTSUB_MATCHES:
            return "bad_eventsub_match"
    widget_contract = BINDING_CONTRACT["widgets"].get(widget)
    if widget_contract and source not in widget_contract.get("sources", SOURCES):
        return "role_not_allowed"
    key_contract = (widget_contract or {}).get("key", {})
    if key_contract.get("required") and not widget_key.strip():
        return "widget_key_required"
    if key_contract.get("type") == "positive_integer":
        try:
            if int(widget_key) <= 0:
                return "widget_key_required"
        except (TypeError, ValueError):
            return "widget_key_required"
    if widget == "counter" and not widget_key.strip():
        return "widget_key_required"

    action_contract = (widget_contract or {}).get("actions", {}).get(action, {})
    value_contract = action_contract.get("value", {})
    if value_contract.get("required") and not value.strip():
        return "value_required"
    value_type = value_contract.get("type", "none")
    legacy_numeric = widget == "counter" and action in ("increment", "set")
    if value.strip() and (value_type in ("integer", "integer_or_amount") or legacy_numeric):
        if value.strip() == "{amount}" and value_type == "integer":
            return "bad_value"
        if value.strip() != "{amount}":
            try:
                number = int(value)
            except (TypeError, ValueError):
                return "bad_value"
            if abs(number) > int(value_contract.get("maximum", 1_000_000)):
                return "bad_value"
    return None


def _render_value(template: str, ctx: dict) -> str:
    out = template or ""
    for key, val in (ctx or {}).items():
        out = out.replace("{" + key + "}", str(val))
    return out


def _role_satisfies(binding_role: str, actual_role: str) -> bool:
    if binding_role == "any":
        return True
    if binding_role == "mod":
        return actual_role in ("broadcaster", "mod", "moderator")
    return actual_role == "broadcaster"


def normalize_channel(channel: str) -> str:
    return str(channel or "").strip().lower().lstrip("#")


async def run_binding(binding: dict, ctx: dict | None = None) -> dict:
    """Выполняет одно действие биндинга над виджетом.

    Все действия идут через публичные функции widgets.py — как если бы их
    вызвала админ-форма или OBS-хоткей.
    """
    from app import widgets as W

    widget = (binding.get("widget") or "").strip()
    action = (binding.get("action") or "").strip()
    key = (binding.get("widget_key") or "").strip()
    value = _render_value(str(binding.get("value") or ""), ctx or {})
    account_id = int(binding.get("account_id") or 0)
    channel = normalize_channel(binding.get("channel") or "")
    scope = ({"account_id": account_id, "channel": channel}
             if account_id > 0 and channel else {})
    compatibility_error = validate_widget_action(widget, action)
    if compatibility_error:
        return {"error": compatibility_error, "widget": widget, "action": action}
    source = str(binding.get("source") or "").strip()
    if source:
        contract_error = validate_binding_contract(
            source, str(binding.get("match") or ""), widget, key, action,
            str(binding.get("value") or ""), str(binding.get("role") or "mod"),
        )
        if contract_error:
            return {"error": contract_error, "widget": widget, "action": action}

    try:
        if widget == "counter":
            if action == "increment":
                delta = int(value) if value.strip() else 1
                return await W._counter_increment(key or "death", {"delta": delta}, **scope)
            if action == "set":
                return await W.counter_update(
                    key or "death", {"value": int(value or 0)}, **scope
                )
            if action == "reset":
                return await W._counter_reset(key or "death", **scope)
        elif widget == "goals":
            gid = int(key or 0)
            if gid <= 0:
                return {"error": "widget_key_required"}
            if action == "add_percent":
                delta = int(value) if value.strip() else 1
                return await W.goals_step(gid, {"delta": delta}, **scope)
            if action == "reset":
                result = await W.goals_update(gid, {"percent": 0}, **scope)
                return {**result, "id": gid, "percent": 0}
        elif widget == "sub_goal":
            if action == "increment":
                delta = int(value) if value.strip() else 1
                return await W.sub_goal_increment({"delta": delta}, **scope)
            if action == "set":
                return await W.sub_goal_update(
                    {"current": max(0, int(value or 0))}, **scope
                )
            if action == "reset":
                return await W.sub_goal_reset(**scope)
        elif widget == "countdown":
            if action == "start":
                return await W.countdown_start(**scope)
            if action == "pause":
                return await W.countdown_stop(**scope)
            if action == "reset":
                return await W.countdown_reset(**scope)
            if action == "add_time":
                seconds = int(value) if value.strip() else 300
                return await W.countdown_add_time(seconds, **scope)
        elif widget == "now_playing":
            if action == "set" and value.strip():
                return await W.apply_now_playing(
                    {"text": value.strip(), "kind": "music"}, **scope
                )
            if action == "clear":
                return await W.now_playing_clear(**scope)
        elif widget == "soundboard":
            if action.startswith("play_track:"):
                return await W.soundboard_play(
                    int(action.split(":", 1)[1]),
                    int(binding.get("account_id") or 0),
                    normalize_channel(binding.get("channel") or ""),
                )
        elif widget == "lower_third":
            if action == "show":
                payload = {"visible": True}
                if value.strip():
                    payload["name"] = value.strip()
                return await W.lower_third_put(payload, **scope)
            if action == "hide":
                return await W.lower_third_put({"visible": False}, **scope)
        elif widget == "moderation":
            from app.mod_feed_routes import _moderator_action
            account_id = int(binding.get("account_id") or 0)
            channel = normalize_channel(binding.get("channel") or "")
            if account_id <= 0 or not channel:
                return {"error": "binding_scope_required"}
            return await _moderator_action(account_id, channel, action, value)
        elif widget == "mascot":
            if action == "preset" and value.strip():
                return await W.mascot_put({"preset": value.strip()}, **scope)
        elif widget == "uptime":
            if action == "start":
                return await W.stream_session_start()
            if action == "stop":
                return await W.stream_session_stop()
        elif widget == "subathon_timer":
            if action == "extend":
                seconds = int(value) if value.strip() else 60
                await W.subathon_extend(seconds, (scope["account_id"], scope["channel"]) if scope else None)
                return {"ok": True, "extended": seconds}
            if action == "start":
                return await W.subathon_start(None, **scope)
            if action == "stop":
                return await W.subathon_stop(**scope)
        elif widget == "donation_challenge":
            if action == "add_funds":
                amount = float(value) if value.strip() else 100.0
                active = await W.donation_challenge_active(**scope)
                if not active.get("active"):
                    return {"error": "no_active_challenge"}
                return await W.donation_challenges_add_funds(
                    int(active["id"]), {"amount": amount}, **scope,
                )
        elif widget == "song_request":
            if action == "skip":
                return await W.sr_skip(**scope)
            if action == "clear":
                return await W.sr_clear(**scope)
        elif widget == "chat_highlight":
            if action == "highlight" and value.strip():
                # Не push_chat_highlight: ручной триггер должен показать
                # подсветку независимо от auto_mode (гейт авто-режима).
                return await W.chat_highlight_put(
                    {"text": value.strip(), "kind": "manual", "visible": True}, **scope,
                )
        elif widget == "chat_roulette":
            if action == "spin":
                return await W.roulette_spin(None, **scope)
        elif widget == "recent_events":
            if action == "clear":
                return await W.recent_events_clear(**scope)
        elif widget == "blur_guard_v2":
            if action in ("blur_on", "blur_off"):
                from fastapi import HTTPException
                from app import blur_guard_routes as BGR
                try:
                    if action == "blur_on":
                        return await BGR.blur_guard_manual_on()
                    return await BGR.blur_guard_manual_off()
                except HTTPException as exc:
                    return {"error": "blur_unavailable", "detail": str(exc.detail)}
        return {"error": "unsupported", "widget": widget, "action": action}
    except (TypeError, ValueError) as exc:
        return {"error": f"bad_value: {exc}"}


async def _active_bindings(source: str, account_id: int, channel: str) -> list[dict]:
    channel = normalize_channel(channel)
    if account_id <= 0 or not channel:
        return []
    from app.widgets import get_db
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, account_id, channel, enabled, source, match, widget, widget_key, "
            "action, value, role FROM widget_bindings "
            "WHERE enabled = 1 AND source = ? AND account_id = ? AND channel = ? "
            "ORDER BY id ASC",
            (source, account_id, channel),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def has_sub_goal_subscribe_binding(account_id: int, channel: str) -> bool:
    """Whether EventSub already owns the automatic Sub Goal increment."""
    return any(
        item.get("match") == "channel.subscribe"
        and item.get("widget") == "sub_goal"
        and item.get("action") == "increment"
        for item in await _active_bindings("eventsub", account_id, channel)
    )


async def handle_chat_command(
    text: str, author: str, account_id: int, channel: str, role: str = "viewer",
) -> list[dict]:
    """Хук из chat_analyzer.on_message: команды → действия над виджетами."""
    results: list[dict] = []
    text_l = (text or "").strip().lower()
    if not text_l:
        return results
    for binding in await _active_bindings("chat_command", account_id, channel):
        match = (binding.get("match") or "").strip().lower()
        if not match or not (
            text_l == match
            or (text_l.startswith(match) and text_l[len(match):len(match) + 1].isspace())
        ):
            continue
        if not _role_satisfies(binding.get("role") or "mod", role):
            continue
        res = await run_binding(binding, {"user": author, "amount": 0})
        logger.info("[bindings] %s → %s/%s от %s: %s",
                    binding.get("match"), binding.get("widget"),
                    binding.get("action"), author, res)
        results.append({"binding_id": binding.get("id"), "result": res})
    return results


async def handle_hotkey(combo: str, account_id: int, channel: str) -> dict:
    """PLAN_FEEDBACK_2908 §3.1: hotkey-биндинги панели.

    ``combo`` — нормализованная строка от фронтенда ('ctrl+shift+d',
    'f5', 'space'). Работает, пока панель открыта в браузере: keydown
    слушает вкладка панели. Роль — уровень панели (streamer), поэтому
    выполняются ВСЕ сматченные биндинги, как чат-команда от стримера.
    """
    combo_n = (combo or "").strip().lower()
    if not combo_n:
        return {"combo": combo_n, "executed": []}
    executed: list[dict] = []
    for binding in await _active_bindings("hotkey", account_id, channel):
        if (binding.get("match") or "").strip().lower() != combo_n:
            continue
        res = await run_binding(binding, {"user": "panel"})
        executed.append({"id": binding.get("id"), "match": binding.get("match"), "result": res})
    return {"combo": combo_n, "executed": executed}


async def handle_eventsub_event(
    account_id: int, event_type: str, channel: str, username: str, amount: int = 0,
) -> list[dict]:
    """Хук из server.on_eventsub_event: sub/cheer/follow/raid → виджеты."""
    results: list[dict] = []
    for binding in await _active_bindings("eventsub", account_id, channel):
        match = (binding.get("match") or "").strip()
        if not match or match != event_type:
            continue
        res = await run_binding(binding, {"user": username, "amount": amount})
        logger.info("[bindings] eventsub %s → %s/%s: %s",
                    event_type, binding.get("widget"), binding.get("action"), res)
        results.append({"binding_id": binding.get("id"), "result": res})
    return results


# ── Пресеты «одной кнопкой» ─────────────────────────────────────

PRESETS: dict[str, list[dict]] = {
    "deaths": [{
        "source": "chat_command", "match": "!death", "widget": "counter",
        "widget_key": "death", "action": "increment", "value": "1", "role": "any",
    }],
    "sub_goal": [{
        "source": "eventsub", "match": "channel.subscribe", "widget": "sub_goal",
        "widget_key": "", "action": "increment", "value": "1", "role": "any",
    }],
    "countdown_end": [{
        "source": "chat_command", "match": "!cd start", "widget": "countdown",
        "widget_key": "", "action": "start", "value": "", "role": "mod",
    }, {
        "source": "chat_command", "match": "!cd pause", "widget": "countdown",
        "widget_key": "", "action": "pause", "value": "", "role": "mod",
    }],
}


async def apply_preset(name: str, account_id: int, channel: str) -> dict:
    """Создаёт набор биндингов пресета (дубликаты по match+widget пропускает)."""
    items = PRESETS.get(name)
    if not items:
        return {"error": "unknown_preset"}
    channel = normalize_channel(channel)
    if account_id <= 0 or not channel:
        return {"error": "binding_scope_required"}
    from app.widgets import get_db
    created = 0
    db = await get_db()
    try:
        for item in items:
            cursor = await db.execute(
                "SELECT id FROM widget_bindings WHERE account_id = ? AND channel = ? "
                "AND source = ? AND match = ? AND widget = ? AND widget_key = ?",
                (account_id, channel, item["source"], item["match"],
                 item["widget"], item["widget_key"]),
            )
            if await cursor.fetchone():
                continue
            cursor = await db.execute(
                "INSERT OR IGNORE INTO widget_bindings "
                "(account_id, channel, enabled, source, match, widget, "
                "widget_key, action, value, role) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
                (account_id, channel, item["source"], item["match"], item["widget"],
                 item["widget_key"], item["action"], item["value"], item["role"]),
            )
            created += 1 if cursor.rowcount else 0
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "created": created}
