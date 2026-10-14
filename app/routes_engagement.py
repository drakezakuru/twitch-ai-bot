"""engagement — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any
import json
from app.routes import router, cleanup_account_children, decrypt_token, engagement_mod, get_db, log_action, router, set_setting  # noqa: E402


# ===================== v10.3 4B: ENGAGEMENT TRACKING =====================

@router.get("/api/engagement/stats")
async def engagement_stats(account_id: int = 0, days: int = 7) -> dict:
    """Агрегаты engagement за период."""
    return await engagement_mod.stats_summary(account_id=int(account_id), days=int(days))


@router.get("/api/engagement/list")
async def engagement_list(
    account_id: int = 0,
    channel: str = "",
    days: int = 7,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Постранично: ответы бота с engagement-метрикой."""
    return await engagement_mod.list_recent(
        account_id=int(account_id),
        channel=channel,
        days=int(days),
        limit=int(limit),
        offset=int(offset),
    )


@router.post("/api/engagement/recompute")
async def engagement_recompute(data: dict | None = None) -> dict:
    """Прогон engagement-расчёта по всем bot-сообщениям с закрывшимся окном.

    body: {"window_sec"?, "breakthrough_min"?, "limit"?} — для отладки.
    """
    data = data or {}
    window = data.get("window_sec")
    bmin = data.get("breakthrough_min")
    limit = int(data.get("limit") or 500)
    count = await engagement_mod.compute_pending(
        window_sec=int(window) if window is not None else None,
        breakthrough_min=int(bmin) if bmin is not None else None,
        limit=limit,
    )
    await log_action("engagement_recompute", f"computed={count}")
    return {"ok": True, "computed": count}


@router.get("/api/engagement/settings")
async def engagement_settings_get() -> dict:
    return {
        "window_sec": await engagement_mod.get_window_sec(),
        "breakthrough_min": await engagement_mod.get_breakthrough_min(),
    }


@router.put("/api/engagement/settings")
async def engagement_settings_put(data: dict) -> dict:
    """Обновить window_sec / breakthrough_min."""
    if "window_sec" in data:
        try:
            v = max(5, min(600, int(data["window_sec"])))
        except (TypeError, ValueError):
            v = engagement_mod.DEFAULT_WINDOW_SEC
        await set_setting("engagement_window_sec", str(v))
    if "breakthrough_min" in data:
        try:
            v = max(1, min(100, int(data["breakthrough_min"])))
        except (TypeError, ValueError):
            v = engagement_mod.DEFAULT_BREAKTHROUGH_MIN
        await set_setting("engagement_breakthrough_min", str(v))
    return {
        "ok": True,
        "window_sec": await engagement_mod.get_window_sec(),
        "breakthrough_min": await engagement_mod.get_breakthrough_min(),
    }


# ===================== v10.3 4C: SIDE-BY-SIDE MODEL COMPARE =====================

