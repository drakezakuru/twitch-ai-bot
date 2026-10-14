"""snippets — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
import asyncio
from typing import Any

from fastapi import HTTPException, Request

from app.database import get_db
from app.routes import (
    router,
    logger, log_action,
    learning_mod, personality_shift, streamer_lore, summarizer, user_memory,
)


# ===================== SNIPPETS =====================

@router.get("/api/accounts/{account_id}/snippets")
async def list_snippets(account_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM snippets WHERE account_id = ? ORDER BY id", (account_id,))
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/snippets")
async def create_snippet(account_id: int, data: dict[str, Any]) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO snippets (account_id, name, text) VALUES (?, ?, ?)",
            (account_id, data.get("name", "unnamed"), data.get("text", "")),
        )
        await db.commit()
        return {"ok": True, "snippet_id": cur.lastrowid}
    finally:
        await db.close()


async def _delete_snippet(account_id: int, snippet_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM snippets WHERE id = ? AND account_id = ?",
            (snippet_id, account_id),
        )
        await db.commit()
        return {"ok": cur.rowcount > 0}
    finally:
        await db.close()


async def _update_snippet(account_id: int, snippet_id: int, data: dict[str, Any]) -> dict:
    name = str(data.get("name") or "").strip()
    text = str(data.get("text") or "").strip()
    if not name or not text:
        return {"ok": False, "error": "name and text are required"}
    db = await get_db()
    try:
        cur = await db.execute(
            "UPDATE snippets SET name = ?, text = ? WHERE id = ? AND account_id = ?",
            (name[:120], text[:500], snippet_id, account_id),
        )
        await db.commit()
        return {"ok": cur.rowcount > 0}
    finally:
        await db.close()


@router.delete("/api/accounts/{account_id}/snippets/{snippet_id}")
async def delete_account_snippet(account_id: int, snippet_id: int) -> dict:
    return await _delete_snippet(account_id, snippet_id)


@router.put("/api/accounts/{account_id}/snippets/{snippet_id}")
async def update_account_snippet(
    account_id: int, snippet_id: int, data: dict[str, Any]
) -> dict:
    """Update a saved phrase used by the quick-snippet panel."""
    return await _update_snippet(account_id, snippet_id, data)


@router.delete("/api/snippets/{snippet_id}")
async def delete_snippet(snippet_id: int, account_id: int) -> dict:
    """Compatibility route; account scope is mandatory and fail-closed."""
    return await _delete_snippet(account_id, snippet_id)


@router.put("/api/snippets/{snippet_id}")
async def update_snippet(
    snippet_id: int, account_id: int, data: dict[str, Any]
) -> dict:
    """Compatibility route; account scope is mandatory and fail-closed."""
    return await _update_snippet(account_id, snippet_id, data)


# ==================== CHARACTER IMPORT ====================

@router.post("/api/persona/import")
async def import_persona(request: Request, account_id: int):
    """Імпорт характеру за ником (чатер/стример).
    
    - Бере останні повідомлення з chat_log за ником
    - Аналізує стиль мови та теми  
    - Генерує біографію та характер через AI
    """
    import json
    import re as regex
    
    body = await request.json()
    nickname = body.get("nickname", "").strip()
    source = body.get("source", "chat")
    streamer = body.get("streamer", "").strip()
    
    if not nickname:
        raise HTTPException(400, {"error": "Nickname обов'язковий"})
    
    from app.ai_service import generate_text
    from app.database import get_db
    
    try:
        # 1. Отримуємо останні повідомлення з chat_log за ником
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT author, message FROM chat_log "
                "WHERE lower(author) = lower(?) "
                + ("AND lower(channel) = lower(?) " if streamer else "")
                + "ORDER BY timestamp DESC LIMIT 200",
                ((nickname, streamer) if streamer else (nickname,))
            )
            rows = await cur.fetchall()
        finally:
            await db.close()
        
        if not rows:
            raise HTTPException(404, {"error": f"Повідомлень від {nickname} не знайдено"})
        
        # 2. Підготовка контексту для AI
        msg_sample = "\n".join(f"{r['author']}: {r['message']}" for r in rows[:50])
        
        # 3. Генерація біографії через AI
        prompt = f"""
