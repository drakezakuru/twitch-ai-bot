"""sandbox_routes.py — песочница для тестирования ответов бота без отправки в реальный Twitch.

Позволяет симулировать сообщение зрителя в чате с выбранным каналом, проверяет:
- модерацию входящего сообщения (бан-слова, регулярки, базовые правила);
- сборку промпта (персона, характер, разрешённые темы канала);
- вызов LLM (время генерации, провайдер, модель);
- фильтры ответа бота;
- возвращает детальный результат в UI песочницы.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from app.database import get_db
from app.security import auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(auth_dependency)])


@router.post("/api/accounts/{account_id}/sandbox-reply")
async def sandbox_reply(account_id: int, request: Request) -> dict:
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    text = str(body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "Введите сообщение для проверки"}

    author = str(body.get("author") or "ТестовыйЗритель").strip() or "ТестовыйЗритель"
    channel = str(body.get("channel") or "").strip().lower().lstrip("#")

    from app import server
    ai_service = server.ai_service
    chat_analyzer = server.chat_analyzer
    from app.moderation import check_message

    db = await get_db()
    try:
        cur = await db.execute("SELECT id, nickname FROM accounts WHERE id = ?", (account_id,))
        acc = await cur.fetchone()
        if not acc:
            return {"ok": False, "error": "Бот не найден"}

        # Если канал не передан, берём первый активный канал бота
        if not channel:
            ch_cur = await db.execute(
                "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1 LIMIT 1",
                (account_id,),
            )
            ch_row = await ch_cur.fetchone()
            channel = str(ch_row["channel_name"] if ch_row else "testchannel").lower().lstrip("#")
    finally:
        await db.close()

    # 1. Проверяем модерацию входящего сообщения
    from app.moderation import load_custom_rules, _normalize, _find_matches, Verdict
    verdicts = await check_message(account_id, channel, author, text)
    if not verdicts:
        # В песочнице тестируем совпадение с правилами даже если режим выключен (mode='off')
        custom_rules = await load_custom_rules(account_id, channel)
        text_norm = _normalize(text)
        for r in custom_rules:
            rx = r.get("regex")
            if rx and _find_matches(rx, text_norm):
                verdicts.append(Verdict(
                    category=r.get("category") or "custom",
                    action=r.get("action") or "block",
                    severity=int(r.get("severity") or 3),
                    rule_name=r.get("name") or r.get("pattern") or "",
                    match=r.get("pattern") or "",
                ))
                break

    moderation_info = {
        "flagged": bool(verdicts),
        "action": verdicts[0].action if verdicts else None,
        "category": verdicts[0].category if verdicts else None,
        "match": verdicts[0].match if verdicts else None,
        "rule_name": verdicts[0].rule_name if verdicts else None,
    }

    # 2. Настройки бота и канала
    settings = chat_analyzer.get_settings(account_id)
    try:
        settings = await chat_analyzer._merged_settings(account_id, channel, settings)
    except Exception:
        pass

    # 3. Разрешённые темы и запретные темы для канала
    allowed_block = ""
    prompt_base_block = ""
    try:
        allowed_block = await chat_analyzer._load_allowed_topics_block(channel)
        prompt_base_block = await chat_analyzer._load_prompt_base_block(channel)
    except Exception:
        pass

    # 4. Собираем системный промпт
    base_prompt = settings.get("system_prompt") or "Ты — дружелюбный чат-бот на стриме."
    persona_block = ""
    try:
        from app.bot_persona import BotPersona
        db = await get_db()
        try:
            cur = await db.execute("SELECT persona_json FROM accounts WHERE id = ?", (account_id,))
            p_row = await cur.fetchone()
            if p_row and p_row["persona_json"]:
                persona_block = BotPersona.from_json(p_row["persona_json"]).to_prompt_block()
        finally:
            await db.close()
    except Exception:
        pass

    bot_nick = str(acc["nickname"] if acc else "Бот")

    # 4.5. Диалоговый контекст из буфера недавних сообщений
    history_lines = []
    if hasattr(chat_analyzer, "_chat_buffer") and hasattr(chat_analyzer, "_buffer_key"):
        buf_key = chat_analyzer._buffer_key(account_id, channel)
        recent_buf = chat_analyzer._chat_buffer.get(buf_key, [])[-8:]
        for m in recent_buf:
            m_author = m.get("author") or "Зритель"
            m_text = m.get("text") or ""
            if m_text:
                history_lines.append(f"{m_author}: {m_text}")

    system_parts = []
    if prompt_base_block:
        system_parts.append(prompt_base_block)
    system_parts.append(base_prompt)
    if persona_block:
        system_parts.append(persona_block)
    if allowed_block:
        system_parts.append(allowed_block)
    if history_lines:
        system_parts.append("Недавний контекст сообщений в чате:\n" + "\n".join(history_lines))

    system_prompt = "\n\n".join(filter(None, system_parts))
    user_prompt = f"{author}: {text}"

    is_variation = bool(body.get("variation"))

    # 5. Вызов модели с замером времени
    t0 = time.perf_counter()
    reply = ""
    error_msg = ""
    provider_name = ai_service.provider
    model_name = ""
    try:
        override = ai_service.get_account_override(account_id)
        if override and override.provider:
            provider_name = override.provider
            model_name = override.chat_model or ""

        base_temp = float(settings.get("temperature", 0.5))
        temp = min(1.0, max(0.2, base_temp + 0.25)) if is_variation else base_temp

        reply = await ai_service.generate_text(
            prompt=user_prompt,
            system=system_prompt,
            account_id=account_id,
            channel=channel,
            temperature=temp,
        )
    except Exception as exc:
        error_msg = str(exc)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if error_msg:
        return {
            "ok": False,
            "error": error_msg,
            "latency_ms": latency_ms,
            "provider": provider_name,
            "model": model_name,
            "moderation": moderation_info,
        }

    # 6. Пост-фильтрация
    reply_cleaned = (reply or "").strip().strip('"').strip("'")

    # Сохраняем реплики в буфер недавней памяти для связности последующих ответов в песочнице
    if hasattr(chat_analyzer, "_add_to_buffer"):
        chat_analyzer._add_to_buffer(account_id, channel, author, text)
        chat_analyzer._add_to_buffer(account_id, channel, bot_nick, reply_cleaned)

    context_count = 0
    if hasattr(chat_analyzer, "get_chat_buffer_status"):
        st = chat_analyzer.get_chat_buffer_status(account_id, channel)
        context_count = st.get("count", 0)

    return {
        "ok": True,
        "reply": reply_cleaned,
        "author": author,
        "channel": channel,
        "latency_ms": latency_ms,
        "provider": provider_name,
        "model": model_name,
        "moderation": moderation_info,
        "allowed_topics_applied": bool(allowed_block),
        "system_prompt_preview": system_prompt[:300] + ("..." if len(system_prompt) > 300 else ""),
        "context_count": context_count,
        "is_variation": is_variation,
    }


@router.post("/api/accounts/{account_id}/clear-context")
async def clear_bot_context(account_id: int, request: Request) -> dict:
    """Очищает кратковременную память и контекст диалога бота (буфер чата)."""
    from app.server import chat_analyzer
    from app.routes import log_action

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    channel = str(body.get("channel") or "").strip().lower().lstrip("#")
    cleared_messages = 0
    if hasattr(chat_analyzer, "clear_chat_buffer"):
        cleared_messages = chat_analyzer.clear_chat_buffer(account_id, channel)

    await log_action(
        "bot_context_cleared",
        f"бот #{account_id}: очищено сообщений в буфере: {cleared_messages}",
    )
    return {
        "ok": True,
        "account_id": account_id,
        "cleared_messages": cleared_messages,
    }


@router.post("/api/accounts/{account_id}/sandbox-save-style")
async def sandbox_save_style(account_id: int, request: Request) -> dict:
    """Сохраняет удачный ответ из песочницы в few-shot примеры стиля бота."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    reply = str(body.get("reply") or "").strip()
    if not reply:
        return {"ok": False, "error": "Пустой ответ для сохранения"}

    trigger_msg = str(body.get("trigger_msg") or "").strip()
    channel = str(body.get("channel") or "").strip().lower().lstrip("#")

    from app.ai_quality_db import add_style_example
    from app.routes import log_action

    note = f"Песочница: {trigger_msg[:60]}" if trigger_msg else "Песочница"
    new_id = await add_style_example(account_id, reply, channel=channel, note=note)

    db = await get_db()
    try:
        await db.execute(
            "UPDATE style_examples SET source = 'sandbox', trigger_msg = ? WHERE id = ?",
            (trigger_msg, new_id),
        )
        await db.commit()
    except Exception:
        pass
    finally:
        await db.close()

    await log_action("sandbox_style_saved", f"бот #{account_id}: пример #{new_id}")
    return {"ok": True, "id": new_id}


@router.get("/api/accounts/{account_id}/context-status")
async def get_bot_context_status(account_id: int, channel: str = "") -> dict:
    """Возвращает информацию о текущей заполненности буфера сообщений (памяти)."""
    from app.server import chat_analyzer

    channel = (channel or "").strip().lower().lstrip("#")
    status = {"count": 0, "max_size": 50}
    if hasattr(chat_analyzer, "get_chat_buffer_status"):
        status = chat_analyzer.get_chat_buffer_status(account_id, channel or None)

    return {
        "ok": True,
        "account_id": account_id,
        "channel": channel,
        **status,
    }
