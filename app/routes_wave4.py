"""wave4 — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from app.routes import router, router  # noqa: E402
from app.database import get_db  # noqa: E402


# ===================== v10.4.7 Wave 4: Threads / Proactive / Fallback / Notify / Mimicry / Replay =====================


@router.get("/api/threads/{account_id}")
async def threads_snapshot(account_id: int, channel: str) -> dict:
    from app.server import chat_analyzer
    try:
        tt = chat_analyzer._get_thread_tracker(account_id, channel)
        return {"ok": True, "snapshot": tt.snapshot()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/proactive/{account_id}")
async def proactive_snapshot(account_id: int, channel: str) -> dict:
    from app.server import chat_analyzer
    try:
        tr = chat_analyzer._get_proactive_tracker(account_id, channel)
        ok, reason = tr.can_emit()
        return {
            "ok": True,
            "can_emit": ok,
            "reason": reason,
            "last_emit": tr.last_emit,
            "last_chat_at": tr.last_chat_at,
            "last_vision_at": tr.last_vision_at,
            "last_vision": tr.last_vision[:200],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/fallback/router")
async def fallback_router_snapshot() -> dict:
    from app.server import chat_analyzer
    return {"ok": True, "snapshot": chat_analyzer._fallback_router.snapshot()}


@router.get("/api/runtime/status")
async def runtime_status() -> dict:
    try:
        from app.server import ai_service, bot_manager
    except (ImportError, AttributeError):
        # Lightweight test applications may mount the router without the
        # production server singleton; keep the status endpoint usable there.
        return {"ok": True, "ai_provider": "unknown", "ai_state": "unknown",
                "ollama_state": "unknown", "fallback_enabled": False, "bots": {}}
    ollama_status = await ai_service.ollama_status()
    return {
        "ok": True,
        "ai_provider": ai_service.provider,
        "ai_state": "paused" if ai_service.provider == "ollama" and ollama_status["state"] == "paused" else "ready",
        "ollama_state": ollama_status["state"],
        "fallback_enabled": ai_service.local_fallback_enabled,
        "bots": bot_manager.get_all_statuses(),
    }


@router.post("/api/fallback/reset")
async def fallback_router_reset(payload: dict) -> dict:
    from app.server import chat_analyzer
    provider = (payload.get("provider") or "").strip()
    if not provider:
        chat_analyzer._fallback_router = type(chat_analyzer._fallback_router)(fallback_provider=chat_analyzer._fallback_router.fallback_provider)
    else:
        chat_analyzer._fallback_router.record_success(provider)
    return {"ok": True, "snapshot": chat_analyzer._fallback_router.snapshot()}


@router.get("/api/streamer-notes")
async def streamer_notes_list(account_id: int | None = None, channel: str | None = None, limit: int = 50, only_unread: bool = False) -> dict:
    from app.streamer_notify import list_panel_notes
    notes = await list_panel_notes(account_id=account_id, channel=channel, limit=int(limit), only_unread=bool(only_unread))
    return {"ok": True, "notes": notes}


@router.post("/api/streamer-notes")
async def streamer_notes_create(payload: dict) -> dict:
    from app.streamer_notify import save_panel_note
    nid = await save_panel_note(
        account_id=int(payload.get("account_id") or 0),
        channel=(payload.get("channel") or "").strip(),
        severity=(payload.get("severity") or "info").strip(),  # type: ignore[arg-type]
        title=(payload.get("title") or "").strip(),
        body=(payload.get("body") or "").strip(),
    )
    return {"ok": True, "id": nid}


@router.post("/api/streamer-notes/{note_id}/read")
async def streamer_notes_mark_read(note_id: int) -> dict:
    from app.streamer_notify import mark_panel_note_read
    await mark_panel_note_read(note_id)
    return {"ok": True}


@router.delete("/api/streamer-notes/{note_id}")
async def streamer_notes_delete(note_id: int) -> dict:
    from app.streamer_notify import delete_panel_note
    await delete_panel_note(note_id)
    return {"ok": True}


@router.post("/api/streamer-notes/test")
async def streamer_notes_test(payload: dict) -> dict:
    """Тестовая отправка через настройки конкретного аккаунта (Discord/Telegram/Panel)."""
    from app.server import chat_analyzer
    account_id = int(payload.get("account_id") or 0)
    channel = (payload.get("channel") or "").strip()
    if not account_id:
        return {"ok": False, "error": "account_id required"}
    # Инвалидируем кеш чтобы перечитать актуальные настройки
    chat_analyzer.invalidate_notifier(account_id)
    notifier = chat_analyzer._get_notifier(account_id)
    res = await notifier.notify(
        account_id, channel,
        (payload.get("severity") or "info"),  # type: ignore[arg-type]
        (payload.get("title") or "Тестовое уведомление"),
        (payload.get("body") or "Это тестовое сообщение от бота."),
    )
    return {"ok": True, "result": res}


@router.get("/api/live-mimicry/{account_id}")
async def live_mimicry_snapshot(account_id: int, channel: str) -> dict:
    from app.server import chat_analyzer
    try:
        col = chat_analyzer._get_live_profile(account_id, channel)
        prof = col.compute()
        return {"ok": True, "profile": prof.to_dict()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# Q16 F5: автозапись replay-сессий — настройка бота. NULL-колонка = наследовать
# глобальный replay_auto_record (legacy-fallback рантайма).
@router.get("/api/accounts/{account_id}/replay-settings")
async def get_replay_bot_settings(account_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute("SELECT replay_auto_record FROM accounts WHERE id = ?", (account_id,))
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "not found"}
    own = row["replay_auto_record"] if "replay_auto_record" in row.keys() else None
    return {"ok": True, "auto_record": bool(own), "inherited": own is None}


@router.put("/api/accounts/{account_id}/replay-settings")
async def set_replay_bot_settings(account_id: int, payload: dict) -> dict:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE accounts SET replay_auto_record = ? WHERE id = ?",
            (1 if payload.get("auto_record") else 0, account_id),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True, "auto_record": bool(payload.get("auto_record"))}


@router.get("/api/replay/sessions")
async def replay_sessions_list(limit: int = 50) -> dict:
    from app.replay_debug import list_sessions
    return {"ok": True, "sessions": await list_sessions(limit=int(limit))}


@router.post("/api/replay/sessions/start")
async def replay_session_start(payload: dict) -> dict:
    from app.replay_debug import start_session
    from app.server import chat_analyzer
    name = (payload.get("name") or "").strip() or f"session_{int(__import__('time').time())}"
    account_id = int(payload.get("account_id") or 0)
    channel = (payload.get("channel") or "").strip()
    notes = (payload.get("notes") or "").strip()
    if not account_id or not channel:
        return {"ok": False, "error": "account_id, channel обязательны"}
    sid = await start_session(name=name, account_id=account_id, channel=channel, notes=notes)
    chat_analyzer._replay_sessions[(account_id, channel.lower())] = sid
    return {"ok": True, "session_id": sid}


@router.post("/api/replay/sessions/{session_id}/end")
async def replay_session_end(session_id: int) -> dict:
    from app.replay_debug import end_session, get_session
    from app.server import chat_analyzer
    sess = await get_session(session_id)
    if not sess:
        return {"ok": False, "error": "session not found"}
    await end_session(session_id)
    key = (int(sess["account_id"]), (sess["channel"] or "").lower())
    if chat_analyzer._replay_sessions.get(key) == session_id:
        chat_analyzer._replay_sessions.pop(key, None)
    return {"ok": True}


@router.get("/api/replay/sessions/{session_id}/events")
async def replay_session_events(session_id: int, kinds: str | None = None, limit: int = 1000) -> dict:
    from app.replay_debug import get_events
    kinds_list = [k.strip() for k in (kinds or "").split(",") if k.strip()] or None
    events = await get_events(session_id, kinds=kinds_list, limit=int(limit))  # type: ignore[arg-type]
    return {"ok": True, "events": events}


@router.delete("/api/replay/sessions/{session_id}")
async def replay_session_delete(session_id: int) -> dict:
    from app.replay_debug import delete_session
    await delete_session(session_id)
    return {"ok": True}