Сформуй коротку біографію та характер для Twitch бота, який імітує стиль обговорення користувача:

Нік: {nickname}
Тип користувача: {source}
Останні повідомлення:
{msg_sample[:2000]}

Напиши JSON з полями: name, age, gender, personality (масив), humor_level (0-100), seriousness (0-100), contact_level (0-100), hobbies, favorite_games.
Формат JSON лише, без зайвого тексту.
"""
        
        generated = await generate_text(prompt, account_id=account_id)
        
        # Парсимо JSON відповідь
        try:
            json_match = regex.search(r'\{.*\}', generated, regex.DOTALL)
            if json_match:
                persona_data = json.loads(json_match.group())
            else:
                persona_data = {
                    "name": nickname,
                    "age": 25,
                    "gender": "невизначено", 
                    "personality": ["дружній"],
                    "humor_level": 50,
                    "seriousness": 50,
                    "contact_level": 60
                }
        except (json.JSONDecodeError, AttributeError):
            persona_data = {
                "name": nickname,
                "age": 25,
                "gender": "невизначено",
                "personality": ["дружній"],
                "humor_level": 50,
                "seriousness": 50,
                "contact_level": 60
            }
        
        return {"success": True, "persona": persona_data, "messages_count": len(rows)}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Character import error: {e}")
        raise HTTPException(500, {"error": str(e)})


# ==================== v12: CHARACTER EXPORT (приватний) ====================

@router.get("/api/accounts/{account_id}/export")
async def export_character(account_id: int) -> dict:
    """Експорт персони та налаштувань бота (приватний JSON)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        acc = await cursor.fetchone()
        if not acc:
            return {"error": "not found"}
        # Триггери
        cursor = await db.execute(
            "SELECT keyword, response, use_ai FROM triggers WHERE account_id = ?",
            (account_id,),
        )
        triggers = [dict(r) for r in await cursor.fetchall()]
        # Персона
        persona_json = acc["persona_json"] if "persona_json" in acc.keys() else ""
        persona = {}
        if persona_json:
            try:
                import json as _json
                persona = _json.loads(persona_json)
            except Exception:
                pass
    finally:
        await db.close()
    export_data = {
        "version": "v12",
        "nickname": acc["nickname"],
        "persona": persona,
        "triggers": triggers,
    }
    return {"ok": True, "export": export_data}


@router.post("/api/accounts/{account_id}/export/import")
async def import_character(account_id: int, data: dict[str, Any]) -> dict:
    """Імпорт персони та налаштувань з export JSON."""
    export = data.get("export") or data
    if not export.get("nickname"):
        return {"ok": False, "error": "export data required"}
    db = await get_db()
    try:
        # Оновлюємо персону
        import json as _json
        persona = export.get("persona") or {}
        if persona:
            await db.execute(
                "UPDATE accounts SET persona_json = ? WHERE id = ?",
                (_json.dumps(persona, ensure_ascii=False), account_id),
            )
        # Додаємо триггери
        for t in export.get("triggers", []):
            await db.execute(
                "INSERT INTO triggers (account_id, keyword, response, use_ai) VALUES (?, ?, ?, ?)",
                (account_id, t.get("keyword", ""), t.get("response", ""), t.get("use_ai", 1)),
            )
        await db.commit()
    finally:
        await db.close()
    await log_action("character_import", f"account={account_id} from export")
    return {"ok": True}


# ==================== v12: GENERATE SNIPPETS ====================

