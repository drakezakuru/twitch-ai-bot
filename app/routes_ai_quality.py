"""ai_quality — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any
from fastapi import HTTPException
from app.routes import router, log_action, router  # noqa: E402


# ===================== v8 AI QUALITY =====================

# Импорт v8 модулей здесь чтобы избежать циклов
from app import ai_quality_db as _aiq


@router.get("/api/accounts/{account_id}/kb")
async def list_kb_route(account_id: int, channel: str = "") -> dict:
    """v8 Feature 11: список знаний стримера. §5: channel — фильтр по каналу."""
    items = await _aiq.list_kb(account_id, channel=channel)
    return {"items": items}


@router.post("/api/accounts/{account_id}/kb")
async def add_kb_route(account_id: int, payload: dict) -> dict:
    topic = (payload.get("topic") or "").strip()
    content = (payload.get("content") or "").strip()
    if not topic or not content:
        return {"error": "topic_and_content_required"}
    tags = (payload.get("tags") or "").strip()
    priority = max(1, min(10, int(payload.get("priority") or 5)))
    channel = (payload.get("channel") or "").strip().lower()
    new_id = await _aiq.add_kb(account_id, topic, content, tags, priority, channel=channel)
    await log_action("kb_add", f"#{account_id} {topic}")
    return {"id": new_id}


@router.put("/api/accounts/{account_id}/kb/{kb_id}")
async def update_kb_route(account_id: int, kb_id: int, payload: dict) -> dict:
    fields: dict[str, Any] = {}
    for k in ("topic", "content", "tags", "priority", "enabled"):
        if k in payload:
            fields[k] = payload[k]
    ok = await _aiq.update_kb(account_id, kb_id, **fields)
    if not ok:
        raise HTTPException(status_code=404, detail="knowledge item not found")
    return {"ok": ok}


@router.delete("/api/accounts/{account_id}/kb/{kb_id}")
async def delete_kb_route(account_id: int, kb_id: int) -> dict:
    if not await _aiq.delete_kb(account_id, kb_id):
        raise HTTPException(status_code=404, detail="knowledge item not found")
    return {"ok": True}


@router.get("/api/accounts/{account_id}/kb/search")
async def search_kb_route(account_id: int, q: str = "", top_k: int = 3) -> dict:
    """v8 Feature 11: поиск по knowledge base (для дебага в UI)."""
    top_k = max(1, min(20, int(top_k)))
    items = await _aiq.retrieve_kb_for_query(account_id, q, top_k=top_k)
    return {"query": q, "results": items}


@router.get("/api/accounts/{account_id}/style-examples")
async def list_style_examples_route(account_id: int, channel: str = "", limit: int = 100) -> dict:
    """v8 Feature 6: список few-shot примеров стиля."""
    limit = max(1, min(500, int(limit)))
    items = await _aiq.list_style_examples(account_id, channel=channel, limit=limit)
    return {"items": items}


@router.post("/api/accounts/{account_id}/style-examples")
async def add_style_example_route(account_id: int, payload: dict) -> dict:
    message = (payload.get("message") or "").strip()
    if not message:
        return {"error": "message_required"}
    channel = (payload.get("channel") or "").strip().lstrip("#")
    note = (payload.get("note") or "").strip()
    new_id = await _aiq.add_style_example(account_id, message, channel, note)
    await log_action("style_example_add", f"#{account_id}: {message[:50]}")
    return {"id": new_id}


@router.delete("/api/accounts/{account_id}/style-examples/{ex_id}")
async def delete_style_example_route(account_id: int, ex_id: int) -> dict:
    if not await _aiq.delete_style_example(account_id, ex_id):
        raise HTTPException(status_code=404, detail="style example not found")
    return {"ok": True}


@router.get("/api/accounts/{account_id}/banned-topics")
async def list_banned_topics_route(account_id: int) -> dict:
    """v8 Feature 7: запрещённые темы."""
    items = await _aiq.list_banned_topics(account_id)
    return {"items": items}


@router.post("/api/accounts/{account_id}/banned-topics")
async def add_banned_topic_route(account_id: int, payload: dict) -> dict:
    pattern = (payload.get("pattern") or "").strip()
    if not pattern:
        return {"error": "pattern_required"}
    fallback = (payload.get("fallback") or "").strip()
    mode = (payload.get("mode") or "silent").strip()
    if mode not in ("silent", "fallback", "redirect"):
        mode = "silent"
    new_id = await _aiq.add_banned_topic(account_id, pattern, fallback, mode)
    await log_action("banned_topic_add", f"#{account_id} {pattern}")
    return {"id": new_id}


@router.put("/api/accounts/{account_id}/banned-topics/{topic_id}")
async def update_banned_topic_route(account_id: int, topic_id: int, payload: dict) -> dict:
    fields: dict[str, Any] = {}
    for k in ("pattern", "fallback", "mode", "enabled"):
        if k in payload:
            fields[k] = payload[k]
    ok = await _aiq.update_banned_topic(account_id, topic_id, **fields)
    if not ok:
        raise HTTPException(status_code=404, detail="banned topic not found")
    return {"ok": ok}


@router.delete("/api/accounts/{account_id}/banned-topics/{topic_id}")
async def delete_banned_topic_route(account_id: int, topic_id: int) -> dict:
    if not await _aiq.delete_banned_topic(account_id, topic_id):
        raise HTTPException(status_code=404, detail="banned topic not found")
    return {"ok": True}


@router.get("/api/accounts/{account_id}/prompt-variants")
async def list_variants_route(account_id: int) -> dict:
    """v8 Feature 3: A/B варианты паттерна."""
    items = await _aiq.list_variants(account_id)
    return {"items": items}


@router.post("/api/accounts/{account_id}/prompt-variants")
async def add_variant_route(account_id: int, payload: dict) -> dict:
    label = (payload.get("label") or "A").strip()[:32] or "A"
    system_prompt = payload.get("system_prompt") or ""
    weight = max(0, min(100, int(payload.get("weight") or 50)))
    new_id = await _aiq.add_variant(account_id, label, system_prompt, weight)
    await log_action("variant_add", f"account={account_id} label={label}")
    return {"id": new_id}


@router.put("/api/accounts/{account_id}/prompt-variants/{variant_id}")
async def update_variant_route(account_id: int, variant_id: int, payload: dict) -> dict:
    fields: dict[str, Any] = {}
    for k in ("label", "system_prompt", "weight", "enabled"):
        if k in payload:
            fields[k] = payload[k]
    ok = await _aiq.update_variant(account_id, variant_id, **fields)
    if not ok:
        raise HTTPException(status_code=404, detail="prompt variant not found")
    return {"ok": ok}


@router.delete("/api/accounts/{account_id}/prompt-variants/{variant_id}")
async def delete_variant_route(account_id: int, variant_id: int) -> dict:
    if not await _aiq.delete_variant(account_id, variant_id):
        raise HTTPException(status_code=404, detail="prompt variant not found")
    return {"ok": True}


@router.post("/api/accounts/{account_id}/feedback")
async def submit_feedback_route(account_id: int, payload: dict) -> dict:
    """v8 Feature 2: like/dislike на ответ бота."""
    chat_log_id = int(payload.get("chat_log_id") or 0)
    if chat_log_id <= 0:
        return {"error": "chat_log_id_required"}
    feedback = int(payload.get("feedback") or 0)
    if feedback == 0:
        return {"error": "feedback_required"}
    note = (payload.get("note") or "").strip()
    variant_id = payload.get("prompt_variant_id")
    new_id = await _aiq.submit_feedback(
        account_id, chat_log_id, feedback,
        note=note,
        prompt_variant_id=int(variant_id) if variant_id else None,
    )
    if not new_id:
        raise HTTPException(status_code=404, detail="chat log or prompt variant not found")
    return {"id": new_id}


@router.get("/api/accounts/{account_id}/feedback/log/{chat_log_id}")
async def get_feedback_route(account_id: int, chat_log_id: int) -> dict:
    result = await _aiq.get_feedback_for_log(account_id, chat_log_id)
    if result is None:
        raise HTTPException(status_code=404, detail="chat log not found")
    return result


@router.get("/api/accounts/{account_id}/feedback/summary")
async def feedback_summary_route(account_id: int, days: int = 30) -> dict:
    """v8 Feature 2: агрегаты feedback'a за период."""
    days = max(1, min(365, int(days)))
    return await _aiq.feedback_summary(account_id=account_id, days=days)


