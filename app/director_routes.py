"""Owner-only control API for the fail-closed Director foundation."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from app.security import auth_dependency
from app import director, director_manual, director_review

router = APIRouter(dependencies=[Depends(auth_dependency)])

def _error(exc: ValueError) -> HTTPException:
    code, _, detail = str(exc).partition(":")
    return HTTPException(status_code=400, detail={"code": code, "params": {"sources": detail.split(",") if detail else []}})

@router.post("/api/director/emergency")
async def emergency_stop_all() -> dict:
    return await director.emergency_stop_all()

# Q40b: режим канала (ИИ / Ручной) и ручная отправка оператора.
@router.get("/api/director/control-modes")
async def control_modes() -> dict:
    return await director_manual.list_modes()

@router.put("/api/director/{channel}/control-mode")
async def set_control_mode(channel: str, data: dict) -> dict:
    try: return await director_manual.set_mode(channel, data.get("mode"))
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/operator/send")
async def operator_send(channel: str, data: dict) -> dict:
    try: return await director_manual.send(channel, data.get("account_id"), data.get("text"))
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/operator/messages")
async def operator_messages(channel: str, limit: int = 20) -> dict:
    try: return await director_manual.list_messages(channel, limit)
    except ValueError as exc: raise _error(exc) from exc

# Q36: глубина очереди канала — для подсказки оператору, пока темп отправки не даёт уйти сразу.
@router.get("/api/director/{channel}/operator/queue")
async def operator_queue(channel: str) -> dict:
    channel = director.normalize_channel(channel)
    return {"ok": True, "channel": channel, "pending": director_manual.queue_depth(channel)}

@router.post("/api/director/{channel}/operator/unfence")
async def operator_unfence(channel: str) -> dict:
    try: return await director_manual.unfence(channel)
    except ValueError as exc: raise _error(exc) from exc

# Q35: заготовки для ручной отправки (текст + позиция → хоткей Alt+1..Alt+9).
@router.get("/api/director/{channel}/manual/presets")
async def manual_presets(channel: str) -> dict:
    try: return await director_manual.list_presets(channel)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/manual/presets")
async def manual_preset_create(channel: str, data: dict) -> dict:
    try: return await director_manual.create_preset(channel, data.get("text"))
    except ValueError as exc: raise _error(exc) from exc

@router.put("/api/director/{channel}/manual/presets/{preset_id}")
async def manual_preset_update(channel: str, preset_id: int, data: dict) -> dict:
    try: return await director_manual.update_preset(channel, preset_id, data.get("text"))
    except ValueError as exc: raise _error(exc) from exc

@router.delete("/api/director/{channel}/manual/presets/{preset_id}")
async def manual_preset_delete(channel: str, preset_id: int) -> dict:
    try: return await director_manual.delete_preset(channel, preset_id)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/manual/presets/reorder")
async def manual_preset_reorder(channel: str, data: dict) -> dict:
    try: return await director_manual.reorder_presets(channel, data.get("order"))
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/status")
async def status(channel: str) -> dict:
    try: return await director.get_status(channel)
    except ValueError as exc: raise _error(exc) from exc

@router.put("/api/director/{channel}/config")
async def config(channel: str, data: dict) -> dict:
    try: return await director.save_config(channel, data.get("config"), data.get("worker_ids"), data.get("director_account_id"))
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/audit")
async def audit(channel: str, limit: int = 100, before_id: int | None = None) -> dict:
    try: return await director.list_audit(channel, limit=limit, before_id=before_id)
    except (TypeError, ValueError) as exc: raise _error(ValueError("invalid_audit_cursor")) from exc

@router.get("/api/director/{channel}/prompts")
async def prompts(channel: str) -> dict:
    try: return await director.list_prompt_versions(channel)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/prompts")
async def create_prompt(channel: str, data: dict) -> dict:
    try: return await director.create_prompt_version(channel, data.get("prompt_text"), replay_metadata=data.get("replay_metadata"))
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/prompts/{prompt_id}/tested")
async def test_prompt(channel: str, prompt_id: str, data: dict) -> dict:
    try:
        return await director.set_prompt_tested(channel, prompt_id, data.get("replay_metadata"))
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/prompts/{prompt_id}/activate")
async def activate_prompt(channel: str, prompt_id: str, data: dict) -> dict:
    try:
        await director.activate_prompt_version(channel, prompt_id, quality_confirmed=data.get("quality_confirmed", False), replay_run_id=data.get("replay_run_id"))
        return await director.list_prompt_versions(channel)
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/suggestions")
async def suggestions(channel: str) -> dict:
    try: return await director_review.list_suggestions(channel)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/suggestions/{plan_id}/approve")
async def approve_suggestion(channel: str, plan_id: str, data: dict) -> dict:
    try:
        return await director_review.review_suggestion(channel, plan_id, "approved", data.get("messages"), data.get("assets"))
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/suggestions/{plan_id}/reject")
async def reject_suggestion(channel: str, plan_id: str) -> dict:
    try: return await director_review.review_suggestion(channel, plan_id, "rejected")
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/reactions/live")
async def live_reactions(channel: str) -> dict:
    try: return await director_review.list_live_reactions(channel)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/reactions/live/{plan_id}/approve")
async def approve_reaction(channel: str, plan_id: str, data: dict) -> dict:
    try: return await director_review.review_live_reaction(channel, plan_id, "approved", data.get("texts"))
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/reactions/live/{plan_id}/reject")
async def reject_reaction(channel: str, plan_id: str, data: dict) -> dict:
    try: return await director_review.review_live_reaction(channel, plan_id, "rejected", data.get("texts"))
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/training/export")
async def export_training(channel: str) -> dict:
    try: return await director_review.export_training(channel)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/training/import")
async def import_training(channel: str, data: dict) -> dict:
    try:
        return await director_review.import_training(
            channel, data.get("data"), replace=bool(data.get("replace")), confirm=bool(data.get("confirm"))
        )
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/examples")
async def examples(channel: str, kind: str | None = None) -> dict:
    try: return await director_review.list_examples(channel, kind=kind)
    except ValueError as exc: raise _error(exc) from exc

@router.put("/api/director/{channel}/examples/{example_id}")
async def edit_example(channel: str, example_id: str, data: dict) -> dict:
    try: return await director_review.edit_example(channel, example_id, data.get("messages"))
    except ValueError as exc: raise _error(exc) from exc

@router.delete("/api/director/{channel}/examples/{example_id}")
async def delete_example(channel: str, example_id: str) -> dict:
    try: return await director_review.delete_example(channel, example_id)
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/builtin-moments")
async def builtin_moments(channel: str) -> dict:
    director.normalize_channel(channel)
    return {"ok": True, "channel": channel, "version": director_review.BUILTIN_MOMENTS_VERSION, "scenarios": director_review.BUILTIN_MOMENTS}

@router.get("/api/director/{channel}/prompts/{prompt_id}/diff")
async def prompt_diff(channel: str, prompt_id: str, against: str) -> dict:
    try: return await director.prompt_diff(channel, prompt_id, against)
    except ValueError as exc: raise _error(exc) from exc

@router.delete("/api/director/{channel}/prompts/{prompt_id}")
async def delete_prompt(channel: str, prompt_id: str) -> dict:
    try: return await director.delete_prompt_version(channel, prompt_id)
    except ValueError as exc: raise _error(exc) from exc

# ── Optional §8/§11: chant dictionary, templates, AI fake moments ──

@router.get("/api/director/{channel}/chants")
async def chants(channel: str) -> dict:
    return await director.chant_list(channel)

@router.post("/api/director/{channel}/chants")
async def add_chant(channel: str, data: dict) -> dict:
    from app.database import get_db
    db = await get_db()
    try:
        session = await (await db.execute(
            "SELECT id FROM director_sessions WHERE channel=? AND state IN ('training','suggest','live')", (channel,)
        )).fetchone()
    finally:
        await db.close()
    try:
        return await director.chant_add(channel, data.get("text", ""), source=data.get("source", "owner"), session_id=session[0] if session else None)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/chants/{chant_id}/approve")
async def approve_chant(channel: str, chant_id: str) -> dict:
    try: return await director.chant_approve(channel, chant_id)
    except ValueError as exc: raise _error(exc) from exc

@router.delete("/api/director/{channel}/chants/{chant_id}")
async def delete_chant(channel: str, chant_id: str) -> dict:
    try: return await director.chant_delete(channel, chant_id)
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/templates")
async def templates(channel: str) -> dict:
    return await director.template_list(channel)

@router.post("/api/director/{channel}/templates")
async def add_template(channel: str, data: dict) -> dict:
    try: return await director.template_add(channel, data.get("text", ""), data.get("mode", "exact"))
    except ValueError as exc: raise _error(exc) from exc

@router.delete("/api/director/{channel}/templates/{template_id}")
async def delete_template(channel: str, template_id: str) -> dict:
    try: return await director.template_delete(channel, template_id)
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/fake-moments")
async def fake_moments(channel: str) -> dict:
    return await director.fake_moments_list(channel)

@router.post("/api/director/{channel}/fake-moments/generate")
async def generate_moments(channel: str, data: dict) -> dict:
    try: return await director.generate_fake_moments(channel, data.get("scenario", ""), int(data.get("count", 3)))
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/sessions")
async def list_sessions(channel: str) -> dict:
    return await director.list_sessions(channel)

@router.get("/api/director/{channel}/sessions/{session_id}/storage")
async def session_storage(channel: str, session_id: str) -> dict:
    try: return await director.session_storage_manifest(channel, session_id)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/sessions/{session_id}/export")
async def export_session(channel: str, session_id: str) -> dict:
    try: return await director.export_session(channel, session_id)
    except ValueError as exc: raise _error(exc) from exc

@router.get("/api/director/{channel}/sessions/{session_id}/export/download")
async def download_session_export(channel: str, session_id: str, path: str):
    from fastapi.responses import FileResponse
    try:
        target = director.export_file(channel, session_id, path)
        return FileResponse(target, filename=target.name, media_type="application/zip")
    except ValueError as exc: raise _error(exc) from exc

@router.delete("/api/director/{channel}/sessions/{session_id}/evidence")
async def delete_session_evidence(channel: str, session_id: str, data: dict) -> dict:
    try: return await director.delete_session_evidence(channel, session_id, data.get("confirmation"))
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/sessions/{session_id}/assets/{asset_id}/pin")
async def pin_asset(channel: str, session_id: str, asset_id: int, data: dict) -> dict:
    try:
        return await director.set_frame_pin(channel, session_id, asset_id, bool(data.get("pinned", True)))
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/start")
async def start(channel: str) -> dict:
    try: return await director.start(channel)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/dry-run")
async def emergency_dry_run(channel: str) -> dict:
    try:
        return await director.scheduler.emergency_dry_run(channel)
    except ValueError as exc:
        raise _error(exc) from exc

@router.post("/api/director/{channel}/manual/{kind}/preview")
async def manual_preview(channel: str, kind: str) -> dict:
    try:
        return await director.scheduler.manual_plan_preview(channel, kind)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/manual/{kind}/confirm")
async def manual_confirm(channel: str, kind: str) -> dict:
    try:
        return await director.scheduler.manual_plan_confirm(channel, kind)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/{action}")
async def control(channel: str, action: str) -> dict:
    try: return await director.transition(channel, action)
    except ValueError as exc: raise _error(exc) from exc

@router.post("/api/director/{channel}/workers/{account_id}/join-now")
async def join_now(channel: str, account_id: int) -> dict:
    try:
        channel = director.normalize_channel(channel)
        await director.scheduler.join_now(channel, account_id)
        return await director.get_status(channel)
    except ValueError as exc: raise _error(exc) from exc


# ── Director Quick-Actions (Хоткеи и Stream Deck интеграция) ──
@router.api_route("/api/director/quick-action", methods=["GET", "POST"])
async def director_quick_action(request: Request) -> dict:
    """Stream Deck, OBS hotkeys and Director Quick-Actions.

    Поддерживает вызовы как GET (для Stream Deck 'Open Website' / curl),
    так и POST (с JSON телом из веб-панели).
    Actions:
      - 'pause_2m' / 'pause': пауза всех авто-ответов ботов на N сек (по умолчанию 120с)
      - 'resume' / 'unpause': немедленное снятие паузы
      - 'status': возвращает текущий статус паузы и оставшиеся секунды
      - 'hype_emotes': быстрый залп хайповых смайликов ботами без LLM (0 токенов)
      - 'break_silence': принудительный Smart Anti-Dead-Air вопрос для оживления чата
    """
    import asyncio, random
    from app.server import bot_manager, chat_analyzer

    params: dict = dict(request.query_params)
    if request.method == "POST":
        try:
            body = await request.json()
            if isinstance(body, dict):
                params.update(body)
        except Exception:
            pass

    action = (params.get("action") or "status").strip().lower()
    channel = (params.get("channel") or "").strip().lstrip("#").lower()
    try:
        duration = float(params.get("duration") or 120.0)
    except (ValueError, TypeError):
        duration = 120.0

    # 1. STATUS
    if action == "status":
        paused, remaining = chat_analyzer.is_paused()
        return {
            "ok": True,
            "action": "status",
            "paused": paused,
            "remaining_sec": remaining,
        }

    # 2. PAUSE
    if action in ("pause_2m", "pause"):
        chat_analyzer.pause_all(duration)
        return {
            "ok": True,
            "action": "pause",
            "paused": True,
            "remaining_sec": int(duration),
            "message": f"Боты приостановлены на {int(duration)}с",
        }

    # 3. RESUME
    if action in ("resume", "unpause"):
        chat_analyzer.resume_all()
        return {
            "ok": True,
            "action": "resume",
            "paused": False,
            "remaining_sec": 0,
            "message": "Пауза снята, боты активны",
        }

    # 4. TTS MUTE (Cinematic Mute: боты пишут в чат, только озвучка выключена)
    from app.tts_mute_state import set_tts_mute, clear_tts_mute, get_tts_mute_status
    if action in ("mute_tts", "mute_tts_5m"):
        minutes = float(params.get("minutes") or (duration / 60.0 if duration else 5.0))
        res = set_tts_mute(channel, minutes)
        return {
            "ok": True,
            "action": "mute_tts",
            "muted": True,
            "remaining_sec": res["remaining_sec"],
            "message": res["message"],
        }

    if action in ("unmute_tts", "tts_unmute"):
        res = clear_tts_mute(channel)
        return {
            "ok": True,
            "action": "unmute_tts",
            "muted": False,
            "remaining_sec": 0,
            "message": res["message"],
        }

    if action == "tts_mute_status":
        return get_tts_mute_status(channel)

    # Для действий, привязанных к каналу (hype_emotes, break_silence):
    statuses = bot_manager.get_all_statuses()

    # Если канал не передан явно — берем первый активный подключенный канал
    if not channel:
        for aid, st in statuses.items():
            if st.get("connected") and st.get("channels"):
                channel = st["channels"][0].lstrip("#").lower()
                break
        if not channel:
            from app.database import get_db
            db = await get_db()
            try:
                row = await (await db.execute("SELECT name FROM channels ORDER BY id LIMIT 1")).fetchone()
                if row:
                    channel = row[0].lstrip("#").lower()
            finally:
                await db.close()

    if not channel:
        return {"ok": False, "error": "channel_not_found", "message": "Не найден активный канал"}

    # Боты, подключённые к этому каналу
    channel_bots: list[tuple[int, str]] = []
    for aid, st in statuses.items():
        chans = [c.lstrip("#").lower() for c in st.get("channels", [])]
        if channel in chans and st.get("connected"):
            channel_bots.append((aid, st.get("nickname") or f"bot_{aid}"))

    # 4. HYPE EMOTES
    if action == "hype_emotes":
        if not channel_bots:
            return {"ok": False, "error": "no_bots_online", "message": f"Нет подключённых ботов на канале #{channel}"}

        # Определяем популярный эмоут из буфера или дефолтный список
        chosen_emote = "KEKW"
        for aid, nick in channel_bots:
            buf_key = chat_analyzer._buffer_key(aid, channel)
            recent = chat_analyzer._chat_buffer.get(buf_key, [])
            if recent:
                for m in reversed(recent[-15:]):
                    txt = m.get("text", "")
                    words = txt.split()
                    for w in words:
                        if w.upper() in ("KEKW", "POG", "LUL", "OMEGALUL", "HYPERS", "CLAP", "EZ", "AYAYA", "POGCHAMP"):
                            chosen_emote = w
                            break
                    if chosen_emote != "KEKW":
                        break
            if chosen_emote != "KEKW":
                break

        if chosen_emote == "KEKW":
            chosen_emote = random.choice(["KEKW", "Pog", "LUL", "PogChamp", "Clap", "EZ"])

        selected = channel_bots[:4]
        variations = [
            chosen_emote,
            f"{chosen_emote} {chosen_emote}",
            f"{chosen_emote}!",
            f"{chosen_emote} {chosen_emote} {chosen_emote}",
        ]
        random.shuffle(variations)

        sent_count = 0
        for i, (aid, nick) in enumerate(selected):
            text = variations[i % len(variations)]
            delay = i * random.uniform(0.2, 0.5)

            async def _send(b_aid=aid, b_text=text, b_delay=delay):
                if b_delay > 0:
                    await asyncio.sleep(b_delay)
                try:
                    await bot_manager.send_message(b_aid, channel, b_text)
                except Exception:
                    pass

            asyncio.create_task(_send())
            sent_count += 1

        return {
            "ok": True,
            "action": "hype_emotes",
            "channel": channel,
            "sent_count": sent_count,
            "emote": chosen_emote,
            "message": f"Хайп {chosen_emote} запущен ({sent_count} ботов)",
        }

    # 5. BREAK SILENCE
    if action == "break_silence":
        if not channel_bots:
            return {"ok": False, "error": "no_bots_online", "message": f"Нет подключённых ботов на канале #{channel}"}

        # Фильтруем только ботов с правом инициативной отправки сообщений (исключаем lurker, director, silent)
        chat_bots: list[tuple[int, str]] = []
        for aid, nick in channel_bots:
            allowed, _ = await chat_analyzer._role_reply_gate(aid, is_mention=False)
            if allowed:
                chat_bots.append((aid, nick))

        if not chat_bots:
            return {
                "ok": False,
                "error": "no_chat_bots_online",
                "message": f"Нет ботов с правом писать в чат на канале #{channel} (боты в роли lurker/director молчат)",
            }

        aid = bot_manager.get_least_recently_spoken_bot(channel, [b[0] for b in chat_bots])
        if aid is None:
            aid = chat_bots[0][0]
        nick = next((b[1] for b in chat_bots if b[0] == aid), f"bot_{aid}")

        success = await chat_analyzer.check_dead_air(aid, channel, nick, force=True)
        if not success:
            return {
                "ok": False,
                "error": "dispatch_failed",
                "message": f"Не удалось отправить вопрос для оживления через {nick}",
            }
        return {
            "ok": True,
            "action": "break_silence",
            "channel": channel,
            "bot": nick,
            "dispatched": True,
            "message": f"Вопрос для оживления отправлен через {nick}",
        }

    return {"ok": False, "error": "unknown_action", "message": f"Неизвестное действие: {action}"}