@router.post("/api/ai/generate-snippets")
async def generate_snippets(data: dict[str, Any]) -> dict:
    """Генерирует случайные заготовки для бота через AI (A4: причина пустого результата — в ответ и в логи)."""
    import logging
    from app.server import ai_service
    logger = logging.getLogger("twitchbot")
    account_id = int(data.get("account_id") or 0)
    count = max(1, min(10, int(data.get("count") or 5)))
    prompt = (
        f"Сгенерируй {count} коротких заготовок для Twitch-бота (на русском). "
        f"Это готовые фразы для быстрых ответов в чате. "
        f"Каждая фраза — 5-15 слов, неформальная, как у живого зрителя. "
        f"Верни JSON массив: [{{name: '...', text: '...'}}, ...]"
    )
    try:
        result = await ai_service.generate_text(
            prompt,
            system="Ты генерируешь заготовки для Twitch-бота. Верни только JSON.",
            account_id=account_id,
        )
        # Парсимо JSON
        import json as _json
        import re as _re
        json_match = _re.search(r'\[.*\]', result or '', _re.DOTALL)
        if not json_match:
            reason = "no_json" if (result or '').strip() else "empty"
            logger.warning("generate-snippets #%s: %s (сырой ответ: %.200r)", account_id, reason, result)
            return {"ok": True, "snippets": [], "reason": reason}
        try:
            snippets = _json.loads(json_match.group())
        except Exception as parse_exc:
            logger.warning("generate-snippets #%s: json_parse_error %s", account_id, parse_exc)
            return {"ok": True, "snippets": [], "reason": "json_parse_error"}
        return {"ok": True, "snippets": snippets[:count]}
    except Exception as exc:
        logger.warning("generate-snippets #%s: ai_error %s", account_id, exc)
        return {"ok": False, "error": str(exc), "reason": "ai_error"}


# ==================== OPS_PLAN §1: Bot Files (per-bot папки) ====================

# Разрешённые текстовые расширения (план §1: только текстовые файлы)
BOT_FILES_TEXT_EXTS = {".json", ".md", ".txt", ".log", ".csv", ".yaml", ".yml", ".ini", ".cfg", ".vtt", ".srt"}
# Лимит размера файла для чтения/записи через панель
BOT_FILES_MAX_SIZE = 256 * 1024


def _bot_files_allowed(name: str) -> bool:
    """True, если файл можно открыть в панели (только текстовые расширения)."""
    p = name.lower()
    return any(p.endswith(ext) for ext in BOT_FILES_TEXT_EXTS)


