"""FastAPI маршруты: REST API + WebSocket для панели управления."""

import asyncio
import contextvars
import json
import logging
import os
import re
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Depends, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import backup as backup_mod
from app.widget_inventory import WIDGET_INVENTORY

from app.database import get_db, get_setting, get_setting_bool, set_setting, cleanup_account_children
from app.security import (
    auth_dependency,
    check_ws_auth,
    encrypt_token,
    decrypt_token,
    is_auth_enabled,
    is_encryption_enabled,
    mask_token,
    require_loopback_client,
    require_same_origin_request,
)
from app import user_memory
from app import streamer_lore
from app import learning as learning_mod
from app import summarizer
from app import personality_shift
from app.twitch_helix import (
    is_helix_configured,
    refresh_oauth_token,
    validate_token,
    get_channel_info,
)
from app import twitch_oauth
from app import twitch_credentials
from app import engagement as engagement_mod

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(auth_dependency)])
# Отдельный роутер без HTTP-auth для WebSocket — у WS своя проверка через check_ws_auth.
ws_router = APIRouter()
templates = Jinja2Templates(directory="templates")
import time as _time
templates.env.globals["asset_v"] = str(int(_time.time()))

# WebSocket connections для live-логов
ws_connections: list[WebSocket] = []
ws_channel_scopes: dict[int, str] = {}


async def broadcast_log(data: dict) -> None:
    channel_key = ""
    channel = str(data.get("channel") or "").strip().lower().lstrip("#")
    if channel:
        from app.widget_channel_scope import resolve_channel
        identity = await resolve_channel(channel)
        if identity:
            data = {**data, **identity.payload()}
            channel_key = identity.key
        else:
            data = {**data, "channel": channel, "channel_id": str(data.get("channel_id") or "")}
            channel_key = str(data.get("channel_id") or "") or channel
    for ws in ws_connections[:]:
        scope = ws_channel_scopes.get(id(ws), "")
        if scope and scope != channel_key:
            continue
        try:
            await ws.send_json(data)
        except Exception:
            ws_connections.remove(ws)
            ws_channel_scopes.pop(id(ws), None)


# v10.3 5: actor (кто из пользователей панели сделал действие).
# Прокидывается через middleware на app, держится в ContextVar чтобы
# существующие вызовы log_action(action, detail) не нужно было править.
_current_actor: contextvars.ContextVar[str] = contextvars.ContextVar("actor", default="")


def _resolve_actor(actor: str | None) -> str:
    if actor is None:
        return (_current_actor.get() or "").strip()
    return (actor or "").strip()


async def log_action(
    action: str,
    detail: str = "",
    *,
    actor: str | None = None,
    revert_payload: dict | str | None = None,
) -> int | None:
    """Записать действие в action_log.

    ``actor`` — если ``None``, возьмётся из ContextVar (Basic-Auth user из middleware).
    ``revert_payload`` — JSON для отката (см. v10.3 5). Принимает dict или сразу строку.
    Возвращает id записи (или ``None`` при ошибке).
    """
    try:
        actor_val = _resolve_actor(actor)
        if isinstance(revert_payload, dict):
            payload_str = json.dumps(revert_payload, ensure_ascii=False)
        elif revert_payload is None:
            payload_str = ""
        else:
            payload_str = str(revert_payload)
        db = await get_db()
        try:
            cur = await db.execute(
                "INSERT INTO action_log (action, detail, actor, revert_payload) VALUES (?, ?, ?, ?)",
                (action, detail, actor_val, payload_str),
            )
            await db.commit()
            return cur.lastrowid
        finally:
            await db.close()
    except Exception:
        return None


def actor_from_request(request: Request) -> str:
    """Достаёт username из Basic-Auth заголовка. Если нет — пусто."""
    try:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("basic "):
            return ""
        import base64
        try:
            raw = base64.b64decode(auth.split(" ", 1)[1].encode("ascii")).decode("utf-8", "ignore")
        except Exception:
            return ""
        if ":" in raw:
            return raw.split(":", 1)[0]
        return ""
    except Exception:
        return ""


async def actor_middleware(request: Request, call_next):
    """Middleware: ставит ContextVar.actor по Basic-Auth для всего запроса."""
    actor = actor_from_request(request)
    token = _current_actor.set(actor or "")
    try:
        return await call_next(request)
    finally:
        _current_actor.reset(token)


async def broadcast_ai_log(event: str, detail: str, account_id: int = 0, channel: str = "") -> None:
    """Отправляет AI-событие всем подключённым клиентам."""
    await broadcast_log({
        "type": "ai_log",
        "event": event,
        "detail": detail,
        "account_id": account_id,
        "channel": channel,
    })


# ===================== PAGES =====================

@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="index.html", context={"widget_inventory": WIDGET_INVENTORY}
    )


# ===================== ACCOUNTS =====================

@router.get("/api/accounts")
async def list_accounts() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM accounts ORDER BY id")
        rows = await cursor.fetchall()
        cursor = await db.execute(
            "SELECT account_id, channel_name FROM channels ORDER BY account_id, id"
        )
        persisted_channels: dict[int, list[str]] = {}
        for channel in await cursor.fetchall():
            persisted_channels.setdefault(channel["account_id"], []).append(channel["channel_name"])
        accounts = []
        for row in rows:
            account = _account_to_dict(row)
            account["persisted_channels"] = persisted_channels.get(row["id"], [])
            accounts.append(account)
        return accounts
    finally:
        await db.close()


def _account_to_dict(row: Any) -> dict:
    """Превращает row в dict, маскируя токен в ответе UI."""
    if not row:
        return {}
    d = dict(row)
    # Не отдаём токен наружу — только маску
    raw_token = d.get("token", "") or ""
    plain = decrypt_token(raw_token) if raw_token else ""
    d["token_masked"] = mask_token(plain)
    d["token"] = ""  # не отдаём токен наружу
    if "refresh_token" in d:
        rt_raw = d.get("refresh_token") or ""
        d["has_refresh_token"] = bool(decrypt_token(rt_raw)) if rt_raw else False
        d["refresh_token"] = ""  # не отдаём refresh-токен наружу
    return d