@router.post("/api/ai/classify")
async def classify_route(payload: dict) -> dict:
    """v8 Feature 5: дебаг-эндпоинт pre-classifier'а.
    
    Принимает {message, account_id, channel, bot_nickname?, min_confidence?}
    Возвращает {should_reply, confidence, reason}.
    """
    message = (payload.get("message") or "").strip()
    if not message:
        return {"error": "message_required"}
    account_id = int(payload.get("account_id") or 0)
    channel = (payload.get("channel") or "").strip().lstrip("#")
    bot_nickname = (payload.get("bot_nickname") or "").strip()
    min_conf = float(payload.get("min_confidence") or 0.4)
    decision = await _aiq.classify_message_db(
        account_id, channel, message,
        bot_nickname=bot_nickname,
        min_confidence=min_conf,
    )
    return {
        "should_reply": decision.should_reply,
        "confidence": decision.confidence,
        "reason": decision.reason,
    }


@router.post("/api/ai/check-banned")
async def check_banned_route(payload: dict) -> dict:
    """v8 Feature 7: проверка текста против banned_topics (дебаг)."""
    text = (payload.get("text") or "").strip()
    account_id = int(payload.get("account_id") or 0)
    if not text:
        return {"hit": None}
    hit = await _aiq.check_banned_topics_db(account_id, text)
    if not hit:
        return {"hit": None}
    return {
        "hit": {
            "pattern_id": hit.pattern_id,
            "pattern": hit.pattern,
            "fallback": hit.fallback,
            "mode": hit.mode,
        }
    }