async def _bot_files_account(account_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT id, nickname FROM accounts WHERE id = ?", (account_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


@router.get("/api/accounts/{account_id}/files")
async def bot_files_list(account_id: int) -> dict:
    """Список файлов в per-bot папке. Структуру создаёт идемпотентно."""
    acc = await _bot_files_account(account_id)
    if not acc:
        return {"ok": False, "error": "account_not_found"}
    from app.bot_dirs import init_bot_dir, list_bot_files
    bot_dir = init_bot_dir(account_id, acc["nickname"])
    files = await list_bot_files(account_id, acc["nickname"])
    for f in files:
        f["editable"] = _bot_files_allowed(f["path"]) and f["size"] <= BOT_FILES_MAX_SIZE
    return {"ok": True, "bot_dir": bot_dir.name, "files": files}


@router.get("/api/accounts/{account_id}/files/{file_path:path}")
async def bot_files_read(account_id: int, file_path: str) -> dict:
    """Прочитать текстовый файл из папки бота (лимит 256КБ, только текст)."""
    acc = await _bot_files_account(account_id)
    if not acc:
        return {"ok": False, "error": "account_not_found"}
    from app.bot_dirs import read_bot_file
    if not _bot_files_allowed(file_path):
        return {"ok": False, "error": "file_type_not_allowed"}
    content = await read_bot_file(account_id, file_path, acc["nickname"])
    if content is None:
        return {"ok": False, "error": "not_found"}
    if len(content.encode("utf-8")) > BOT_FILES_MAX_SIZE:
        return {"ok": False, "error": "file_too_large"}
    return {"ok": True, "path": file_path, "content": content}


@router.put("/api/accounts/{account_id}/files/{file_path:path}")
async def bot_files_write(account_id: int, file_path: str, data: dict[str, Any]) -> dict:
    """Записать текстовый файл (лимит 256КБ, только текстовые расширения)."""
    acc = await _bot_files_account(account_id)
    if not acc:
        return {"ok": False, "error": "account_not_found"}
    from app.bot_dirs import write_bot_file
    content = data.get("content")
    if not isinstance(content, str):
        return {"ok": False, "error": "content_required"}
    if not _bot_files_allowed(file_path):
        return {"ok": False, "error": "file_type_not_allowed"}
    if len(content.encode("utf-8")) > BOT_FILES_MAX_SIZE:
        return {"ok": False, "error": "file_too_large"}
    ok = await write_bot_file(account_id, file_path, content, acc["nickname"])
    if not ok:
        return {"ok": False, "error": "path_traversal_blocked"}
    await log_action("bot_file_write", f"account={account_id} path={file_path}")
    return {"ok": True}


@router.delete("/api/accounts/{account_id}/files/{file_path:path}")
async def bot_files_delete(account_id: int, file_path: str) -> dict:
    """Удалить файл из папки бота (path traversal закрыт в bot_dirs)."""
    acc = await _bot_files_account(account_id)
    if not acc:
        return {"ok": False, "error": "account_not_found"}
    from app.bot_dirs import delete_bot_file
    if not _bot_files_allowed(file_path):
        return {"ok": False, "error": "file_type_not_allowed"}
    ok = await delete_bot_file(account_id, file_path, acc["nickname"])
    if not ok:
        return {"ok": False, "error": "not_found"}
    await log_action("bot_file_delete", f"account={account_id} path={file_path}")
    return {"ok": True}


# ============== v16 BRAIN_PLAN: §1 Память (priority/TTL/confirmed) ==============


@router.post("/api/accounts/{account_id}/memory/{username}/confirm")
async def memory_fact_confirm(account_id: int, username: str, data: dict) -> dict:
    """Помечает факт как подтверждённый (или снимает подтверждение).

    body: {fact: str, confirmed: bool = true}
    """
    fact = (data.get("fact") or "").strip()
    if not fact:
        return {"ok": False, "error": "fact_required"}
    confirmed = bool(data.get("confirmed", True))
    ok = await user_memory.set_fact_confirmed(account_id, username, fact, confirmed=confirmed)
    if not ok:
        return {"ok": False, "error": "fact_not_found"}
    await log_action(
        "memory_fact_confirm",
        f"account={account_id} user={username} fact={fact[:60]} confirmed={confirmed}",
    )
    return {"ok": True}


@router.post("/api/accounts/{account_id}/memory_gc")
async def memory_gc_run(account_id: int) -> dict:
    """Прогон GC: чистит просроченные факты."""
    n = await user_memory.gc_expired_facts(account_id=account_id)
    await log_action("memory_gc", f"account={account_id} removed={n}")
    return {"ok": True, "removed": n}


@router.post("/api/accounts/{account_id}/memory_auto_extract")
async def memory_auto_extract(account_id: int, data: dict | None = None) -> dict:
    """Запускает авто-извлечение фактов для активных юзеров (на основе истории сообщений).

    body: {channel: str, usernames: [..]?, min_confidence: 0.6?, max_facts_per_user: 3?}
    Если usernames не заданы — берём топ-10 по активности.
    """
    from app.ai_service import AIService
    data = data or {}
    # D (REWORK_PLAN): рубильник «Обучение» per-bot — выключено = факты не извлекаем
    try:
        from app.server import chat_analyzer
        if not chat_analyzer.get_settings(account_id).get("influence_learning", True):
            return {"ok": True, "skipped": "influence_learning_off", "facts": []}
    except Exception:
        pass
    channel = (data.get("channel") or "").strip().lower().lstrip("#")
    min_conf = float(data.get("min_confidence", 0.6) or 0.6)
    max_per = int(data.get("max_facts_per_user", 3) or 3)
    usernames = data.get("usernames")
    ai = AIService()  # используем глобальный сервис (per-account override сработает)
    if not usernames:
        try:
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT username, message_count FROM chat_users "
                    "WHERE account_id = ? AND message_count >= 5 "
                    "ORDER BY message_count DESC LIMIT 10",
                    (account_id,),
                )
                usernames = [r["username"] for r in await cur.fetchall()]
            finally:
                await db.close()
        except Exception:
            usernames = []
    found: list[dict] = []
    for u in usernames or []:
        try:
            facts = await user_memory.auto_extract_facts_for(
                account_id, u,
                min_message_count=5,
                max_facts=max_per,
                confidence_threshold=min_conf,
                ai_service=ai,
                channel=channel,
            )
        except Exception:
            facts = []
        for f in facts:
            new_id = await streamer_lore.add_suggestion(
                account_id, channel, f["fact"],
                source="auto", confidence=f.get("confidence", 0.6),
                importance=50,
            )
            found.append({
                "username": u,
                "fact": f["fact"],
                "confidence": f.get("confidence"),
                "lore_id": new_id,
            })
    await log_action(
        "memory_auto_extract",
        f"account={account_id} channel={channel} candidates={len(found)}",
    )
    return {"ok": True, "candidates": found}