@router.post("/api/accounts")
async def create_account(data: dict[str, Any]) -> dict:
    from app.account_parser import parse_account_line
    raw_token = str(data.get("token") or "").strip()
    nickname = str(data.get("nickname") or "").strip()
    proxy = str(data.get("proxy") or "").strip()

    parsed = parse_account_line(raw_token)
    if parsed and parsed.token:
        token_to_store = encrypt_token(parsed.token)
        if not nickname and parsed.nickname_hint:
            nickname = parsed.nickname_hint
        if not proxy and parsed.proxy:
            proxy = parsed.proxy
    else:
        token_to_store = encrypt_token(raw_token)

    db = await get_db()
    try:
        refresh = data.get("refresh_token", "")
        await db.execute(
            "INSERT INTO accounts (nickname, token, enabled, refresh_token, proxy) VALUES (?, ?, ?, ?, ?)",
            (nickname, token_to_store, 1, encrypt_token(refresh), proxy),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM accounts WHERE nickname = ?", (nickname,))
        row = await cursor.fetchone()
        await log_action(
            "account_add",
            nickname,
            revert_payload={"action": "account_add", "params": {"account_id": row["id"] if row else 0}},
        )
        return _account_to_dict(row)
    finally:
        await db.close()


@router.post("/api/accounts/bulk-lurkers")
async def bulk_add_lurkers(data: dict[str, Any]) -> dict:
    """Массовое восстановление ботов по токенам, ники — из Twitch.

    body: {tokens: [str], role?: chatter|lurker, channel?: str, proxy?: str}. Каждый токен проверяется через
    /oauth2/validate → login становится ником. Битые/дубли пропускаются с отчётом,
    валидные добавляются включёнными с выбранной ролью.
    """
    raw_tokens = data.get("tokens")
    if not isinstance(raw_tokens, list) or not [t for t in raw_tokens if str(t or "").strip()]:
        return {"ok": False, "error": "tokens_required"}
    if len(raw_tokens) > 200:
        return {"ok": False, "error": "too_many_tokens"}
    role = str(data.get("role") or "lurker").strip()
    if role not in {"chatter", "lurker"}:
        return {"ok": False, "error": "invalid_role"}
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    if channel and not re.fullmatch(r"[a-z0-9_]{1,25}", channel):
        return {"ok": False, "error": "invalid_channel"}
    proxy = str(data.get("proxy") or "").strip()
    from app.twitch_helix import _strip_oauth, validate_token

    from app.account_parser import parse_account_line, parse_accounts_input, ParsedAccount

    parsed_accounts = parse_accounts_input(raw_tokens)
    if not parsed_accounts:
        parsed_accounts = []
        for raw in raw_tokens:
            entry_str = str(raw or "").strip()
            if entry_str:
                parsed_accounts.append(ParsedAccount(token=_strip_oauth(entry_str), raw=entry_str))

    added: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    seen_logins: set[str] = set()
    db = await get_db()
    try:
        for acc in parsed_accounts:
            bare = _strip_oauth(acc.token)
            if not bare:
                continue
            bot_proxy = (acc.proxy if acc.proxy else proxy).strip()
            masked = f"{bare[:4]}…{bare[-4:]}" if len(bare) > 8 else "…"
            if bare in seen_tokens:
                skipped.append({"token": masked, "reason": "duplicate_token"})
                continue
            seen_tokens.add(bare)
            info = await validate_token(bare)
            if not info or not info.get("login"):
                skipped.append({"token": masked, "reason": "invalid_token"})
                continue
            login = str(info["login"]).lower()
            if login in seen_logins:
                skipped.append({"token": masked, "nickname": login, "reason": "duplicate_batch"})
                continue
            cursor = await db.execute("SELECT id FROM accounts WHERE nickname = ?", (login,))
            if await cursor.fetchone():
                skipped.append({"token": masked, "nickname": login, "reason": "duplicate_nickname"})
                continue
            seen_logins.add(login)
            cursor = await db.execute(
                "INSERT INTO accounts (nickname, token, enabled, refresh_token, proxy, bot_role) "
                "VALUES (?, ?, 1, ?, ?, ?)",
                (login, encrypt_token(bare), "", bot_proxy, role),
            )
            account_id = cursor.lastrowid or 0
            if channel:
                await db.execute(
                    "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
                    (account_id, channel),
                )
            added.append({"id": account_id, "nickname": login})
        await db.commit()
    finally:
        await db.close()
    await log_action(
        "bulk_bots_restore",
        f"added={len(added)} skipped={len(skipped)} role={role} channel={channel or '-'}",
    )
    return {"ok": True, "added": added, "skipped": skipped, "role": role, "channel": channel or None}


@router.get("/api/accounts/{account_id}")
async def get_account(account_id: int) -> dict:
    """P8-A1: GET одного аккаунта (был только PUT/DELETE — вкладка «Общие»
    ловила 405 и не заполняла поля бота)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = await cursor.fetchone()
        return _account_to_dict(row) if row else {"error": "not found"}
    finally:
        await db.close()


@router.put("/api/accounts/{account_id}")
async def update_account(account_id: int, data: dict[str, Any]) -> dict:
    db = await get_db()
    try:
        fields = []
        values = []
        for key in ("nickname", "token", "enabled", "refresh_token", "proxy", "eventsub_enabled", "observation_only"):
            if key in data:
                v = data[key]
                if key in ("token", "refresh_token") and isinstance(v, str):
                    v = encrypt_token(v)
                fields.append(f"{key} = ?")
                values.append(v)
        if fields:
            values.append(account_id)
            await db.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?", values)
            await db.commit()
        if "enabled" in data and not bool(data["enabled"]):
            from app.director import revoke_worker
            await revoke_worker(account_id)
        # B1 (REWORK_PLAN): observation_only — единый источник accounts-колонка;
        # синхронизируем рантайм-гейт анализатора сразу (без рестарта).
        if "observation_only" in data:
            from app.server import chat_analyzer
            chat_analyzer.update_settings(account_id, {"observation_only": bool(data["observation_only"])})
            await chat_analyzer.persist_settings(account_id)
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = await cursor.fetchone()
        return _account_to_dict(row) if row else {"error": "not found"}
    finally:
        await db.close()


@router.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int) -> dict:
    from app.server import bot_manager
    await bot_manager.stop_bot(account_id)
    from app.director import revoke_worker
    await revoke_worker(account_id)
    db = await get_db()
    try:
        # §5 аудит: чистим таблицы без FK, чтобы не оставлять мусор
        await cleanup_account_children(db, account_id)
        await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/api/bulk/delete")
async def bulk_delete(data: dict[str, Any]) -> dict:
    """v12: масове видалення. body: {type: 'accounts'|'triggers'|'phrases'|'banlist'|'wordfilter', ids: [int]}"""
    entity_type = (data.get("type") or "").strip()
    ids = data.get("ids") or []
    if not entity_type or not ids or not isinstance(ids, list):
        return {"ok": False, "error": "type and ids[] required"}
    valid_types = {
        "accounts": ("accounts", True),   # (table, stop_bot)
        "triggers": ("triggers", False),
        "phrases": ("quick_phrases", False),
        "banlist": ("banlist", False),
        "wordfilter": ("word_filter", False),
    }
    if entity_type not in valid_types:
        return {"ok": False, "error": f"unknown type: {entity_type}"}
    table, should_stop = valid_types[entity_type]
    db = await get_db()
    try:
        deleted = 0
        for item_id in ids:
            try:
                if should_stop and entity_type == "accounts":
                    from app.server import bot_manager
                    await bot_manager.stop_bot(int(item_id))
                    from app.director import revoke_worker
                    await revoke_worker(int(item_id), db=db)
                    # §5 аудит: чистим таблицы без FK
                    await cleanup_account_children(db, int(item_id))
                await db.execute(f"DELETE FROM {table} WHERE id = ?", (int(item_id),))
                deleted += 1
            except Exception:
                pass
        await db.commit()
    finally:
        await db.close()
    await log_action("bulk_delete", f"{entity_type}: {deleted} deleted")
    return {"ok": True, "deleted": deleted}


@router.post("/api/accounts/{account_id}/toggle")
async def toggle_account(account_id: int) -> dict:
    """Переключает ТОЛЬКО флаг accounts.enabled.

    Owner report 27.09.2026: раньше toggle ещё и запускал/останавливал бота.
    Панель тогда слала `toggle` + `/start` одним кликом, бот поднимался дважды,
    второй `/start` отвечал «Уже запущен» → тост «Ошибка», а флаг enabled
    рассинхронизировался с живым ботом (бот в чате, `/api/send` → «Бот выключен»).
    Теперь состояние бота меняют только /start и /stop — они же владеют флагом.
    """
    db = await get_db()
    try:
        await db.execute("UPDATE accounts SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?", (account_id,))
        await db.commit()
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "not found"}
    return dict(row)


# ===================== v10.4.3: per-account AI override =====================

_AI_OVERRIDE_FIELDS = (
    "ai_provider_override",
    "ai_chat_model_override",
    "ai_vision_model_override",
    "openrouter_api_key_override",
    "ai_api_key_override",
    # v12: кастомний провайдер
    "custom_ai_base_url",
    "custom_ai_api_key",
)

# v10.4.3: все поддерживаемые провайдеры. Пустая строка = наследовать глобальный.
_VALID_AI_PROVIDERS = {"", "openrouter", "ollama", "gemini", "openai", "anthropic", "custom"}


def _row_get(row, name: str, default: str = "") -> str:
    try:
        if name in row.keys():
            return row[name] or default
    except Exception:
        pass
    return default


def _smart_routing_from_row(row) -> dict | None:
    """Q15d: распарсить per-бот smart-routing (JSON) или None = наследовать глобальный."""
    raw = _row_get(row, "ai_smart_routing_json")
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) and v else None


@router.get("/api/accounts/{account_id}/ai-override")
async def get_ai_override(account_id: int) -> dict:
    """Возвращает per-account override AI-настроек.
    Поля с ключами возвращаются как has_* флаги (не отдаём ключ в ответе).
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            f"SELECT {', '.join(_AI_OVERRIDE_FIELDS)}, ai_local_fallback, ai_smart_routing_json FROM accounts WHERE id = ?",
            (account_id,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "not found"}
    return {
        "ai_provider_override": _row_get(row, "ai_provider_override"),
        "ai_chat_model_override": _row_get(row, "ai_chat_model_override"),
        "ai_vision_model_override": _row_get(row, "ai_vision_model_override"),
        "has_openrouter_api_key_override": bool(_row_get(row, "openrouter_api_key_override")),
        "has_ai_api_key_override": bool(_row_get(row, "ai_api_key_override")),
        "custom_ai_base_url": _row_get(row, "custom_ai_base_url"),
        "has_custom_ai_api_key": bool(_row_get(row, "custom_ai_api_key")),
        # Q15c (E4): резерв «локальная Ollama» — ручной opt-in бота
        "ai_local_fallback": bool(_row_get(row, "ai_local_fallback")),
        # Q15d (E5): smart-routing чат-моделей per-бот (None = наследовать глобальный)
        "ai_smart_routing": _smart_routing_from_row(row),
        "supported_providers": ["openrouter", "ollama", "gemini", "openai", "anthropic", "custom"],
    }


@router.put("/api/accounts/{account_id}/ai-override")
async def update_ai_override(account_id: int, data: dict[str, Any]) -> dict:
    """Сохраняет per-account override и обновляет AIService cache.
    Пустая строка = очистить поле и использовать глобальный конфиг.
    """
    from app.server import ai_service
    from app.ai_service import AccountAIOverride

    db = await get_db()
    try:
        fields, values = [], []
        for f in _AI_OVERRIDE_FIELDS:
            if f not in data:
                continue
            v = str(data[f] or "").strip()
            # provider должен быть валидным из набора (пустая — наследовать глобальный)
            if f == "ai_provider_override":
                low = v.lower()
                if low.startswith("custom:"):
                    custom_name = low.split(":", 1)[1].strip()
                    if not custom_name:
                        continue
                    cur = await db.execute(
                        "SELECT name FROM custom_providers WHERE LOWER(name) = ? AND enabled = 1",
                        (custom_name,),
                    )
                    custom_row = await cur.fetchone()
                    if not custom_row:
                        continue
                    low = f"custom:{custom_row['name']}"
                elif low not in _VALID_AI_PROVIDERS:
                    continue
                v = low
            fields.append(f"{f} = ?")
            values.append(v)
        if fields:
            values.append(account_id)
            await db.execute(
                f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?", values,
            )
            await db.commit()
        if "ai_local_fallback" in data:
            await db.execute(
                "UPDATE accounts SET ai_local_fallback = ? WHERE id = ?",
                (1 if data.get("ai_local_fallback") else 0, account_id),
            )
            await db.commit()
        if "ai_smart_routing" in data:
            sr = data.get("ai_smart_routing") or {}
            clean: dict[str, Any] = {}
            if isinstance(sr, dict) and sr.get("enabled"):
                clean["enabled"] = True
                try:
                    clean["threshold"] = max(50, int(sr.get("threshold") or 600))
                except (TypeError, ValueError):
                    clean["threshold"] = 600
                for side in ("simple", "complex"):
                    pv = str(sr.get(f"{side}_provider") or "").strip().lower()
                    if pv.startswith("custom:"):
                        cname = pv.split(":", 1)[1].strip()
                        pv = ""
                        if cname:
                            cur_c = await db.execute(
                                "SELECT name FROM custom_providers WHERE LOWER(name) = ? AND enabled = 1",
                                (cname,),
                            )
                            row_c = await cur_c.fetchone()
                            if row_c:
                                pv = f"custom:{row_c['name']}"
                    elif pv not in _VALID_AI_PROVIDERS:
                        pv = ""
                    clean[f"{side}_provider"] = pv
                    clean[f"{side}_model"] = str(sr.get(f"{side}_model") or "").strip()
            # выключенный routing не сохраняется: бот наследует глобальный (legacy)
            sr_json = json.dumps(clean) if clean.get("enabled") else ""
            await db.execute(
                "UPDATE accounts SET ai_smart_routing_json = ? WHERE id = ?",
                (sr_json, account_id),
            )
            await db.commit()
        cursor = await db.execute(
            f"SELECT {', '.join(_AI_OVERRIDE_FIELDS)}, ai_local_fallback, ai_smart_routing_json FROM accounts WHERE id = ?",
            (account_id,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "not found"}

    # Применяем в живом AIService.
    ov = AccountAIOverride(
        provider=_row_get(row, "ai_provider_override"),
        chat_model=_row_get(row, "ai_chat_model_override"),
        vision_model=_row_get(row, "ai_vision_model_override"),
        openrouter_key=_row_get(row, "openrouter_api_key_override"),
        api_key=_row_get(row, "ai_api_key_override"),
        custom_base_url=_row_get(row, "custom_ai_base_url"),
        custom_api_key=_row_get(row, "custom_ai_api_key"),
        local_fallback=bool(_row_get(row, "ai_local_fallback")),
        smart_routing=_smart_routing_from_row(row) or {},
    )
    ai_service.set_account_override(account_id, ov)
    return {
        "ok": True,
        "ai_local_fallback": bool(_row_get(row, "ai_local_fallback")),
        "ai_smart_routing": _smart_routing_from_row(row),
        "ai_provider_override": _row_get(row, "ai_provider_override"),
        "ai_chat_model_override": _row_get(row, "ai_chat_model_override"),
        "ai_vision_model_override": _row_get(row, "ai_vision_model_override"),
        "has_openrouter_api_key_override": bool(_row_get(row, "openrouter_api_key_override")),
        "has_ai_api_key_override": bool(_row_get(row, "ai_api_key_override")),
        "custom_ai_base_url": _row_get(row, "custom_ai_base_url"),
        "has_custom_ai_api_key": bool(_row_get(row, "custom_ai_api_key")),
    }


# ===================== v10.4.3: per-account raid-follow =====================

_RAID_FOLLOW_FIELDS = (
    "raid_follow_enabled",
    "raid_follow_active_min",
    "raid_follow_active_max",
    "raid_follow_part_after",
)


@router.get("/api/accounts/{account_id}/raid-follow")
async def get_raid_follow(account_id: int) -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            f"SELECT {', '.join(_RAID_FOLLOW_FIELDS)} FROM accounts WHERE id = ?",
            (account_id,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "not found"}
    return {
        "enabled": bool(row["raid_follow_enabled"]),
        "active_min": int(row["raid_follow_active_min"] or 10),
        "active_max": int(row["raid_follow_active_max"] or 60),
        "part_after": bool(row["raid_follow_part_after"]),
    }


@router.put("/api/accounts/{account_id}/raid-follow")
async def update_raid_follow(account_id: int, data: dict[str, Any]) -> dict:
    """Сохраняет настройки raid-follow.
    data: {enabled?: bool, active_min?: int, active_max?: int, part_after?: bool}
    """
    db = await get_db()
    try:
        fields, values = [], []
        if "enabled" in data:
            fields.append("raid_follow_enabled = ?")
            values.append(1 if data["enabled"] else 0)
        if "active_min" in data:
            try:
                v = max(1, min(int(data["active_min"]), 720))
                fields.append("raid_follow_active_min = ?")
                values.append(v)
            except (TypeError, ValueError):
                pass
        if "active_max" in data:
            try:
                v = max(1, min(int(data["active_max"]), 720))
                fields.append("raid_follow_active_max = ?")
                values.append(v)
            except (TypeError, ValueError):
                pass
        if "part_after" in data:
            fields.append("raid_follow_part_after = ?")
            values.append(1 if data["part_after"] else 0)
        if fields:
            values.append(account_id)
            await db.execute(
                f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?", values,
            )
            await db.commit()
        cursor = await db.execute(
            f"SELECT {', '.join(_RAID_FOLLOW_FIELDS)} FROM accounts WHERE id = ?",
            (account_id,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "not found"}
    return {
        "ok": True,
        "enabled": bool(row["raid_follow_enabled"]),
        "active_min": int(row["raid_follow_active_min"] or 10),
        "active_max": int(row["raid_follow_active_max"] or 60),
        "part_after": bool(row["raid_follow_part_after"]),
    }


# ===================== PERSONA (v10.4.4) =====================

@router.get("/api/accounts/{account_id}/persona")
async def get_persona(account_id: int) -> dict:
    """Возвращает структурированную bio/persona бота."""
    from app.bot_persona import BotPersona

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT persona_json FROM accounts WHERE id = ?", (account_id,),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "not found"}
    raw = ""
    try:
        raw = row["persona_json"] if "persona_json" in row.keys() else ""
    except Exception:
        pass
    persona = BotPersona.from_json(raw)
    return {"ok": True, "persona": persona.to_dict()}


@router.put("/api/accounts/{account_id}/persona")
async def update_persona(account_id: int, data: dict[str, Any]) -> dict:
    """Сохраняет bio/persona бота.

    data: либо плоский dict с полями BotPersona, либо {"persona": {...}}.
    Возвращает нормализованный persona.
    """
    from app.bot_persona import BotPersona

    payload = data.get("persona") if isinstance(data, dict) and "persona" in data else data
    persona = BotPersona.from_dict(payload or {})
    db = await get_db()
    try:
        await db.execute(
            "UPDATE accounts SET persona_json = ? WHERE id = ?",
            (persona.to_json(), account_id),
        )
        await db.commit()
    finally:
        await db.close()
    # B1 (REWORK_PLAN): «Только наблюдает» в Характерe — тот же флаг, что и на карточке:
    # пишем в accounts + рантайм-гейт, чтобы все места UI были согласованы.
    if payload and "observation_only" in payload:
        from app.server import chat_analyzer
        from app.database import get_db as _get_db
        flag = bool(payload["observation_only"])
        _db = await _get_db()
        try:
            await _db.execute("UPDATE accounts SET observation_only = ? WHERE id = ?", (int(flag), account_id))
            await _db.commit()
        finally:
            await _db.close()
        chat_analyzer.update_settings(account_id, {"observation_only": flag})
        await chat_analyzer.persist_settings(account_id)
    return {"ok": True, "persona": persona.to_dict()}


# ===================== CHANNELS =====================

@router.get("/api/accounts/{account_id}/channels")
async def list_channels(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM channels WHERE account_id = ? ORDER BY id", (account_id,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/channels")
async def add_channel(account_id: int, data: dict[str, Any]) -> dict:
    db = await get_db()
    try:
        channel_name = str(data.get("channel_name") or "").lower().strip().lstrip("#")
        if not channel_name:
            return {"ok": False, "error": "Укажите канал"}
        await db.execute(
            "INSERT OR IGNORE INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1)",
            (account_id, channel_name),
        )
        await db.commit()
        return {"ok": True, "channel_name": channel_name}
    finally:
        await db.close()


@router.get("/api/channels/{channel_id}/dependencies")
async def channel_dependencies(channel_id: int) -> dict:
    """BC-4: что держится за связкой бот×канал — до удаления, без догадок."""
    from app.channel_admin import channel_dependencies as _deps, dependency_total
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = await cursor.fetchone()
        if not row:
            return {"ok": False, "code": "channel_not_found"}
        counts = await _deps(db, int(row["account_id"]), row["channel_name"])
        return {
            "ok": True,
            "channel_id": channel_id,
            "account_id": int(row["account_id"]),
            "channel_name": row["channel_name"],
            "counts": counts,
            "total": dependency_total(counts),
        }
    finally:
        await db.close()


@router.patch("/api/channels/{channel_id}")
async def update_channel(channel_id: int, data: dict[str, Any]) -> dict:
    """BC-1/BC-4: переименование канала или перенос его к другому боту.

    Данные channel-таблиц переносятся вместе с привязкой; при конфликте
    UNIQUE(account_id, channel) отказ без потери строк (force решает явно).
    """
    from app.channel_admin import move_channel, rename_channel
    rename_to = data.get("channel_name")
    target_account = data.get("account_id")
    force = bool(data.get("force"))
    if rename_to is None and target_account is None:
        return {"ok": False, "code": "nothing_to_update"}
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = await cursor.fetchone()
        if not row:
            return {"ok": False, "code": "channel_not_found"}
        account_id = int(row["account_id"])
        channel_name = row["channel_name"]

        if target_account is not None and int(target_account) != account_id:
            from app.server import bot_manager
            await bot_manager.leave_channel(account_id, channel_name)
            result = await move_channel(db, channel_id, int(target_account), force=force)
            if not result.get("ok"):
                return result
            from app.director import revoke_worker
            await revoke_worker(account_id, channel_name)
            return {**result, "channel_id": channel_id}

        if rename_to is not None:
            result = await rename_channel(db, account_id, channel_name, str(rename_to), force=force)
            if not result.get("ok"):
                return result
            return {**result, "channel_id": channel_id, "account_id": account_id}

        return {"ok": True, "channel_id": channel_id, "account_id": account_id}
    finally:
        await db.close()


@router.delete("/api/channels/{channel_id}")
async def remove_channel(channel_id: int, force: bool = False) -> dict:
    """Удалить канал у бота.

    Без ``force`` канал с зависимыми данными не удаляется: сначала возвращается
    их перечень, чтобы владелец удалял осознанно, а не «вместе с историей».
    """
    from app.channel_admin import channel_dependencies as _deps, delete_channel_rows, dependency_total
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = await cursor.fetchone()
        if row:
            counts = await _deps(db, int(row["account_id"]), row["channel_name"])
            if counts and not force:
                return {
                    "ok": False,
                    "code": "channel_has_dependencies",
                    "counts": counts,
                    "total": dependency_total(counts),
                }
            from app.server import bot_manager, stream_vision_manager
            await stream_vision_manager.stop(row["account_id"], row["channel_name"])
            await bot_manager.leave_channel(row["account_id"], row["channel_name"])
            from app.director import revoke_worker
            await revoke_worker(row["account_id"], row["channel_name"])
            await delete_channel_rows(db, int(row["account_id"]), row["channel_name"])
            await db.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ----- Stream Vision (что ИИ видит/слышит со стрима) -----

@router.get("/api/channels/{channel_id}/stream-vision")
async def stream_vision_get(channel_id: int) -> dict:
    """Состояние захвата стрима для конкретного канала."""
    from app.server import stream_vision_manager
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"ok": False, "error": "channel not found"}
    enabled = bool(row["stream_vision_enabled"]) if "stream_vision_enabled" in row.keys() else False
    return {
        "ok": True,
        "enabled": enabled,
        "running": stream_vision_manager.is_running(row["account_id"], row["channel_name"]),
        "channel_name": row["channel_name"],
    }


@router.post("/api/channels/{channel_id}/stream-vision/toggle")
async def stream_vision_toggle(channel_id: int, data: dict[str, Any]) -> dict:
    """Вкл/выкл захвата кадров и аудио для канала.

    Когда включено — фоновая задача каждые ``FRAME_INTERVAL``/``AUDIO_INTERVAL``
    секунд берёт кадр/аудио со стрима и эмитит ``stream_vision_result`` /
    ``stream_audio_result`` события в "AI Мозг".
    """
    from app.server import stream_vision_manager
    enabled = bool(data.get("enabled"))
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = await cursor.fetchone()
        if not row:
            return {"ok": False, "error": "channel not found"}
        await db.execute(
            "UPDATE channels SET stream_vision_enabled = ? WHERE id = ?",
            (1 if enabled else 0, channel_id),
        )
        await db.commit()
    finally:
        await db.close()

    if enabled:
        ok = await stream_vision_manager.start(row["account_id"], row["channel_name"])
    else:
        await stream_vision_manager.stop(row["account_id"], row["channel_name"])
        ok = True
    await log_action(
        "stream_vision_toggle",
        f"#{row['channel_name']} (acc={row['account_id']}) -> {'on' if enabled else 'off'}",
    )
    return {"ok": ok, "enabled": enabled}


# v10.4: глобальные настройки StreamVision (frame_interval_min, quality, pipelining…).
# Применяются ко всем каналам. Изменения вступают в силу со следующего кадра.
_STREAM_VISION_FIELDS = (
    "frame_interval", "frame_interval_min", "frame_interval_max",
    "audio_interval", "quality", "phash_threshold",
    "vision_chat_enabled", "vision_chat_min_words", "pipelining",
    # v10.4.2:
    "save_frames", "max_saved_frames", "quality_fallback",
    # v10.4.3 (OBS / custom source):
    "stream_source", "stream_video_input", "stream_audio_input",
    # v10.4.4: vision-cache (semantic-diff на описаниях).
    "vision_cache_enabled", "vision_cache_similarity_threshold",
    # v10.4.8: reasoning-stripper + Helix-контекст + детальный vision-промпт + диаризация.
    "vision_strip_reasoning",
    "vision_include_stream_info",
    "vision_prompt_style",
    "vision_prompt_override",
    "audio_diarization_mode",
    "audio_diarization_max_speakers",
)


@router.get("/api/stream-vision/config")
async def stream_vision_config_get() -> dict:
    from app.server import stream_vision_manager
    cfg = stream_vision_manager.cfg
    return {"ok": True, "config": {f: getattr(cfg, f) for f in _STREAM_VISION_FIELDS}}


@router.put("/api/stream-vision/config")
async def stream_vision_config_update(data: dict[str, Any]) -> dict:
    """Обновляет конфигурацию глобально, без рестарта приложения."""
    from app.server import stream_vision_manager
    cfg = stream_vision_manager.cfg
    changed = {}
    for f in _STREAM_VISION_FIELDS:
        if f not in data:
            continue
        val = data[f]
        if f in ("vision_chat_enabled", "pipelining", "save_frames", "quality_fallback", "vision_cache_enabled",
                 "vision_strip_reasoning", "vision_include_stream_info"):
            val = bool(val)
        elif f == "quality":
            val = str(val or "360p").strip() or "360p"
        elif f == "stream_source":
            val = (str(val or "twitch").strip().lower()) or "twitch"
            if val not in ("twitch", "custom"):
                val = "twitch"
        elif f in ("stream_video_input", "stream_audio_input"):
            val = str(val or "").strip()
        elif f == "vision_prompt_style":
            val = (str(val or "detailed").strip().lower()) or "detailed"
            if val not in ("basic", "detailed"):
                val = "detailed"
        elif f == "vision_prompt_override":
            # Кастомный промпт — обрезаем экстремальную длину, остальное — как есть.
            val = str(val or "")
            if len(val) > 4000:
                val = val[:4000]
        elif f == "audio_diarization_mode":
            val = (str(val or "off").strip().lower()) or "off"
            if val not in ("off", "heuristic", "whisperx"):
                val = "off"
        elif f == "vision_cache_similarity_threshold":
            try:
                val = max(0.0, min(float(val), 1.0))
            except (TypeError, ValueError):
                continue
        else:
            try:
                val = int(val)
            except (TypeError, ValueError):
                continue
            # Защитимся от глупых значений.
            if f == "frame_interval_min":
                val = max(1, min(val, 60))
            elif f == "frame_interval_max":
                val = max(5, min(val, 300))
            elif f == "frame_interval":
                val = max(1, min(val, 300))
            elif f == "audio_interval":
                val = max(5, min(val, 300))
            elif f == "phash_threshold":
                val = max(0, min(val, 30))
            elif f == "vision_chat_min_words":
                val = max(1, min(val, 50))
            elif f == "max_saved_frames":
                val = max(1, min(val, 1000))
            elif f == "audio_diarization_max_speakers":
                val = max(1, min(val, 10))
        setattr(cfg, f, val)
        changed[f] = val
    if changed:
        await log_action(
            "stream_vision_config_update",
            f"updated: {', '.join(f'{k}={v}' for k, v in changed.items())}",
        )
    return {"ok": True, "config": {f: getattr(cfg, f) for f in _STREAM_VISION_FIELDS}, "changed": changed}


# v10.4.8: HuggingFace-токен для whisperx-диаризации. Храним в БД (settings.huggingface_token).
# В get-ответе НЕ возвращаем сам токен — только factual `set`-флаг + длину, чтобы не утечь в логи/UI.
@router.get("/api/stream-vision/diarization/status")
async def stream_vision_diarization_status() -> dict:
    """Статус диаризации: текущий режим, набор пакетов, наличие HF-токена."""
    from app.server import stream_vision_manager
    cfg = stream_vision_manager.cfg

    # Проверяем установлен ли whisperx (импорт — без вызова).
    try:
        import whisperx  # noqa: F401
        whisperx_installed = True
    except Exception:
        whisperx_installed = False

    # HF-токен берём из БД (приоритет) или env.
    token_db = await get_setting("huggingface_token", "")
    token_env = os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN") or ""
    token_set = bool(token_db.strip() or token_env.strip())
    token_source = "db" if token_db.strip() else ("env" if token_env.strip() else "")

    return {
        "ok": True,
        "mode": cfg.audio_diarization_mode,
        "max_speakers": cfg.audio_diarization_max_speakers,
        "whisperx_installed": whisperx_installed,
        "hf_token_set": token_set,
        "hf_token_source": token_source,
    }


@router.put("/api/stream-vision/diarization/hf-token")
async def stream_vision_set_hf_token(data: dict[str, Any]) -> dict:
    """Сохраняет HuggingFace-токен в БД. Пустая строка — удаляет.

    Никогда не возвращает токен обратно. Лог-сообщение — только маска.
    """
    raw = str(data.get("token") or "").strip()
    await set_setting("huggingface_token", raw)
    masked = ""
    if raw:
        masked = raw[:4] + "…" + raw[-4:] if len(raw) > 12 else "(set)"
    await log_action(
        "diarization_hf_token_update",
        f"hf-token {'cleared' if not raw else f'set ({masked})'}",
    )
    return {"ok": True, "hf_token_set": bool(raw)}


@router.post("/api/stream-vision/diarization/install-whisperx")
async def stream_vision_install_whisperx() -> dict:
    """Запускает фоновую установку whisperx через pip.

    Возвращает результат (rc, stdout-tail, stderr-tail). На успех — `installed`: True.
    Это long-running операция (~500MB зависимостей), фронт держит спиннер.
    """
    import asyncio as _asyncio
    import sys as _sys

    # Если уже стоит — мгновенный no-op.
    try:
        import whisperx  # noqa: F401
        return {"ok": True, "installed": True, "already_installed": True}
    except Exception:
        pass

    # Стратегии: обычный → --user → --break-system-packages.
    strategies = (
        [_sys.executable, "-m", "pip", "install", "--quiet", "whisperx"],
        [_sys.executable, "-m", "pip", "install", "--quiet", "--user", "whisperx"],
        [_sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages", "whisperx"],
    )

    last_rc, last_out, last_err = -1, "", ""
    for strat in strategies:
        try:
            proc = await _asyncio.create_subprocess_exec(
                *strat,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            last_rc = proc.returncode or 0
            last_out = (stdout or b"").decode("utf-8", errors="replace")[-2000:]
            last_err = (stderr or b"").decode("utf-8", errors="replace")[-2000:]
            if last_rc == 0:
                # Проверим что импорт теперь работает (pip мог дать exit 0 без установки модуля).
                try:
                    # Сбрасываем кэш импортов, чтобы успешный pip --user сразу подхватился.
                    import importlib
                    importlib.invalidate_caches()
                    import whisperx  # noqa: F401
                    await log_action("diarization_whisperx_install", f"installed via {' '.join(strat[2:])}")
                    return {"ok": True, "installed": True, "strategy": " ".join(strat[2:])}
                except Exception as e:
                    last_err = f"pip rc=0 но импорт всё равно падает: {e}\n{last_err}"
                    continue
        except Exception as e:
            last_err = f"запуск pip провалился: {e}\n{last_err}"

    await log_action("diarization_whisperx_install_fail", f"rc={last_rc} err={last_err[:200]}")
    return {
        "ok": False,
        "installed": False,
        "rc": last_rc,
        "stdout": last_out,
        "stderr": last_err,
        "hint": "Возможно, нужно вручную: pip install whisperx (или --break-system-packages на Debian/Ubuntu)",
    }


# v10.4.9: one-shot test-run endpoints for "fast buttons".

@router.post("/api/stream-vision/test-vision/{account_id}/{channel}")
async def stream_vision_test_vision(account_id: int, channel: str) -> dict:
    """One-shot: grab frame + AI vision.  Returns description."""
    from app.server import stream_vision_manager
    try:
        result = await stream_vision_manager.test_once_vision(account_id, channel)
        await log_action("stream_vision_test_vision", f"#{channel} (acc={account_id}): ok={result.get('ok')}")
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/api/stream-vision/test-audio/{account_id}/{channel}")
async def stream_vision_test_audio(account_id: int, channel: str) -> dict:
    """One-shot: grab audio + whisper + diarization.  Returns transcript."""
    from app.server import stream_vision_manager
    try:
        result = await stream_vision_manager.test_once_audio(account_id, channel)
        await log_action("stream_vision_test_audio", f"#{channel} (acc={account_id}): ok={result.get('ok')}")
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ===================== BOT CONTROL =====================

async def _set_account_enabled(account_id: int, enabled: bool) -> None:
    """Синхронизировать accounts.enabled с намерением пользователя (start/stop)."""
    db = await get_db()
    try:
        await db.execute("UPDATE accounts SET enabled = ? WHERE id = ?", (1 if enabled else 0, account_id))
        await db.commit()
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/start")
async def start_bot(account_id: int, channel: str = "") -> dict:
    from app.server import bot_manager, eventsub_manager, chat_analyzer
    target_channel = str(channel or "").lower().strip().lstrip("#")
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        account = await cursor.fetchone()
        if not account:
            return {"error": "Аккаунт не найден"}

        if target_channel:
            cursor = await db.execute(
                "SELECT channel_name FROM channels WHERE account_id = ? AND LOWER(channel_name) = ? AND enabled = 1",
                (account_id, target_channel),
            )
            row = await cursor.fetchone()
            if not row:
                return {"error": f"Канал #{target_channel} не привязан к боту или отключён"}
            channels = [row["channel_name"]]
        else:
            cursor = await db.execute("SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1", (account_id,))
            channels = [r["channel_name"] for r in await cursor.fetchall()]
            if not channels:
                return {"error": "Нет каналов для подключения"}

        # Owner report 27.09.2026: кнопка «Старт» дёргала toggle (он уже поднимал
        # бота) и следом /start → бот_manager отвечал «Уже запущен» → {"ok": false}
        # без reason → на панели всплывала «Ошибка». Повторный старт занятого
        # бота — это успешный no-op.
        if bot_manager.is_running(account_id):
            status = bot_manager.get_status(account_id)
            await _set_account_enabled(account_id, True)
            return {"ok": True, "already": True,
                    "connected": bool(status.get("connected")),
                    "channels": status.get("channels") or channels}

        # OPS_PLAN §2: панель и standalone-бот не могут управлять одним ботом одновременно
        from app.instance_lock import acquire_account_lock, release_account_lock, lock_error
        if not acquire_account_lock(account_id):
            return {"error": lock_error(account_id)}

        # OPS_PLAN §1: инициализируем per-bot папку (идемпотентно, миграция read-only)
        try:
            from app.bot_dirs import migrate_bot_dir
            await migrate_bot_dir(account_id, account["nickname"])
        except Exception:
            logger.warning("bot dir init failed for #%s", account_id, exc_info=True)

        # OPS_PLAN §2/§3: общий wiring со standalone + регистрация желаемого состояния (watchdog)
        from app.bootstrap import start_account
        ok = await start_account(
            bot_manager, chat_analyzer, dict(account), channels,
            eventsub_manager=eventsub_manager,
        )
        if not ok:
            # Бот не запустился (уже запущен и т.п.) — не держим lock зря
            release_account_lock(account_id)
        if ok:
            # Старт = намерение «бот включён»: синхронизируем флаг, иначе после
            # рестарта панели autoconnect его не поднимет, а /api/send будет
            # отвечать «Бот выключен» (owner report 27.09.2026).
            await _set_account_enabled(account_id, True)
            await log_action("Бот запущен", f"{account['nickname']} → {', '.join(channels)}")
        return {"ok": ok}
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/stop")
async def stop_bot(account_id: int) -> dict:
    from app.server import bot_manager, eventsub_manager
    # OPS_PLAN §3: явная остановка пользователя снимает желаемое состояние,
    # чтобы watchdog не переподнял бота
    bot_manager.set_desired(account_id, None)
    ok = await bot_manager.stop_bot(account_id)
    await eventsub_manager.stop_for_account(account_id)
    # Симметрично /start: стоп = «бот выключен» во всех местах (БД + панель).
    await _set_account_enabled(account_id, False)
    from app.director import revoke_worker
    try:
        await revoke_worker(account_id)
    except Exception:
        logger.debug("revoke_worker on stop failed for #%s", account_id, exc_info=True)
    # OPS_PLAN §2: освобождаем instance-lock
    try:
        from app.instance_lock import release_account_lock
        release_account_lock(account_id)
    except Exception:
        pass
    if ok:
        await log_action("Бот остановлен", str(account_id))
    # BUGFIX: остановка незапущенного бота — валидный no-op, а не ошибка.
    # Раньше {"ok": false} превращался в тост «Ошибка: OK» и кнопку Стоп
    # у включённого, но ещё не поднятого watchdog'ом бота.
    return {"ok": True, "was_running": ok}


@router.post("/api/bots/start-all")
async def start_all_bots() -> dict:
    """Массовый запуск всех активных ботов с небольшой паузой."""
    import asyncio
    from app.server import bot_manager, eventsub_manager, chat_analyzer
    from app.instance_lock import acquire_account_lock, release_account_lock
    from app.bootstrap import start_account

    db = await get_db()
    started = 0
    errors = []
    try:
        cur = await db.execute("SELECT * FROM accounts WHERE enabled = 1")
        accounts = await cur.fetchall()
        for acc in accounts:
            aid = acc["id"]
            if bot_manager.is_running(aid):
                continue
            cur_ch = await db.execute("SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1", (aid,))
            channels = [r["channel_name"] for r in await cur_ch.fetchall()]
            if not channels:
                continue
            if not acquire_account_lock(aid):
                continue
            try:
                ok = await start_account(
                    bot_manager, chat_analyzer, dict(acc), channels,
                    eventsub_manager=eventsub_manager,
                )
                if ok:
                    started += 1
                    await _set_account_enabled(aid, True)
                    await asyncio.sleep(0.15)
                else:
                    release_account_lock(aid)
            except Exception as e:
                release_account_lock(aid)
                errors.append(f"{acc['nickname']}: {str(e)[:100]}")
    finally:
        await db.close()

    await log_action("Массовый запуск ботов", f"Запущено: {started} из {len(accounts)}")
    return {"ok": True, "started": started, "total": len(accounts), "errors": errors}


@router.post("/api/bots/stop-all")
async def stop_all_bots() -> dict:
    """Массовая остановка всех запущенных ботов."""
    from app.server import bot_manager, eventsub_manager
    from app.director import revoke_worker
    from app.instance_lock import release_account_lock

    running_ids = list(bot_manager._bots.keys()) if hasattr(bot_manager, "_bots") else list(getattr(bot_manager, "running", []))
    stopped = 0
    for aid in running_ids:
        bot_manager.set_desired(aid, None)
        ok = await bot_manager.stop_bot(aid)
        await eventsub_manager.stop_for_account(aid)
        await _set_account_enabled(aid, False)
        try:
            await revoke_worker(aid)
        except Exception:
            pass
        try:
            release_account_lock(aid)
        except Exception:
            pass
        if ok:
            stopped += 1

    await log_action("Массовая остановка ботов", f"Остановлено: {stopped}")
    return {"ok": True, "stopped": stopped}


@router.get("/api/accounts/{account_id}/status")
async def bot_status(account_id: int) -> dict:
    from app.server import bot_manager
    return bot_manager.get_status(account_id)


@router.get("/api/bots/status")
async def all_bots_status() -> dict:
    from app.server import bot_manager
    return bot_manager.get_all_statuses()


# ===================== MESSAGES =====================

@router.post("/api/send")
async def send_message(data: dict[str, Any]) -> dict:
    account_id = data.get("account_id")
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    text = str(data.get("text") or "").strip()
    if not account_id or not channel:
        return {"ok": False, "reason": "invalid_target", "error": "Укажите бота и канал"}
    if not text:
        return {"ok": False, "reason": "empty_message", "error": "Сообщение не может быть пустым"}
    from app.server import bot_manager
    from app.bot_logs import log_per_bot

    db = await get_db()
    try:
        row = await db.execute("SELECT enabled FROM accounts WHERE id = ?", (int(account_id),))
        acc = await row.fetchone()
        if not acc:
            return {"ok": False, "reason": "bot_not_found", "error": "Бот не найден"}
        if not acc["enabled"]:
            # Owner report 27.09.2026: бот сидит в канале, а флаг accounts.enabled
            # остался 0 (двойной вызов toggle+start на кнопке «Старт» разводил
            # флаг и живое состояние) → отправка невозможна. Флаг — намерение,
            # фактическое подключение — истина: если бот реально connected,
            # отправляем; иначе честно отказываем.
            if not bot_manager.get_status(int(account_id)).get("connected"):
                return {"ok": False, "reason": "bot_disabled", "error": "Бот выключен"}
        ch_row = await db.execute(
            "SELECT enabled FROM channels WHERE account_id = ? AND channel_name = ?",
            (int(account_id), channel),
        )
        ch = await ch_row.fetchone()
        if ch and not ch["enabled"]:
            # То же для канала: подключённый канал отключать нельзя.
            live = bot_manager.get_status(int(account_id))
            if channel not in {str(c).lstrip("#").lower() for c in (live.get("channels") or [])}:
                return {"ok": False, "reason": "channel_disabled", "error": f"Канал #{channel} отключён"}
        # Исходящая модерация: слово из word_filter бота блокирует отправку (план §5.2).
        # PLAN §2.1: учитываются глобальные слова и слова канала получателя.
        wf = await db.execute(
            "SELECT word FROM word_filter WHERE account_id = ? AND (channel = '' OR channel = ?)",
            (int(account_id), (channel or "").lower().lstrip("#")),
        )
        bad_words = [r["word"].lower() for r in await wf.fetchall()]
    finally:
        await db.close()

    low = text.lower()
    if any(w and w in low for w in bad_words):
        await log_per_bot(int(account_id), channel, "system", "Отправка заблокирована модерацией", level="warning")
        return {"ok": False, "reason": "moderation_blocked", "error": "Сообщение заблокировано фильтром слов"}

    # v14 MODERATION_PLAN §3: исходящая модерация ручных отправок через движок.
    from app import moderation as _mod
    _out = await _mod.check_outgoing(int(account_id), channel, text, source="api_send")
    if not _out.ok:
        await log_per_bot(int(account_id), channel, "system",
                          f"Ручная отправка заблокирована автомодерацией ({_mod.summarize(_out.verdicts)})",
                          level="warning")
        return {"ok": False, "reason": "moderation_blocked",
                "error": "Сообщение заблокировано автомодерацией (правила модерации)"}
    text = _out.text

    result = await bot_manager.send_message_detailed(int(account_id), channel, text)
    if not result.get("ok"):
        await log_per_bot(
            int(account_id), channel, "system",
            f"Не отправлено ({result.get('reason')}): {result.get('error', '')}", level="error",
        )
    return result


@router.post("/api/accounts/{account_id}/join")
async def join_channel(account_id: int, data: dict[str, Any]) -> dict:
    from app.server import bot_manager
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    if not channel:
        return {"ok": False, "error": "Укажите канал"}

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO channels (account_id, channel_name, enabled) VALUES (?, ?, 1) "
            "ON CONFLICT(account_id, channel_name) DO UPDATE SET enabled = 1",
            (account_id, channel),
        )
        await db.commit()
    finally:
        await db.close()

    ok = await bot_manager.join_channel(account_id, channel)
    return {"ok": ok}


@router.post("/api/accounts/{account_id}/leave")
async def leave_channel(account_id: int, data: dict[str, Any]) -> dict:
    from app.server import bot_manager
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    if not channel:
        return {"ok": False, "error": "Укажите канал"}
    ok = await bot_manager.leave_channel(account_id, channel)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE channels SET enabled = 0 WHERE account_id = ? AND channel_name = ?",
            (account_id, channel),
        )
        await db.commit()
    finally:
        await db.close()
    from app.director import revoke_worker
    await revoke_worker(account_id, channel)
    return {"ok": ok}


# ===================== LOGS =====================

@router.get("/api/logs")
async def get_logs(limit: int = 100, channel: str = "", account_id: int = 0) -> list[dict]:
    """История чата. §25.1: фильтры по каналу и боту для вкладки «Чат»."""
    ch = (channel or "").strip().lstrip("#").lower()
    where: list[str] = []
    params: list[Any] = []
    if ch:
        where.append("LOWER(channel) = ?")
        params.append(ch)
    if account_id:
        where.append("account_id = ?")
        params.append(int(account_id))
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    limit = max(1, min(500, int(limit)))
    db = await get_db()
    try:
        cursor = await db.execute(
            f"SELECT * FROM chat_log{where_sql} ORDER BY id DESC LIMIT ?",
            tuple(params + [limit]),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        await db.close()


# ===================== AI SETTINGS =====================

_AI_SECRET_FIELDS = {
    "openrouter_key", "gemini_key", "openai_key", "anthropic_key",
    "custom_ai_api_key",
}


def _mask_secret(value: Any) -> str:
    value = str(value or "")
    if len(value) <= 8:
        return "configured" if value else ""
    return f"{value[:4]}...{value[-4:]}"


def _safe_ai_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return panel config without returning credential material."""
    safe = dict(config)
    for field in _AI_SECRET_FIELDS:
        value = safe.pop(field, "")
        safe[f"{field}_masked"] = _mask_secret(value)
        safe[f"has_{field}"] = bool(value)
    return safe

@router.get("/api/ai/config")
async def get_ai_config() -> dict:
    from app.server import ai_service
    cfg = ai_service.get_config()
    return _safe_ai_config(cfg)


@router.put("/api/ai/config")
async def update_ai_config(data: dict[str, Any]) -> dict:
    from app.server import ai_service
    # A blank or omitted secret means "keep the current secret". This also
    # prevents the panel from accidentally clearing credentials on partial PUT.
    update = dict(data)
    for field in _AI_SECRET_FIELDS:
        if field not in update or update[field] in (None, ""):
            update.pop(field, None)
    cfg = ai_service.update_config(update)
    # Сохраняем в БД
    db = await get_db()
    try:
        for key, value in cfg.items():
            if key in _AI_SECRET_FIELDS:
                continue
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"ai_{key}", str(value)),
            )
        await db.commit()
    finally:
        await db.close()
        # Credentials are persisted separately, never via the response DTO.
        for key in _AI_SECRET_FIELDS:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"ai_{key}", str(getattr(ai_service, {
                    "custom_ai_api_key": "custom_api_key",
                }.get(key, key), "") or "")),
            )
        await db.commit()
    return _safe_ai_config(cfg)


@router.post("/api/ai/test")
async def test_ai_connection(data: dict[str, Any] | None = None) -> dict:
    from app.server import ai_service
    provider = data.get("provider") if isinstance(data, dict) else None
    return await ai_service.test_connection(provider=provider)


@router.get("/api/offline/config")
async def get_offline_config() -> dict:
    from app.server import ai_service
    return {"enabled": bool(ai_service.offline_mode), "provider": "ollama", "tts_provider": "piper"}


@router.put("/api/offline/config")
async def update_offline_config(data: dict[str, Any]) -> dict:
    from app.server import ai_service
    enabled = bool(data.get("enabled", False))
    ai_service.update_config({"offline_mode": enabled})
    db = await get_db()
    try:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('offline_mode', ?)", ("1" if enabled else "0",))
        await db.commit()
    finally:
        await db.close()
    return {"enabled": enabled, "provider": "ollama", "tts_provider": "piper"}


# ===================== §25.5: VISION TEST =====================

@router.post("/api/ai/test-vision")
async def test_vision(data: dict[str, Any] | None = None) -> dict:
    """§25.5: проверка vision-модели заглушкой-картинкой (без панели это не проверить)."""
    import io as _io
    import base64 as _b64
    from app.server import ai_service
    try:
        from PIL import Image as _Image
    except ImportError:
        return {"ok": False, "error": "Pillow не установлен"}
    # 8x8 красный PNG
    png = _b64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAGElEQVR4nGP8z8Dwn4EIwESMolG"
        "FzgEAbqQECQzRZlMAAAAASUVORK5CYII="
    )
    img = _Image.open(_io.BytesIO(png)).convert("RGB")
    try:
        text = await ai_service.analyze_image(img, "Что на картинке? Ответь одним словом.")
        if text:
            return {"ok": True, "response": text[:200]}
        detail = (getattr(ai_service, "last_vision_error", "") or "").strip()
        if detail:
            return {"ok": False, "error": f"Vision вернул пустой ответ: {detail}"}
        return {"ok": False, "error": "Vision вернул пустой ответ — проверьте Vision-модель и ключ"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


# ===================== §25.4: CUSTOM PROVIDERS =====================

def _mask_provider_key(value: Any) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 8:
        return "configured"
    return f"{value[:4]}...{value[-4:]}"


async def _load_custom_providers() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT id, name, base_url, api_key, models, vision_models, enabled FROM custom_providers ORDER BY name")
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    return rows


async def _refresh_custom_providers_cache() -> None:
    """После CRUD — обновить кэш в ai_service (single source of truth — БД)."""
    from app.server import ai_service
    try:
        ai_service.set_custom_providers(await _load_custom_providers())
    except Exception:
        pass


@router.get("/api/custom-providers")
async def list_custom_providers() -> dict:
    """Список кастомных провайдеров без секретов (has_api_key вместо ключа)."""
    rows = await _load_custom_providers()
    for r in rows:
        r["has_api_key"] = bool(r.pop("api_key", ""))
        r["models"] = _parse_provider_models(r.get("models"))
        r["vision_models"] = _parse_provider_models(r.get("vision_models"))
    return {"items": rows}

def _parse_provider_models(raw) -> list:
    """JSON-список моделей провайдера (или строки через запятую — legacy)."""
    models = raw or "[]"
    if isinstance(models, str):
        try:
            models = json.loads(models)
        except (TypeError, ValueError):
            models = [m.strip() for m in models.split(",") if m.strip()]
    return [str(m).strip() for m in (models or []) if str(m).strip()]


@router.post("/api/custom-providers")
async def create_custom_provider(data: dict[str, Any]) -> dict:
    name = str(data.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "Укажите имя провайдера"}
    base_url = str(data.get("base_url") or "").strip().rstrip("/")
    models = data.get("models") or []
    if isinstance(models, str):
        models = [m.strip() for m in models.replace("\n", "\n").split("\n") if m.strip()]
    models = [str(m).strip() for m in models if str(m).strip()]
    vision_models = data.get("vision_models") or []
    if isinstance(vision_models, str):
        vision_models = [m.strip() for m in vision_models.replace("\r", "").split("\n") if m.strip()]
    vision_models = [str(m).strip() for m in vision_models if str(m).strip()]
    db = await get_db()
    try:
        try:
            cur = await db.execute(
                "INSERT INTO custom_providers (name, base_url, api_key, models, vision_models, enabled) VALUES (?, ?, ?, ?, ?, ?)",
                (name, base_url, str(data.get("api_key") or ""), json.dumps(models), json.dumps(vision_models), 1 if data.get("enabled", True) else 0),
            )
            await db.commit()
        except Exception as exc:
            if "UNIQUE" in str(exc):
                return {"ok": False, "error": f"Провайдер '{name}' уже существует"}
            raise
        pid = cur.lastrowid or 0
    finally:
        await db.close()
    await _refresh_custom_providers_cache()
    await log_action("custom_provider_add", name)
    return {"ok": True, "id": pid}


@router.put("/api/custom-providers/{provider_id}")
async def update_custom_provider(provider_id: int, data: dict[str, Any]) -> dict:
    db = await get_db()
    try:
        row = await db.execute("SELECT api_key FROM custom_providers WHERE id = ?", (provider_id,))
        existing = await row.fetchone()
        if not existing:
            return {"ok": False, "error": "Провайдер не найден"}
        sets: list[str] = []
        values: list[Any] = []
        if "name" in data:
            name = str(data["name"] or "").strip()
            if not name:
                return {"ok": False, "error": "Укажите имя провайдера"}
            sets.append("name = ?"); values.append(name)
        if "base_url" in data:
            sets.append("base_url = ?"); values.append(str(data["base_url"] or "").strip().rstrip("/"))
        # Пустой ключ = оставить старый (защита от затирания при частичном сохранении)
        if data.get("api_key"):
            sets.append("api_key = ?"); values.append(str(data["api_key"]))
        if "models" in data:
            models = data.get("models") or []
            if isinstance(models, str):
                models = [m.strip() for m in models.split("\n") if m.strip()]
            models = [str(m).strip() for m in models if str(m).strip()]
            sets.append("models = ?"); values.append(json.dumps(models))
        if "vision_models" in data:
            vm = data.get("vision_models") or []
            if isinstance(vm, str):
                vm = [m.strip() for m in vm.split("\n") if m.strip()]
            vm = [str(m).strip() for m in vm if str(m).strip()]
            sets.append("vision_models = ?"); values.append(json.dumps(vm))
        if "enabled" in data:
            sets.append("enabled = ?"); values.append(1 if data["enabled"] else 0)
        if sets:
            values.append(provider_id)
            await db.execute(f"UPDATE custom_providers SET {', '.join(sets)} WHERE id = ?", tuple(values))
            await db.commit()
    finally:
        await db.close()
    await _refresh_custom_providers_cache()
    await log_action("custom_provider_update", str(data.get("name") or provider_id))
    return {"ok": True}


@router.delete("/api/custom-providers/{provider_id}")
async def delete_custom_provider(provider_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM custom_providers WHERE id = ?", (provider_id,))
        await db.commit()
    finally:
        await db.close()
    await _refresh_custom_providers_cache()
    await log_action("custom_provider_delete", str(provider_id))
    return {"ok": True}


@router.get("/api/providers/status")
async def provider_status() -> dict:
    """Unified, non-secret provider state for the settings panel."""
    from app.server import ai_service
    from app import twitch_credentials

    cfg = ai_service.get_config()
    ollama_status = await ai_service.ollama_status()
    ai = {}
    for provider in ai_service.SUPPORTED_PROVIDERS:
        model, _vision, key = ai_service._provider_defaults(provider)
        ai[provider] = {
            "configured": bool(key or provider in {"ollama", "custom"} and cfg.get("ollama_host" if provider == "ollama" else "custom_ai_base_url")),
            "model": model,
            "host": cfg.get("ollama_host") if provider == "ollama" else cfg.get("custom_ai_base_url") if provider == "custom" else None,
        }
        if provider == "ollama":
            ai[provider].update(ollama_status)
    # §25.4: именованные кастомные провайдеры попадают в статус
    for name in ai_service.custom_provider_names():
        cfg = ai_service.get_custom_provider(name) or {}
        ai[f"custom:{name}"] = {
            "configured": bool(cfg.get("base_url")),
            "model": (cfg.get("models") or [""])[0],
            "host": cfg.get("base_url") or None,
        }
    db = await get_db()
    try:
        cur = await db.execute("SELECT value FROM settings WHERE key IN ('tts_elevenlabs_api_key', 'elevenlabs_api_key') ORDER BY key LIMIT 1")
        eleven = await cur.fetchone()
        cur = await db.execute("SELECT provider FROM tts_settings WHERE id = 1")
        tts = await cur.fetchone()
    finally:
        await db.close()
    return {"ai": ai, "twitch": twitch_credentials.get_status(),
            "offline_mode": bool(ai_service.offline_mode),
            "tts": {"provider": tts["provider"] if tts else "web_speech",
                    "elevenlabs_configured": bool(eleven and eleven["value"]),
                    "piper_available": bool(__import__("shutil").which("piper"))}}


@router.post("/api/providers/test")
async def test_provider(data: dict[str, Any]) -> dict:
    """Test one provider by name; does not change the active configuration."""
    from app.server import ai_service
    provider = str(data.get("provider") or "").strip().lower()
    if provider in ai_service.SUPPORTED_PROVIDERS:
        result = await ai_service.test_connection(provider)
        return {"provider": provider, **result}
    if provider == "twitch":
        return {"provider": provider, "ok": bool(twitch_credentials.is_helix_configured()), **twitch_credentials.get_status()}
    if provider == "web_speech":
        return {"provider": provider, "ok": True, "message": "Browser SpeechSynthesis is available"}
    if provider in {"piper", "elevenlabs", "xtts"}:
        status = await provider_status()
        configured = status["tts"].get(f"{provider}_configured", False) or provider == "piper" and status["tts"]["piper_available"]
        return {"provider": provider, "ok": bool(configured), "error": "Provider is not configured" if not configured else ""}
    return {"provider": provider, "ok": False, "error": "Unsupported provider"}


# ===================== CHAT ANALYZER =====================

@router.get("/api/accounts/{account_id}/analyzer")
async def get_analyzer_settings(account_id: int) -> dict:
    from app.server import chat_analyzer
    return chat_analyzer.get_settings(account_id)


@router.put("/api/accounts/{account_id}/analyzer")
async def update_analyzer_settings(account_id: int, data: dict[str, Any]) -> dict:
    from app.server import chat_analyzer
    return chat_analyzer.update_settings(account_id, data)


# v10.4.1: пресеты «режима бота» — один клик меняет и chat_analyzer, и stream_vision.
# Названия и значения зафиксированы в коде, чтобы UI знал что отправлять.
ANALYZER_PRESETS: dict[str, dict[str, Any]] = {
    # 💬 Только из чата — как было «классически».
    "chat_only": {
        "label": "💬 Только из чата",
        "analyzer": {
            "context_source_chat": True,
            "context_source_stream": False,
            "context_source_streamer": False,
            "use_channel_context": False,
            "buffer_size": 50,
            "chat_window_size": 30,
            "use_db_chat_fallback": True,
        },
        "stream_vision": {},  # не трогаем
    },
    # ⚡ Realtime со стрима — только vision/audio + streamer-инфо, минимум кадрового интервала.
    "realtime_stream": {
        "label": "⚡ Realtime со стрима",
        "analyzer": {
            "context_source_chat": False,
            "context_source_stream": True,
            "context_source_streamer": True,
            "use_channel_context": True,
            # Окно чата сокращаем — он почти не используется, но для коротких фолбэков пригодится.
            "buffer_size": 30,
            "chat_window_size": 10,
            "use_db_chat_fallback": True,
        },
        "stream_vision": {
            "frame_interval_min": 3,
            "frame_interval_max": 30,
            "audio_interval": 30,
            "quality": "360p",
            "pipelining": True,
        },
    },
    # 🎬 Полный контекст — все источники включены, большое окно.
    "full_context": {
        "label": "🎬 Полный контекст",
        "analyzer": {
            "context_source_chat": True,
            "context_source_stream": True,
            "context_source_streamer": True,
            "use_channel_context": True,
            "buffer_size": 100,
            "chat_window_size": 50,
            "use_db_chat_fallback": True,
        },
        "stream_vision": {
            "frame_interval_min": 5,
            "audio_interval": 30,
            "quality": "360p",
            "pipelining": True,
        },
    },
}


@router.get("/api/analyzer-presets")
async def list_analyzer_presets() -> dict:
    """v10.4.1: список доступных пресетов «режима бота» (для UI)."""
    return {
        "ok": True,
        "presets": [
            {
                "id": pid,
                "label": p["label"],
                "analyzer": p["analyzer"],
                "stream_vision": p["stream_vision"],
            }
            for pid, p in ANALYZER_PRESETS.items()
        ],
    }


@router.post("/api/accounts/{account_id}/analyzer-presets/{preset_id}")
async def apply_analyzer_preset(account_id: int, preset_id: str) -> dict:
    """v10.4.1: применить пресет к аккаунту + (опционально) к глобальному Stream Vision.

    1. ``analyzer`` — записывается в настройки конкретного аккаунта.
    2. ``stream_vision`` (если непустой в пресете) — обновляет глобальную конфигурацию.
    """
    preset = ANALYZER_PRESETS.get(preset_id)
    if not preset:
        return {"ok": False, "error": f"unknown preset: {preset_id}"}

    from app.server import chat_analyzer, stream_vision_manager

    chat_analyzer.update_settings(account_id, preset["analyzer"])

    sv_changed: dict[str, Any] = {}
    sv_overrides = preset.get("stream_vision") or {}
    if sv_overrides:
        cfg = stream_vision_manager.cfg
        for f, val in sv_overrides.items():
            if hasattr(cfg, f):
                setattr(cfg, f, val)
                sv_changed[f] = val

    await log_action(
        "analyzer_preset_apply",
        f"acc={account_id} preset={preset_id} ({preset['label']})",
        revert_payload={"account_id": account_id, "preset_id": preset_id},
    )
    return {
        "ok": True,
        "preset": preset_id,
        "label": preset["label"],
        "analyzer": chat_analyzer.get_settings(account_id),
        "stream_vision_changed": sv_changed,
    }


# v10.4.1: «что бот сейчас видит/слышит на стриме» — для UI «Живого чата».
@router.get("/api/stream-vision/last-observation/{account_id}/{channel}")
async def stream_vision_last_observation(
    account_id: int, channel: str, max_age_sec: int = 180
) -> dict:
    from app.server import stream_vision_manager
    obs = stream_vision_manager.get_last_observation(
        account_id, channel.lstrip("#").lower(), max_age_sec=max_age_sec
    )
    if not obs:
        return {"ok": True, "observation": None}
    return {
        "ok": True,
        "observation": {
            "description": obs.get("description") or "",
            "transcript": obs.get("transcript") or "",
            # v10.4.2: относительный URL к последнему сохранённому кадру ("/frames/...")
            "frame_url": obs.get("frame_url") or "",
            "at": obs.get("at"),
            "age_sec": int(time.time() - float(obs.get("at") or 0)),
        },
    }


@router.get("/api/stream-vision/last-observation-by-channel/{channel}")
async def stream_vision_last_observation_by_channel(
    channel: str, max_age_sec: int = 180
) -> dict:
    """v10.4.1: то же, но без account_id — ищем самое свежее наблюдение
    по каналу среди всех активных аккаунтов. Удобно для UI «Живого чата»."""
    from app.server import stream_vision_manager
    ch = channel.lstrip("#").lower()
    best: dict[str, Any] | None = None
    best_at: float = 0.0
    best_account: int | None = None
    # _last_observation: dict[(account_id, channel), {description, transcript, at}]
    for (acc, c), obs in stream_vision_manager._last_observation.items():
        if c != ch:
            continue
        at = float(obs.get("at") or 0)
        if at <= best_at:
            continue
        if max_age_sec > 0 and (time.time() - at) > max_age_sec:
            continue
        best, best_at, best_account = obs, at, acc
    if not best:
        return {"ok": True, "observation": None}
    return {
        "ok": True,
        "account_id": best_account,
        "observation": {
            "description": best.get("description") or "",
            "transcript": best.get("transcript") or "",
            "frame_url": best.get("frame_url") or "",
            "at": best.get("at"),
            "age_sec": int(time.time() - float(best.get("at") or 0)),
        },
    }


# v10.4.2: архив последних кадров по каналу — для вкладки «📸 Архив кадров».
@router.get("/api/stream-vision/frames/{channel}")
async def stream_vision_frames(channel: str, limit: int = 50) -> dict:
    """Возвращает список сохранённых JPG для канала, свежие вперёд."""
    from app.stream_vision import FRAMES_DIR
    ch = channel.lstrip("#").lower()
    ch_dir = FRAMES_DIR / ch
    if not ch_dir.exists():
        return {"ok": True, "channel": ch, "frames": []}
    limit = max(1, min(int(limit or 50), 500))
    try:
        files = sorted(
            (p for p in ch_dir.glob("*.jpg") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]
    except OSError:
        return {"ok": True, "channel": ch, "frames": []}
    frames = []
    for p in files:
        try:
            stat = p.stat()
        except OSError:
            continue
        # Имя файла — unix-ms (из _save_frame_to_disk).
        try:
            ts_ms = int(p.stem)
        except ValueError:
            ts_ms = int(stat.st_mtime * 1000)
        frames.append({
            "url": f"/frames/{ch}/{p.name}",
            "name": p.name,
            "size_bytes": stat.st_size,
            "ts_ms": ts_ms,
            "age_sec": int(time.time() - ts_ms / 1000),
        })
    return {"ok": True, "channel": ch, "frames": frames}


@router.post("/api/accounts/{account_id}/analyzer/start")
async def start_auto_chat(account_id: int, data: dict[str, Any]) -> dict:
    """Запускает фоновый авто-чат для аккаунта на указанном канале."""
    from app.server import chat_analyzer, bot_manager

    channel = data.get("channel", "").lower().strip().lstrip("#")
    if not channel:
        return {"error": "Укажите канал"}

    status = bot_manager.get_status(account_id)
    nickname = status.get("nickname", "bot")

    chat_analyzer.update_settings(account_id, {"enabled": True, "auto_chat": True})
    await chat_analyzer.start_auto_chat(account_id, channel, nickname)
    return {"ok": True, "message": f"Авто-чат запущен для #{channel}"}


# ===================== TRIGGERS =====================

@router.get("/api/accounts/{account_id}/triggers")
async def list_triggers(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM triggers WHERE account_id = ? ORDER BY id", (account_id,))
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/triggers")
async def create_trigger(account_id: int, data: dict[str, Any]) -> dict:
    keyword = str(data.get("keyword") or "").strip()
    if not keyword:
        return {"ok": False, "error": "Укажите слово или фразу"}
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO triggers (account_id, keyword, response, use_ai, enabled, channel) VALUES (?, ?, ?, ?, 1, ?)",
            (account_id, keyword, str(data.get("response") or ""), 1 if data.get("use_ai", True) else 0, channel),
        )
        await db.commit()
        tid = cur.lastrowid or 0
    finally:
        await db.close()
    await log_action(
        "trigger_add",
        f"#{account_id} {keyword}",
        revert_payload={"action": "trigger_add", "params": {"trigger_id": tid}},
    )
    return {"ok": True, "trigger_id": tid}


@router.put("/api/triggers/{trigger_id}")
async def update_trigger(trigger_id: int, data: dict[str, Any]) -> dict:
    fields: list[str] = []
    values: list[Any] = []
    if "keyword" in data:
        keyword = str(data.get("keyword") or "").strip()
        if not keyword:
            return {"ok": False, "error": "Укажите слово или фразу"}
        fields.append("keyword = ?")
        values.append(keyword)
    if "channel" in data:
        fields.append("channel = ?")
        values.append(str(data.get("channel") or "").lower().strip().lstrip("#"))
    for key in ("response", "use_ai", "enabled"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(1 if key in ("use_ai", "enabled") and data[key] else 0 if key in ("use_ai", "enabled") else str(data[key] or ""))
    if not fields:
        return {"ok": False, "error": "Нет изменений"}
    db = await get_db()
    try:
        values.append(trigger_id)
        await db.execute(f"UPDATE triggers SET {', '.join(fields)} WHERE id = ?", values)
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/api/triggers/{trigger_id}/test")
async def test_trigger(trigger_id: int, data: dict[str, Any]) -> dict:
    """Тестовый запуск триггера (план §10): проверяет совпадение без отправки и
    возвращает причину, почему триггер не сработал бы."""
    text = str(data.get("text") or "")
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM triggers WHERE id = ?", (trigger_id,))
        trig = await row.fetchone()
    finally:
        await db.close()
    if not trig:
        return {"ok": False, "reason": "not_found", "fired": False}
    if not trig["enabled"]:
        return {"ok": False, "fired": False, "reason": "trigger_disabled",
                "error": "Триггер выключен"}
    trig_channel = (trig["channel"] or "").lower() if "channel" in trig.keys() else ""
    if trig_channel and channel and trig_channel != channel:
        return {"ok": False, "fired": False, "reason": "channel_mismatch",
                "error": f"Триггер привязан к #{trig_channel}, а тест для #{channel}"}
    if trig["keyword"].lower() not in text.lower():
        return {"ok": False, "fired": False, "reason": "no_keyword_match",
                "error": f"Ключевое слово «{trig['keyword']}» не найдено в тексте"}
    return {
        "ok": True,
        "fired": True,
        "reason": "match",
        "use_ai": bool(trig["use_ai"]),
        "response": "" if trig["use_ai"] else trig["response"],
    }


@router.delete("/api/triggers/{trigger_id}")
async def delete_trigger(trigger_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/api/triggers/{trigger_id}/toggle")
async def toggle_trigger(trigger_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("UPDATE triggers SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?", (trigger_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ===================== BANLIST =====================

@router.get("/api/accounts/{account_id}/banlist")
async def list_banlist(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM banlist WHERE account_id = ? ORDER BY username", (account_id,))
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/banlist")
async def add_to_banlist(account_id: int, data: dict[str, Any]) -> dict:
    username = str(data.get("username") or data.get("user") or "").lower().strip()
    if not username:
        return {"ok": False, "error": "Укажите имя пользователя"}
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO banlist (account_id, username) VALUES (?, ?)",
            (account_id, username),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT id FROM banlist WHERE account_id = ? AND username = ?",
            (account_id, username),
        )
        row = await cur.fetchone()
        bid = row["id"] if row else 0
    finally:
        await db.close()
    await log_action(
        "banlist_add",
        f"#{account_id} {username}",
        revert_payload={"action": "banlist_add", "params": {"banlist_id": bid}},
    )
    return {"ok": True, "username": username, "banlist_id": bid}


@router.delete("/api/banlist/{ban_id}")
async def remove_from_banlist(ban_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM banlist WHERE id = ?", (ban_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ===================== STATISTICS =====================

@router.get("/api/accounts/{account_id}/stats")
async def get_account_stats(account_id: int) -> dict:
    db = await get_db()
    try:
        # Всего сообщений бота
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM chat_log WHERE account_id = ? AND is_bot = 1", (account_id,)
        )
        total_sent = (await cursor.fetchone())["cnt"]

        # Всего прочитано
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM chat_log WHERE account_id = ? AND is_bot = 0", (account_id,)
        )
        total_read = (await cursor.fetchone())["cnt"]

        # По каналам
        cursor = await db.execute(
            "SELECT channel, COUNT(*) as cnt FROM chat_log WHERE account_id = ? AND is_bot = 1 GROUP BY channel ORDER BY cnt DESC",
            (account_id,),
        )
        by_channel = [{"channel": r["channel"], "count": r["cnt"]} for r in await cursor.fetchall()]

        # Последние 24 часа
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM chat_log WHERE account_id = ? AND is_bot = 1 AND timestamp > datetime('now', '-1 day')",
            (account_id,),
        )
        last_24h = (await cursor.fetchone())["cnt"]

        # Топ собеседники
        cursor = await db.execute(
            "SELECT author, COUNT(*) as cnt FROM chat_log WHERE account_id = ? AND is_bot = 0 GROUP BY author ORDER BY cnt DESC LIMIT 10",
            (account_id,),
        )
        top_chatters = [{"author": r["author"], "count": r["cnt"]} for r in await cursor.fetchall()]

        return {
            "total_sent": total_sent,
            "total_read": total_read,
            "last_24h": last_24h,
            "by_channel": by_channel,
            "top_chatters": top_chatters,
        }
    finally:
        await db.close()


@router.get("/api/stats/all")
async def get_all_stats() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, nickname FROM accounts ORDER BY id")
        accounts = await cursor.fetchall()
        result = []
        for acc in accounts:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM chat_log WHERE account_id = ? AND is_bot = 1", (acc["id"],)
            )
            sent = (await cursor.fetchone())["cnt"]
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM chat_log WHERE account_id = ? AND is_bot = 0", (acc["id"],)
            )
            read = (await cursor.fetchone())["cnt"]
            cursor = await db.execute(
                "SELECT DISTINCT channel FROM chat_log WHERE account_id = ?", (acc["id"],)
            )
            channels = [r["channel"] for r in await cursor.fetchall()]
            result.append({
                "account_id": acc["id"],
                "nickname": acc["nickname"],
                "sent": sent,
                "read": read,
                "channels": channels,
            })
        return result
    finally:
        await db.close()


# ===================== QUICK PHRASES =====================

@router.get("/api/accounts/{account_id}/phrases")
async def list_phrases(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM quick_phrases WHERE account_id = ? ORDER BY id", (account_id,))
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/phrases")
async def add_phrase(account_id: int, data: dict[str, Any]) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO quick_phrases (account_id, phrase) VALUES (?, ?)",
            (account_id, data["phrase"]),
        )
        await db.commit()
        pid = cur.lastrowid or 0
    finally:
        await db.close()
    await log_action(
        "quick_phrase_add",
        f"#{account_id} {data.get('phrase', '')[:50]}",
        revert_payload={"action": "quick_phrase_add", "params": {"phrase_id": pid}},
    )
    return {"ok": True, "phrase_id": pid}


@router.delete("/api/phrases/{phrase_id}")
async def delete_phrase(phrase_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM quick_phrases WHERE id = ?", (phrase_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ===================== SPAM MODE =====================

@router.post("/api/spam")
async def spam_messages(data: dict[str, Any]) -> dict:
    import asyncio
    from app.server import bot_manager

    account_id = data["account_id"]
    channel = data["channel"].lower().strip().lstrip("#")
    text = data["text"]
    count = min(data.get("count", 1), 50)
    delay = max(data.get("delay", 1.0), 0.3)

    async def do_spam():
        for i in range(count):
            await bot_manager.send_message(account_id, channel, text)
            if i < count - 1:
                await asyncio.sleep(delay)

    asyncio.create_task(do_spam())
    await log_action(f"Спам: {count}x в #{channel}", text[:100])
    return {"ok": True, "count": count, "delay": delay}


# ===================== WORD FILTER =====================

@router.get("/api/accounts/{account_id}/wordfilter")
async def list_word_filter(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM word_filter WHERE account_id = ? ORDER BY id", (account_id,))
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/wordfilter")
async def add_word_filter(account_id: int, data: dict[str, Any]) -> dict:
    word = str(data.get("word") or "").lower().strip()
    if not word:
        return {"ok": False, "error": "Укажите слово"}
    action = str(data.get("action") or "block").lower().strip()
    if action not in {"block", "replace", "warn"}:
        return {"ok": False, "error": "Недопустимое действие фильтра"}
    # PLAN §2.1: привязка слова к каналу ('' = все каналы бота)
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO word_filter (account_id, word, action, channel) VALUES (?, ?, ?, ?)",
            (account_id, word, action, channel),
        )
        await db.commit()
        wid = cur.lastrowid or 0
    finally:
        await db.close()
    await log_action(
        "word_filter_add",
        f"#{account_id} {word[:50]}",
        revert_payload={"action": "word_filter_add", "params": {"word_filter_id": wid}},
    )
    return {"ok": True, "word_filter_id": wid}


@router.delete("/api/wordfilter/{filter_id}")
async def delete_word_filter(filter_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM word_filter WHERE id = ?", (filter_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ===================== EVENT RESPONSES =====================

@router.get("/api/accounts/{account_id}/events")
async def list_event_responses(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM event_responses WHERE account_id = ? ORDER BY event_type", (account_id,))
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/events")
async def add_event_response(account_id: int, data: dict[str, Any]) -> dict:
    event_type = str(data.get("event_type") or "").strip().lower()
    if not event_type:
        return {"ok": False, "error": "Укажите тип события"}
    try:
        chance = max(0, min(100, int(data.get("chance", 100))))
    except (TypeError, ValueError):
        chance = 100
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO event_responses (account_id, event_type, response, use_ai, chance, enabled) VALUES (?, ?, ?, ?, ?, 1)",
            (account_id, event_type, str(data.get("response") or ""), 1 if data.get("use_ai") else 0, chance),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.put("/api/events/{event_id}")
async def update_event_response(event_id: int, data: dict[str, Any]) -> dict:
    db = await get_db()
    try:
        fields, values = [], []
        for key in ("response", "use_ai", "chance", "enabled"):
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if fields:
            values.append(event_id)
            await db.execute(f"UPDATE event_responses SET {', '.join(fields)} WHERE id = ?", values)
            await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/api/events/{event_id}")
async def delete_event_response(event_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM event_responses WHERE id = ?", (event_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ===================== PERSONAS =====================

@router.get("/api/accounts/{account_id}/personas")
async def list_personas(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM personas WHERE account_id = ? ORDER BY id", (account_id,))
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/personas")
async def add_persona(account_id: int, data: dict[str, Any]) -> dict:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO personas (account_id, name, system_prompt, is_active) VALUES (?, ?, ?, 0)",
            (account_id, data["name"], data.get("system_prompt", "")),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/api/personas/{persona_id}/activate")
async def activate_persona(persona_id: int) -> dict:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT account_id FROM personas WHERE id = ?", (persona_id,))
        row = await cursor.fetchone()
        if not row:
            return {"error": "not found"}
        await db.execute("UPDATE personas SET is_active = 0 WHERE account_id = ?", (row["account_id"],))
        await db.execute("UPDATE personas SET is_active = 1 WHERE id = ?", (persona_id,))
        await db.commit()

        # Apply to chat analyzer
        cursor = await db.execute("SELECT system_prompt FROM personas WHERE id = ?", (persona_id,))
        persona = await cursor.fetchone()
        if persona:
            from app.server import chat_analyzer
            chat_analyzer.update_settings(row["account_id"], {"system_prompt": persona["system_prompt"]})

        return {"ok": True}
    finally:
        await db.close()


@router.delete("/api/personas/{persona_id}")
async def delete_persona(persona_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()

# ===================== MOOD ANALYSIS =====================

@router.post("/api/accounts/{account_id}/mood")
async def analyze_mood(account_id: int, data: dict[str, Any]) -> dict:
    from app.server import ai_service, chat_analyzer
    channel = data.get("channel", "").lower().strip().lstrip("#")
    context = chat_analyzer._get_chat_context(account_id, channel)
    if not context:
        return {"mood": "неизвестно", "detail": "Буфер чата пуст"}

    prompt = f"Проанализируй настроение Twitch-чата по последним сообщениям. Ответь ОДНИМ словом: весёлый, злой, скучающий, токсичный, нейтральный, хайповый. Потом коротко поясни (1 предложение).\n\nСообщения:\n{context}"
    result = await ai_service.generate_text(prompt, system="Ты — аналитик чата. Отвечай кратко.", account_id=account_id, channel=channel)
    return {"mood": result or "ошибка", "messages_analyzed": len(context.splitlines())}


# ===================== ACTION LOG =====================

@router.get("/api/action-log")
async def get_action_log(
    limit: int = 50,
    offset: int = 0,
    action: str = "",
    q: str = "",
    from_ts: str = "",
    to_ts: str = "",
    actor: str = "",
) -> dict:
    """v10 BJ + v10.3 5: Action log с фильтрами (action type, query, date range, actor, pagination).

    Возвращает {total, items, actions, actors} — items: страница записей,
    actions/actors: список уникальных значений для UI-фильтров.
    """
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))
    where: list[str] = []
    params: list[Any] = []
    if action:
        where.append("action = ?")
        params.append(action.strip())
    if q:
        where.append("(action LIKE ? OR detail LIKE ?)")
        params.append(f"%{q.strip()}%")
        params.append(f"%{q.strip()}%")
    if from_ts:
        where.append("timestamp >= ?")
        params.append(from_ts.strip())
    if to_ts:
        where.append("timestamp <= ?")
        params.append(to_ts.strip())
    if actor:
        where.append("actor = ?")
        params.append(actor.strip())
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    db = await get_db()
    try:
        cursor = await db.execute(
            f"SELECT COUNT(*) AS c FROM action_log{where_sql}",
            tuple(params),
        )
        total = (await cursor.fetchone())["c"]
        cursor = await db.execute(
            f"SELECT * FROM action_log{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        )
        items = []
        for r in await cursor.fetchall():
            d = dict(r)
            # revert_payload показываем UI как boolean флаг (можно ли откатить).
            payload = d.pop("revert_payload", "") or ""
            d["can_revert"] = bool(payload)
            items.append(d)
        cursor = await db.execute(
            "SELECT DISTINCT action FROM action_log ORDER BY action"
        )
        actions = [r["action"] for r in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT DISTINCT actor FROM action_log WHERE actor != '' ORDER BY actor"
        )
        actors = [r["actor"] for r in await cursor.fetchall()]
    finally:
        await db.close()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "actions": actions,
        "actors": actors,
    }


# ===================== AUTO-CONNECT =====================

@router.post("/api/autoconnect")
async def auto_connect_all() -> dict:
    from app.server import bot_manager
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM accounts WHERE enabled = 1")
        accounts = await cursor.fetchall()
        started = 0
        for acc in accounts:
            cur2 = await db.execute(
                "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1", (acc["id"],)
            )
            channels = [r["channel_name"] for r in await cur2.fetchall()]
            if channels:
                ok = await bot_manager.start_bot(acc["id"], acc["nickname"], acc["token"], channels)
                if ok:
                    started += 1
        await log_action("Авто-подключение", f"Запущено {started} ботов")
        return {"ok": True, "started": started}
    finally:
        await db.close()


@router.get("/api/settings/autoconnect")
async def get_autoconnect_setting() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'autoconnect'")
        row = await cursor.fetchone()
        return {"autoconnect": row["value"] == "1" if row else False}
    finally:
        await db.close()


@router.put("/api/settings/autoconnect")
async def set_autoconnect_setting(data: dict[str, Any]) -> dict:
    db = await get_db()
    try:
        val = "1" if data.get("autoconnect") else "0"
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('autoconnect', ?)", (val,))
        await db.commit()
        return {"ok": True, "autoconnect": val == "1"}
    finally:
        await db.close()


# PLAN §9h: автозапись replay-сессий при старте/остановке бота.
# P8-C6: дефолт ВКЛ — тот же, что у bot_manager при старте бота, иначе тумблер
# врал (показывал «выкл» при реально включённой записи).
@router.get("/api/settings/replay-auto-record")
async def get_replay_auto_record_setting() -> dict:
    return {"enabled": (await get_setting_bool("replay_auto_record", default=True))}


@router.put("/api/settings/replay-auto-record")
async def set_replay_auto_record_setting(data: dict[str, Any]) -> dict:
    await set_setting("replay_auto_record", "1" if data.get("enabled") else "0")
    return {"ok": True, "enabled": bool(data.get("enabled"))}


# Q16 F1 (DEC-OWNER-016): роуты глобального рубильника провокаций убраны вместе с UI.
# Сохранённое значение `provocations_master_enabled` в settings не удаляется — его читает
# рантайм (chat_analyzer) как legacy-fallback; вкл/выкл теперь только у бота («Характер»).


# ===================== OBS WIDGET =====================

@ws_router.get("/obs/tts", response_class=HTMLResponse)
async def obs_tts(channel: str = "", min_role: str = "any", lang: str = "ru-RU",
                  rate: float = 1.0, volume: float = 1.0, max_chars: int = 200,
                  theme: str | None = None, accent: str | None = None,
                  bg: str | None = None, opacity: str | None = None,
                  radius: str | None = None, font: str | None = None,
                  size: str | None = None, scale: str | None = None,
                  pos: str | None = None, shadow: str | None = None,
                  showstatus: str | None = None) -> str:
    """OBS-overlay: TTS-озвучка сообщений из чата (Web Speech API).

    Параметры URL (для browser-source в OBS):
      channel=name    — фильтр по каналу (без #), пусто = все каналы
      min_role=any    — any | sub | vip | mod | broadcaster
      lang=ru-RU      — язык голоса (ru-RU, en-US, …)
      rate=1.0        — скорость речи (0.5-2)
      volume=1.0      — громкость (0-1)
      max_chars=200   — обрезать длинные сообщения
    """
    # Безопасные значения для подстановки в JS
    safe_channel = (channel or "").replace("'", "").replace("\\", "").lower()
    safe_role = (min_role or "any").replace("'", "")
    safe_lang = (lang or "ru-RU").replace("'", "")
    try:
        rate_v = max(0.5, min(2.0, float(rate)))
    except Exception:
        rate_v = 1.0
    try:
        vol_v = max(0.0, min(1.0, float(volume)))
    except Exception:
        vol_v = 1.0
    try:
        max_chars_v = max(20, min(500, int(max_chars)))
    except Exception:
        max_chars_v = 200
    # §5 WIDGETS_PLAN: шаблон виджета живёт в widgets/tts-raw/index.html
    from app.widgets import _apply_widget_design, _resolve_widget_design, _widget_html
    design = await _resolve_widget_design("tts-raw", {
        "theme": theme, "accent": accent, "bg": bg, "opacity": opacity,
        "radius": radius, "font": font, "size": size, "scale": scale,
        "pos": pos, "shadow": shadow, "showstatus": showstatus,
    })
    html = _apply_widget_design(_widget_html("tts-raw"), design)
    return html \
        .replace("__CHANNEL__", json.dumps(safe_channel)) \
        .replace("__ROLE__", json.dumps(safe_role)) \
        .replace("__LANG__", json.dumps(safe_lang)) \
        .replace("__RATE__", str(rate_v)) \
        .replace("__VOL__", str(vol_v)) \
        .replace("__MAXCHARS__", str(max_chars_v))


@router.get("/obs-widget", response_class=HTMLResponse)
async def obs_widget() -> str:
    return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="color-scheme" content="dark">
<script src="/widget/_shared/i18n.js"></script>
<script>
WidgetI18n.add({
    ru: {'legacy_chat.title': 'Чат для OBS', 'legacy_chat.messages': 'Сообщения чата'},
    en: {'legacy_chat.title': 'OBS chat', 'legacy_chat.messages': 'Chat messages'},
    ua: {'legacy_chat.title': 'Чат для OBS', 'legacy_chat.messages': 'Повідомлення чату'}
});
</script>
<title data-widget-i18n="legacy_chat.title">Чат для OBS</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:transparent;font-family:'Segoe UI',sans-serif;overflow:hidden}
#chat{display:flex;flex-direction:column;justify-content:flex-end;height:100vh;padding:10px}
.msg{padding:4px 8px;margin:2px 0;border-radius:4px;font-size:14px;animation:fadeIn 0.3s ease;
     background:rgba(0,0,0,0.6);color:#fff;max-width:100%;word-wrap:break-word}
.msg .nick{font-weight:700;margin-right:4px}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
</style></head><body>
<div id="chat" role="log" aria-label="Сообщения чата" data-widget-i18n-aria-label="legacy_chat.messages"></div>
<script>
const colors=['#FF6B6B','#4ECDC4','#45B7D1','#96CEB4','#FECA57','#FF9FF3','#54A0FF','#5F27CD','#F368E0','#2ED573'];
function getColor(n){let h=0;for(let i=0;i<n.length;i++)h=n.charCodeAt(i)+((h<<5)-h);return colors[Math.abs(h)%colors.length]}
const ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws');
ws.onmessage=function(e){
    const d=JSON.parse(e.data);
    if(d.type!=='chat')return;
    const author=String(d.author??'');
    const message=String(d.message??'');
    const el=document.createElement('div');
    el.className='msg';
    const nick=document.createElement('span');
    nick.className='nick';
    nick.style.color=getColor(author);
    nick.textContent=author+':';
    el.appendChild(nick);
    el.appendChild(document.createTextNode(message));
    const chat=document.getElementById('chat');
    chat.appendChild(el);
    while(chat.children.length>30)chat.removeChild(chat.firstChild);
};
</script></body></html>"""


# ===================== SCHEDULED MESSAGES =====================

@router.get("/api/accounts/{account_id}/scheduled")
async def get_scheduled(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM scheduled_messages WHERE account_id = ? ORDER BY id", (account_id,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/scheduled")
async def add_scheduled(account_id: int, request: Request) -> dict:
    data = await request.json()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO scheduled_messages (account_id, channel, message, min_interval, max_interval, use_ai, ai_prompt) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account_id, data.get("channel", ""), data.get("message", ""),
             data.get("min_interval", 5), data.get("max_interval", 30),
             1 if data.get("use_ai") else 0, data.get("ai_prompt", ""))
        )
        await db.commit()
        await log_action("scheduled_add", f"Добавлено расписание для аккаунта {account_id}")
        return {"ok": True}
    finally:
        await db.close()


@router.put("/api/scheduled/{sched_id}")
async def update_scheduled(sched_id: int, request: Request) -> dict:
    data = await request.json()
    db = await get_db()
    try:
        if "enabled" in data:
            await db.execute("UPDATE scheduled_messages SET enabled = ? WHERE id = ?", (1 if data["enabled"] else 0, sched_id))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/api/scheduled/{sched_id}")
async def delete_scheduled(sched_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM scheduled_messages WHERE id = ?", (sched_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ===================== CHAT STATS =====================

@router.get("/api/stats/chat")
async def get_chat_stats() -> dict:
    db = await get_db()
    try:
        # Messages per hour (last 24h)
        cursor = await db.execute("""
            SELECT strftime('%H', timestamp) as hour, COUNT(*) as cnt
            FROM chat_log
            WHERE timestamp > datetime('now', '-24 hours')
            GROUP BY hour ORDER BY hour
        """)
        hourly = [dict(r) for r in await cursor.fetchall()]

        # Top chatters
        cursor = await db.execute("""
            SELECT author, COUNT(*) as cnt
            FROM chat_log WHERE is_bot = 0
            GROUP BY author ORDER BY cnt DESC LIMIT 10
        """)
        top_chatters = [dict(r) for r in await cursor.fetchall()]

        # Total messages
        cursor = await db.execute("SELECT COUNT(*) as total FROM chat_log")
        total = (await cursor.fetchone())["total"]

        # Bot messages
        cursor = await db.execute("SELECT COUNT(*) as total FROM chat_log WHERE is_bot = 1")
        bot_total = (await cursor.fetchone())["total"]

        return {"hourly": hourly, "top_chatters": top_chatters, "total": total, "bot_total": bot_total}
    finally:
        await db.close()


# ===================== FEATURE Z: BACKUP / RESTORE =====================

@router.get("/api/backup/download")
async def backup_download(request: Request, include_env: int = 0) -> Response:
    """Скачать zip-бэкап; секретный .env добавляется только явно."""
    require_loopback_client(request)
    try:
        zip_bytes, fname = await backup_mod.make_backup_zip(include_env=bool(include_env))
    except Exception as exc:
        logger.error("Backup error: %s", exc)
        return Response(status_code=500, content=f"backup error: {exc}")
    await log_action("backup_download", f"Бэкап выгружен ({len(zip_bytes)} байт)")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/backup/download-db")
async def backup_download_db(request: Request) -> Response:
    """Скачать актуальный снимок bot.db (SQLite) напрямую."""
    require_loopback_client(request)
    try:
        db_bytes, fname = await backup_mod.make_db_snapshot()
    except Exception as exc:
        logger.error("DB Snapshot error: %s", exc)
        return Response(status_code=500, content=f"db snapshot error: {exc}")
    await log_action("backup_download_db", f"Снимок bot.db выгружен ({len(db_bytes)} байт)")
    return Response(
        content=db_bytes,
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/api/backup/restore")
async def backup_restore(request: Request, file: UploadFile = File(...), restore_env: int = 0) -> dict:
    """Восстановить из загруженного zip-бэкапа."""
    require_loopback_client(request)
    require_same_origin_request(request)
    try:
        data = await file.read()
        if not data:
            return {"ok": False, "error": "Пустой файл"}
        result = await backup_mod.restore_from_zip(data, restore_env=bool(restore_env))
    except Exception as exc:
        logger.error("Restore error: %s", exc)
        return {"ok": False, "error": str(exc)}
    if result.get("ok"):
        await log_action("backup_restore", f"Восстановлено из {file.filename}")
    return result


# ===================== TWITCH CREDENTIALS (Client ID / Secret через UI) =====================

@router.get("/api/settings/twitch-credentials")
async def get_twitch_credentials() -> dict:
    """Текущее состояние Twitch Client ID / Secret.

    Client ID считается публичным (он уходит в браузер при OAuth) — отдаём его как есть.
    Client Secret наружу не отдаём, только флаг ``client_secret_set``.
    Также сообщаем, откуда сейчас берётся каждое значение: из БД (UI) или из ``.env``.
    """
    return twitch_credentials.get_status()


@router.put("/api/settings/twitch-credentials")
async def set_twitch_credentials(data: dict[str, Any]) -> dict:
    """Сохранить Client ID / Secret в БД и применить без рестарта.

    Поля: ``client_id``, ``client_secret`` (оба опциональны). Передавайте пустую
    строку, чтобы очистить override и снова использовать значение из ``.env``.
    """
    cid = data.get("client_id")
    csec = data.get("client_secret")
    await twitch_credentials.save_to_db(
        client_id=cid if isinstance(cid, str) else None,
        client_secret=csec if isinstance(csec, str) else None,
    )
    await log_action("twitch_credentials_update", "Client ID/Secret обновлены через UI")
    return {"ok": True, **twitch_credentials.get_status()}


# ===================== FEATURE 6: PROXY =====================

@router.put("/api/accounts/{account_id}/proxy")
async def set_account_proxy(account_id: int, data: dict[str, Any]) -> dict:
    """Установить/убрать прокси для аккаунта. Поддержка: http://, https://, socks5://"""
    proxy = (data.get("proxy") or "").strip()
    db = await get_db()
    try:
        await db.execute("UPDATE accounts SET proxy = ? WHERE id = ?", (proxy, account_id))
        await db.commit()
        return {"ok": True, "proxy_set": bool(proxy)}
    finally:
        await db.close()


# ===================== v10.4.5 Wave 2: A/B dashboard =====================


@router.get("/api/ab-dashboard")
async def ab_dashboard(account_id: int | None = None, hours: int = 168) -> dict:
    """Aggregated metrics per pattern_variant за последние N часов."""
    from app.ab_dashboard import get_dashboard_payload

    try:
        payload = await get_dashboard_payload(
            account_id=int(account_id) if account_id is not None else None,
            hours=max(1, min(int(hours or 168), 24 * 30)),
        )
        return {"ok": True, **payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ===================== v10.4.5 Wave 2: Shared user_facts =====================
# P8-C2: роуты shared-user-facts удалены (общая память убрана;
# факты мигрировали в per-bot user_memory).


# ===================== v10.4.5 Wave 2: Game vocabulary =====================


@router.get("/api/game-vocab/categories")
async def list_game_vocab_categories() -> dict:
    """Возвращает доступные категории + примеры словарей (для UI)."""
    from app.game_vocab import DEFAULT_GAME_CATEGORIES

    items = []
    for cat, payload in DEFAULT_GAME_CATEGORIES.items():
        items.append({
            "category": cat,
            "match_examples": list(payload.get("match", []))[:5],
            "vocab": list(payload.get("vocab", []))[:8],
            "tone": payload.get("tone", ""),
        })
    return {"ok": True, "categories": items}


@router.get("/api/game-vocab/detect")
async def detect_game_category(game_name: str = "") -> dict:
    """Определяет категорию по имени игры. Для UI «попробовать»."""
    from app.game_vocab import format_vocab_block, match_game_category

    cat = match_game_category(game_name)
    block = format_vocab_block(cat) if cat else ""
    return {"ok": True, "game_name": game_name, "category": cat, "block": block}


# ===================== v10.4.5 Wave 2: Mood snapshot =====================


@router.get("/api/accounts/{account_id}/mood")
async def get_account_mood(account_id: int, channel: str = "") -> dict:
    """Текущее mood-состояние per (account, channel)."""
    from app.server import chat_analyzer

    s = chat_analyzer.get_settings(account_id)
    if not channel:
        return {"ok": True, "enabled": bool(s.get("mood_engine_enabled")), "trackers": []}
    tr = chat_analyzer._get_mood_tracker(account_id, channel)
    return {"ok": True, "enabled": bool(s.get("mood_engine_enabled")), "channel": channel, **tr.snapshot()}


# ===================== v10.4.5 Wave 2: Multi-bot snapshot =====================


@router.get("/api/accounts/{account_id}/multi-bot")
async def get_multi_bot_state(account_id: int, channel: str = "") -> dict:
    from app.server import chat_analyzer

    s = chat_analyzer.get_settings(account_id)
    if not channel:
        return {
            "ok": True,
            "enabled": bool(s.get("multi_bot_chat_enabled")),
            "friendly_nicks_raw": s.get("multi_bot_friendly_nicks", ""),
        }
    tr = chat_analyzer._get_friendly_tracker(account_id, channel)
    return {"ok": True, "enabled": bool(s.get("multi_bot_chat_enabled")), "channel": channel, **tr.snapshot()}


# ===================== v10.4.5 Wave 2: Predictions/Polls auto-vote =====================


@router.post("/api/predictions/decide")
async def predictions_decide_vote(data: dict[str, Any]) -> dict:
    """Test endpoint: даём question + choices, получаем выбор AI.

    body: {question: str, choices: list[str], channel?: str}
    """
    from app.predictions_polls import decide_vote

    question = str(data.get("question") or "")
    choices = list(data.get("choices") or [])
    channel = str(data.get("channel") or "")
    if not question or not choices:
        return {"ok": False, "error": "question and choices required"}
    decision = await decide_vote(question, choices, channel=channel)
    return {"ok": True, "decision": decision.to_dict()}


# ===================== v10.4.5 Wave 2: VAD silence snapshot =====================


@router.get("/api/vad-silence/{account_id}")
async def get_vad_silence_state(account_id: int, channel: str = "") -> dict:
    from app.server import chat_analyzer, stream_vision_manager

    s = chat_analyzer.get_settings(account_id)
    if not channel or stream_vision_manager is None:
        return {"ok": True, "enabled": bool(s.get("vad_silence_enabled"))}
    w = stream_vision_manager._get_silence_watcher(account_id, channel)
    return {"ok": True, "enabled": bool(s.get("vad_silence_enabled")), "channel": channel, **w.snapshot()}


# ===================== WEBSOCKET =====================

@ws_router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # Feature 1: проверка авторизации для WS
    headers = dict(ws.headers)
    client_host = ws.client.host if ws.client else ""
    if not check_ws_auth(headers, client_host):
        await ws.close(code=4401)
        return
    has_channel_param = "channel" in ws.query_params
    requested_channel = ws.query_params.get("channel", "")
    scope_key = ""
    if has_channel_param:
        from app.widget_channel_scope import resolve_channel
        identity = await resolve_channel(requested_channel)
        if identity is None or not identity.enabled:
            await ws.close(code=4404)
            return
        scope_key = identity.key
    await ws.accept()
    ws_connections.append(ws)
    if scope_key:
        ws_channel_scopes[id(ws)] = scope_key
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in ws_connections:
            ws_connections.remove(ws)
        ws_channel_scopes.pop(id(ws), None)
from app import routes_modpanel  # noqa: E402
from app import routes_wave4  # noqa: E402
from app import routes_bot_intel  # noqa: E402
from app import routes_attention  # noqa: E402
from app import routes_ai_quality  # noqa: E402
from app import routes_engagement  # noqa: E402
from app import routes_streamer_profile  # noqa: E402
from app import routes_global_profile  # noqa: E402
from app import routes_stats_heatmap  # noqa: E402
from app import routes_stats_v9  # noqa: E402
from app import routes_clip  # noqa: E402
from app.routes_clip import _chat_rate_tracker, _clip_cooldowns, register_clip_rate_hook  # noqa: E402,F401
from app import routes_snippets  # noqa: E402
from app import routes_maintenance  # noqa: E402
from app import routes_csv_export  # noqa: E402
from app import routes_import_export  # noqa: E402
from app import routes_security  # noqa: E402
from app import routes_device_code  # noqa: E402
from app import routes_token_refresh  # noqa: E402
from app import routes_ai_feedback  # noqa: E402
from app import routes_eventsub  # noqa: E402
from app import routes_channel_info  # noqa: E402
from app import routes_user_memory  # noqa: E402
from app import routes_user_history  # noqa: E402
from app import routes_search  # noqa: E402
from app import routes_ai_summary  # noqa: E402
from app import routes_highlights  # noqa: E402
from app import routes_auto_highlights  # noqa: E402
from app import routes_voice_clone  # noqa: E402
from app import routes_persona_presets  # noqa: E402
from app import routes_tts_config  # noqa: E402
from app import routes_overrides  # noqa: E402
from app import routes_bot_logs  # noqa: E402
from app import routes_tts_duck  # noqa: E402
from app.routes_tts_duck import _ensure_duck_settings  # noqa: E402,F401
from app import routes_sse  # noqa: E402
from app import routes_prompt_base  # noqa: E402  # PROMPT-BASE PB-1: /api/prompt-base