@router.post("/api/ai/compare")
async def ai_compare(data: dict[str, Any]) -> dict:
    """Параллельно дёргает несколько моделей с одним промптом и возвращает результаты.

    Body: {prompt, system?, temperature?, models: [{provider, model}]}
    """
    import asyncio as _asyncio
    import time as _time

    from app.server import ai_service

    prompt = (data.get("prompt") or "").strip()
    system = (data.get("system") or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt required"}
    try:
        temperature = data.get("temperature")
        temperature = float(temperature) if temperature is not None and temperature != "" else None
    except (TypeError, ValueError):
        temperature = None

    raw_models = data.get("models") or []
    if not isinstance(raw_models, list) or not raw_models:
        return {"ok": False, "error": "models[] required"}

    cleaned: list[dict] = []
    for item in raw_models[:6]:
        if not isinstance(item, dict):
            continue
        provider = (item.get("provider") or "").strip().lower() or "openrouter"
        if provider not in ("openrouter", "ollama", "gemini", "openai", "anthropic"):
            provider = "openrouter"
        model = (item.get("model") or "").strip()
        if not model:
            continue
        cleaned.append({"provider": provider, "model": model})

    if not cleaned:
        return {"ok": False, "error": "no valid models"}

    async def _run(provider: str, model: str) -> dict:
        t0 = _time.monotonic()
        try:
            res = await ai_service.generate_text_with(
                provider, model, prompt, system=system, temperature=temperature,
            )
        except Exception as exc:
            return {
                "provider": provider,
                "model": model,
                "ok": False,
                "error": str(exc),
                "ms": int((_time.monotonic() - t0) * 1000),
                "response": "",
            }
        ms = int((_time.monotonic() - t0) * 1000)
        return {
            "provider": provider,
            "model": model,
            "ok": bool(res.get("ok")),
            "error": res.get("error") or "",
            "response": res.get("response") or "",
            "ms": ms,
            "length": len(res.get("response") or ""),
        }

    results = await _asyncio.gather(
        *(_run(m["provider"], m["model"]) for m in cleaned),
        return_exceptions=False,
    )

    await log_action(
        "compare_run",
        f"models={len(cleaned)} prompt={prompt[:80]}",
        revert_payload=None,
    )

    return {
        "ok": True,
        "prompt": prompt,
        "system": system,
        "temperature": temperature,
        "results": list(results),
    }


# ===================== v10.3 5: BULK BOT CONTROL (Ctrl+K commands) =====================

@router.post("/api/bots/start_all")
async def start_all_bots() -> dict:
    """Запустить ботов на всех включённых аккаунтах с каналами."""
    from app.server import bot_manager, eventsub_manager, chat_analyzer
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM accounts WHERE enabled = 1")
        accounts = await cur.fetchall()
        started = 0
        skipped = 0
        for acc in accounts:
            cur2 = await db.execute(
                "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1",
                (acc["id"],),
            )
            channels = [r["channel_name"] for r in await cur2.fetchall()]
            if not channels:
                skipped += 1
                continue
            proxy = acc["proxy"] if "proxy" in acc.keys() else ""
            ok = await bot_manager.start_bot(
                acc["id"], acc["nickname"], acc["token"], channels, proxy=proxy or "",
            )
            if ok:
                started += 1
                try:
                    chat_analyzer.set_account_token(acc["id"], decrypt_token(acc["token"]))
                except Exception:
                    pass
                try:
                    if "eventsub_enabled" in acc.keys() and acc["eventsub_enabled"]:
                        await eventsub_manager.start_for_account(
                            acc["id"], acc["nickname"], decrypt_token(acc["token"]), channels,
                        )
                except Exception:
                    pass
    finally:
        await db.close()
    await log_action("bots_start_all", f"started={started} skipped={skipped}")
    return {"ok": True, "started": started, "skipped": skipped}


@router.post("/api/bots/stop_all")
async def stop_all_bots() -> dict:
    from app.server import bot_manager, eventsub_manager
    db = await get_db()
    try:
        cur = await db.execute("SELECT id FROM accounts")
        ids = [r["id"] for r in await cur.fetchall()]
    finally:
        await db.close()
    stopped = 0
    for aid in ids:
        try:
            ok = await bot_manager.stop_bot(aid)
            if ok:
                stopped += 1
            await eventsub_manager.stop_for_account(aid)
        except Exception:
            pass
    await log_action("bots_stop_all", f"stopped={stopped}")
    return {"ok": True, "stopped": stopped}


# ===================== v10.3 5: ACTION LOG REVERT =====================

# Регистрация известных revert-операций. Принимают (db, payload) и выполняют откат.
async def _revert_account_add(db: Any, payload: dict) -> tuple[bool, str]:
    aid = int(payload.get("account_id") or 0)
    if not aid:
        return False, "no account_id"
    from app.server import bot_manager
    try:
        await bot_manager.stop_bot(aid)
    except Exception:
        pass
    await cleanup_account_children(db, aid)
    await db.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    await db.commit()
    return True, f"account {aid} deleted"


async def _revert_quick_phrase_add(db: Any, payload: dict) -> tuple[bool, str]:
    pid = int(payload.get("phrase_id") or 0)
    if not pid:
        return False, "no phrase_id"
    await db.execute("DELETE FROM quick_phrases WHERE id = ?", (pid,))
    await db.commit()
    return True, f"phrase {pid} deleted"


async def _revert_banlist_add(db: Any, payload: dict) -> tuple[bool, str]:
    bid = int(payload.get("banlist_id") or 0)
    if not bid:
        return False, "no banlist_id"
    await db.execute("DELETE FROM banlist WHERE id = ?", (bid,))
    await db.commit()
    return True, f"banlist {bid} deleted"


async def _revert_word_filter_add(db: Any, payload: dict) -> tuple[bool, str]:
    wid = int(payload.get("word_filter_id") or 0)
    if not wid:
        return False, "no word_filter_id"
    await db.execute("DELETE FROM word_filter WHERE id = ?", (wid,))
    await db.commit()
    return True, f"word_filter {wid} deleted"


async def _revert_trigger_add(db: Any, payload: dict) -> tuple[bool, str]:
    tid = int(payload.get("trigger_id") or 0)
    if not tid:
        return False, "no trigger_id"
    await db.execute("DELETE FROM triggers WHERE id = ?", (tid,))
    await db.commit()
    return True, f"trigger {tid} deleted"


async def _revert_voice_widget_action(db: Any, payload: dict) -> tuple[bool, str]:
    from app.voice_control import revert_widget_action
    return await revert_widget_action(db, payload)


_REVERT_HANDLERS: dict[str, Any] = {
    "account_add": _revert_account_add,
    "quick_phrase_add": _revert_quick_phrase_add,
    "banlist_add": _revert_banlist_add,
    "word_filter_add": _revert_word_filter_add,
    "trigger_add": _revert_trigger_add,
    "voice_widget_action": _revert_voice_widget_action,
}


@router.post("/api/action-log/{log_id}/revert")
async def revert_action_log(log_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, action, detail, actor, revert_payload FROM action_log WHERE id = ?",
            (log_id,),
        )
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "not_found"}
        payload_str = row["revert_payload"] or ""
        if not payload_str:
            return {"ok": False, "error": "no_revert_payload"}
        try:
            payload = json.loads(payload_str)
        except Exception:
            return {"ok": False, "error": "bad_payload"}
        action = (payload.get("action") or "") if isinstance(payload, dict) else ""
        params = (payload.get("params") or {}) if isinstance(payload, dict) else {}
        handler = _REVERT_HANDLERS.get(action)
        if not handler:
            return {"ok": False, "error": f"no_handler:{action}"}
        ok, detail = await handler(db, params)
        if ok:
            await db.execute(
                "UPDATE action_log SET revert_payload = '' WHERE id = ?", (log_id,),
            )
            await db.commit()
    finally:
        await db.close()

    if ok:
        await log_action(
            f"revert:{action}",
            f"original_id={log_id} {detail}",
        )
    return {"ok": ok, "detail": detail, "action": action}