# ============== v16 BRAIN_PLAN: §5 Streamer Lore ==============


@router.get("/api/accounts/{account_id}/lore")
async def lore_list(
    account_id: int, channel: str = "", status: str | None = None, limit: int = 100
) -> dict:
    items = await streamer_lore.list_lore(account_id, channel, status=status, limit=limit)
    return {"items": items, "total": len(items)}


@router.post("/api/accounts/{account_id}/lore")
async def lore_add(account_id: int, data: dict) -> dict:
    channel = (data.get("channel") or "").strip().lower().lstrip("#")
    fact = (data.get("fact") or "").strip()
    if not fact:
        return {"ok": False, "error": "fact_required"}
    try:
        confidence = float(data.get("confidence", 0.7) or 0.7)
    except (TypeError, ValueError):
        confidence = 0.7
    try:
        importance = int(data.get("importance", 50) or 50)
    except (TypeError, ValueError):
        importance = 50
    source = (data.get("source") or "manual").strip().lower()
    evidence = (data.get("evidence") or "").strip()
    expires_at = (data.get("expires_at") or "").strip() or None
    new_id = await streamer_lore.add_suggestion(
        account_id, channel, fact,
        source=source, evidence=evidence,
        confidence=confidence, importance=importance,
        expires_at=expires_at,
    )
    if not new_id:
        return {"ok": False, "error": "db_error"}
    # Если сразу просили approved (из UI «сохранить и подтвердить»)
    if data.get("approved"):
        await streamer_lore.approve(new_id)
    await log_action(
        "lore_add",
        f"account={account_id} ch={channel} source={source} fact={fact[:60]}",
    )
    return {"ok": True, "id": new_id, "approved": bool(data.get("approved"))}


@router.post("/api/accounts/{account_id}/lore/{lore_id}/approve")
async def lore_approve(account_id: int, lore_id: int) -> dict:
    ok = await streamer_lore.approve(lore_id)
    if ok:
        await log_action("lore_approve", f"account={account_id} lore_id={lore_id}")
    return {"ok": ok}


@router.post("/api/accounts/{account_id}/lore/{lore_id}/reject")
async def lore_reject(account_id: int, lore_id: int) -> dict:
    ok = await streamer_lore.reject(lore_id)
    if ok:
        await log_action("lore_reject", f"account={account_id} lore_id={lore_id}")
    return {"ok": ok}


@router.put("/api/accounts/{account_id}/lore/{lore_id}")
async def lore_update(account_id: int, lore_id: int, data: dict) -> dict:
    kwargs: dict[str, Any] = {}
    if "fact" in data:
        kwargs["fact"] = data.get("fact")
    if "importance" in data:
        try:
            kwargs["importance"] = int(data.get("importance"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_importance"}
    if "expires_at" in data:
        kwargs["expires_at"] = data.get("expires_at")
    ok = await streamer_lore.update_fact(lore_id, **kwargs)
    if ok:
        await log_action("lore_update", f"account={account_id} lore_id={lore_id}")
    return {"ok": ok}


@router.delete("/api/accounts/{account_id}/lore/{lore_id}")
async def lore_delete(account_id: int, lore_id: int) -> dict:
    ok = await streamer_lore.delete_lore(lore_id)
    if ok:
        await log_action("lore_delete", f"account={account_id} lore_id={lore_id}")
    return {"ok": ok}


# ============== v16 BRAIN_PLAN: §6 Safe Auto-Learning ==============


@router.get("/api/accounts/{account_id}/learning")
async def learning_list(
    account_id: int, channel: str = "", status: str | None = None,
    kind: str | None = None, limit: int = 100,
) -> dict:
    items = await learning_mod.list_suggestions(
        account_id, channel, status=status, kind=kind, limit=limit
    )
    return {"items": items, "total": len(items)}


@router.post("/api/accounts/{account_id}/learning")
async def learning_add(account_id: int, data: dict) -> dict:
    kind = (data.get("kind") or "").strip()
    payload = data.get("payload") or {}
    if kind not in learning_mod.VALID_KINDS:
        return {"ok": False, "error": "invalid_kind"}
    new_id = await learning_mod.add_suggestion(
        account_id, (data.get("channel") or ""),
        kind, payload,
        reason=(data.get("reason") or "")[:300],
        source=(data.get("source") or "manual")[:32],
        confidence=float(data.get("confidence", 0.5) or 0.5),
    )
    if not new_id:
        return {"ok": False, "error": "db_error"}
    await log_action("learning_add", f"account={account_id} kind={kind} id={new_id}")
    return {"ok": True, "id": new_id}


@router.post("/api/accounts/{account_id}/learning/{suggestion_id}/apply")
async def learning_apply(account_id: int, suggestion_id: int) -> dict:
    """Применяет предложение. Реальное действие зависит от kind.

    kind=style_example: добавляет в style_examples
    kind=kb_topic:     добавляет в streamer_kb
    kind=banned_topic: добавляет в banned_topics
    kind=persona_delta: пишет только в action_log (нет прямого эффекта)
    """
    s = await learning_mod.get_suggestion(account_id, suggestion_id)
    if not s:
        return {"ok": False, "error": "not_found"}
    if s.get("status") != "pending":
        return {"ok": False, "error": "not_pending"}
    payload = s.get("payload") or {}
    kind = s.get("kind")
    channel = s.get("channel", "")
    applied_action = "noop"
    try:
        if kind == "style_example":
            from app.ai_quality_db import add_style_example
            await add_style_example(
                account_id,
                str(payload.get("message") or "")[:500],
                channel=channel,
                note=str(payload.get("note") or "")[:200],
            )
            applied_action = "style_example_added"
        elif kind == "kb_topic":
            from app.ai_quality_db import add_kb
            await add_kb(
                account_id,
                str(payload.get("topic") or "")[:200],
                str(payload.get("content") or "")[:2000],
                tags=str(payload.get("tags") or "")[:200],
                priority=int(payload.get("priority", 5) or 5),
            )
            applied_action = "kb_added"
        elif kind == "banned_topic":
            from app.ai_quality_db import add_banned_topic
            await add_banned_topic(
                account_id,
                str(payload.get("pattern") or "")[:200],
                str(payload.get("fallback") or "")[:200],
                str(payload.get("mode") or "silent"),
            )
            applied_action = "banned_topic_added"
        elif kind == "persona_delta":
            applied_action = "persona_delta_logged"
    except Exception as exc:
        return {"ok": False, "error": f"apply_failed: {exc}"}
    await learning_mod.apply_suggestion(account_id, suggestion_id)
    await log_action(
        "learning_apply",
        f"account={account_id} id={suggestion_id} kind={kind} action={applied_action}",
    )
    return {"ok": True, "applied_action": applied_action}


@router.post("/api/accounts/{account_id}/learning/{suggestion_id}/reject")
async def learning_reject(account_id: int, suggestion_id: int) -> dict:
    ok = await learning_mod.reject_suggestion(account_id, suggestion_id)
    if ok:
        await log_action("learning_reject", f"account={account_id} id={suggestion_id}")
    return {"ok": ok}


@router.post("/api/accounts/{account_id}/learning/{suggestion_id}/revert")
async def learning_revert(account_id: int, suggestion_id: int) -> dict:
    """Помечает applied предложение как reverted (без физического отката)."""
    ok = await learning_mod.mark_reverted(account_id, suggestion_id)
    if ok:
        await log_action("learning_revert", f"account={account_id} id={suggestion_id}")
    return {"ok": ok}


# ============== v16 BRAIN_PLAN: §4 Stream Summarizer API ==============


@router.get("/api/accounts/{account_id}/summarizer/runs")
async def summarizer_list_runs(account_id: int, channel: str = "", limit: int = 50) -> dict:
    items = await summarizer.list_runs(account_id, channel, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/api/accounts/{account_id}/summarizer/runs/{run_id}")
async def summarizer_get_run(account_id: int, run_id: int) -> dict:
    run = await summarizer.get_run(run_id)
    if not run or int(run.get("account_id", -1)) != int(account_id):
        return {"ok": False, "error": "not_found"}
    checkpoints = await summarizer.get_checkpoints(run_id)
    return {"ok": True, "run": run, "checkpoints": checkpoints}


@router.post("/api/accounts/{account_id}/summarizer/runs")
async def summarizer_create_run(account_id: int, data: dict) -> dict:
    """Создаёт прогон (pending) и сразу запускает в фоне.

    body: {channel: str, period_start: ISO, period_end: ISO, lang: 'ru'|'en'?}
    """
    from datetime import datetime, timezone
    channel = (data.get("channel") or "").strip().lower().lstrip("#")
    try:
        pstart = datetime.fromisoformat(str(data.get("period_start", "")).replace("Z", "+00:00"))
        pend = datetime.fromisoformat(str(data.get("period_end", "")).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return {"ok": False, "error": "bad_period"}
    if pstart.tzinfo is None:
        pstart = pstart.replace(tzinfo=timezone.utc)
    if pend.tzinfo is None:
        pend = pend.replace(tzinfo=timezone.utc)
    lang = (data.get("lang") or "ru").lower()
    run = await summarizer.create_run(account_id, channel, pstart, pend, lang=lang)
    if not run:
        return {"ok": False, "error": "create_failed"}
    run_id = int(run["id"])
    # Запускаем фоновую задачу — берём ai_service из server
    try:
        from app.server import ai_service as _ai
        from app import streamer_lore as _lore

        async def _lore_suggester(rid: int, lore_json: list) -> None:
            run = await summarizer.get_run(rid)
            if not run:
                return
            ch = run.get("channel", "")
            for it in (lore_json or []):
                fact = (it.get("fact") or "").strip()
                if not fact:
                    continue
                try:
                    conf = float(it.get("confidence") or 0.6)
                except (TypeError, ValueError):
                    conf = 0.6
                try:
                    imp = int(it.get("importance") or 50)
                except (TypeError, ValueError):
                    imp = 50
                await _lore.add_suggestion(
                    account_id, ch, fact,
                    source="summary",
                    evidence=f"summarizer run {rid}",
                    confidence=conf, importance=imp,
                )

        asyncio.create_task(
            summarizer.execute_run(
                run_id, _ai,
                window_minutes=int(data.get("window_minutes") or 30),
                language=lang,
                lore_suggester=_lore_suggester,
            )
        )
    except Exception as exc:
        logger.warning("summarizer background start error: %s", exc)
    await log_action("summarizer_run", f"account={account_id} ch={channel} run_id={run_id}")
    return {"ok": True, "run_id": run_id}


@router.delete("/api/accounts/{account_id}/summarizer/runs/{run_id}")
async def summarizer_delete_run(account_id: int, run_id: int) -> dict:
    run = await summarizer.get_run(run_id)
    if not run or int(run.get("account_id", -1)) != int(account_id):
        return {"ok": False, "error": "not_found"}
    ok = await summarizer.delete_run(run_id)
    if ok:
        await log_action("summarizer_run_delete", f"account={account_id} run_id={run_id}")
    return {"ok": ok}


@router.get("/api/accounts/{account_id}/summarizer/live")
async def summarizer_live(account_id: int, channel: str = "", limit: int = 5) -> dict:
    from datetime import datetime, timezone
    digest = await summarizer.get_live_digest(account_id, channel, since=None)
    return {"ok": True, "digest": digest}


# ============== v16 BRAIN_PLAN: §7 Personality Shift API ==============
# P8-C4: ручные GET/POST /shift (карточка «Personality Shift») удалены —
# ручной Shift убран по вердикту владельца. Оставлен только /shift/trigger —
# им пользуется автоматика (raid-триггер в chat_analyzer).


@router.post("/api/accounts/{account_id}/shift/trigger")
async def shift_trigger(account_id: int, data: dict) -> dict:
    channel = (data.get("channel") or "").strip().lower().lstrip("#")
    kind = (data.get("kind") or "raid").strip().lower()
    st = personality_shift.shift_manager.trigger(
        account_id, channel, kind,
        duration_sec=int(data.get("duration_sec") or 300),
        mood_delta=float(data.get("mood_delta") or 0.0),
        emotionality_delta=float(data.get("emotionality_delta") or 0.0),
        reason=str(data.get("reason") or "manual")[:200],
    )
    if not st:
        return {"ok": False, "error": "not_triggered"}
    return {"ok": True, "state": st.to_dict()}
