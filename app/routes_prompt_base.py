"""PROMPT-BASE (PB-1/PB-2): общая база запреток/правил для ВСЕХ ботов.

Декорирует ОБЩИЙ router из app.routes (auth уже на нём); импортируется
ВНИЗУ routes.py. Хранение: settings-kv ключ ``prompt_base`` (простой текст,
одна запретка на строку). Сборка system prompt задокументирована в
ChatAnalyzer._generate_and_send: база → персона/личный промпт → правила.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from app.routes import router, log_action  # noqa: E402

logger = logging.getLogger(__name__)

PROMPT_BASE_KEY = "prompt_base"
MAX_PROMPT_BASE_CHARS = 8000


@router.get("/api/prompt-base")
async def get_prompt_base() -> dict:
    """LEGACY (Q18): глобальная база перенесена в пресет запретных тем
    (/api/bans/preset). Роут оставлен для чтения legacy-ключа и старых клиентов."""
    from app.database import get_setting
    raw = await get_setting(PROMPT_BASE_KEY, "")
    return {"ok": True, "text": raw or "", "legacy": True}


@router.put("/api/prompt-base")
async def set_prompt_base(request: Request) -> dict:
    """LEGACY (Q18): пишется только legacy-ключ, рантаймом не читается.
    Новый путь — /api/bans/preset и /api/bans/channel."""
    from app.database import set_setting
    data = await request.json()
    text = str(data.get("text") or "")
    if len(text) > MAX_PROMPT_BASE_CHARS:
        return {"ok": False, "error": "too_long", "max_chars": MAX_PROMPT_BASE_CHARS}
    await set_setting(PROMPT_BASE_KEY, text)
    rules = sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))
    await log_action("prompt_base_save", f"legacy-база запреток сохранена ({rules} правил)")
    return {"ok": True, "rules": rules, "legacy": True}


# ===================== Q18 (DEC-OWNER-004): запретные темы per-канал + пресет =====================

@router.get("/api/bans/preset")
async def get_bans_preset() -> dict:
    from app.channel_bans import get_preset_text
    text = await get_preset_text()
    return {"ok": True, "text": text, "rules": sum(
        1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))}


@router.put("/api/bans/preset")
async def put_bans_preset(request: Request) -> dict:
    from app.channel_bans import MAX_BANS_CHARS, set_preset_text
    data = await request.json()
    text = str(data.get("text") or "")
    if len(text) > MAX_BANS_CHARS:
        return {"ok": False, "error": "too_long", "max_chars": MAX_BANS_CHARS}
    rules = await set_preset_text(text)
    await log_action("bans_preset_save", f"базовый пресет запретных тем сохранён ({rules} правил)")
    return {"ok": True, "rules": rules}


@router.get("/api/bans/channel")
async def get_bans_channel(channel: str = "") -> dict:
    from app.channel_bans import MAX_BANS_CHARS, normalize_channel, resolve_channel_bans
    ch = normalize_channel(channel)
    if not ch:
        raise HTTPException(status_code=400, detail="channel_required")
    text, source = await resolve_channel_bans(ch)
    return {"ok": True, "channel": ch, "text": text, "source": source,
            "max_chars": MAX_BANS_CHARS}


@router.put("/api/bans/channel")
async def put_bans_channel(request: Request) -> dict:
    from app.channel_bans import MAX_BANS_CHARS, set_channel_text
    data = await request.json()
    channel = str(data.get("channel") or "")
    text = str(data.get("text") or "")
    if len(text) > MAX_BANS_CHARS:
        return {"ok": False, "error": "too_long", "max_chars": MAX_BANS_CHARS}
    try:
        rules = await set_channel_text(channel, text)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    await log_action("bans_channel_save", f"запретные темы канала #{channel} сохранены ({rules} правил)")
    return {"ok": True, "rules": rules}


# ===================== Разрешённые темы и цели per-канал + пресет =====================

@router.get("/api/allowed-topics/preset")
async def get_allowed_topics_preset() -> dict:
    from app.channel_allowed import get_allowed_preset_text
    text = await get_allowed_preset_text()
    return {"ok": True, "text": text, "rules": sum(
        1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))}


@router.put("/api/allowed-topics/preset")
async def put_allowed_topics_preset(request: Request) -> dict:
    from app.channel_allowed import MAX_ALLOWED_CHARS, set_allowed_preset_text
    data = await request.json()
    text = str(data.get("text") or "")
    if len(text) > MAX_ALLOWED_CHARS:
        return {"ok": False, "error": "too_long", "max_chars": MAX_ALLOWED_CHARS}
    rules = await set_allowed_preset_text(text)
    await log_action("allowed_topics_preset_save", f"базовый пресет разрешённых тем сохранён ({rules} правил)")
    return {"ok": True, "rules": rules}


@router.get("/api/allowed-topics/channel")
async def get_allowed_topics_channel(channel: str = "") -> dict:
    from app.channel_allowed import MAX_ALLOWED_CHARS, normalize_channel, resolve_channel_allowed
    ch = normalize_channel(channel)
    if not ch:
        raise HTTPException(status_code=400, detail="channel_required")
    text, source = await resolve_channel_allowed(ch)
    return {"ok": True, "channel": ch, "text": text, "source": source,
            "max_chars": MAX_ALLOWED_CHARS}


@router.put("/api/allowed-topics/channel")
async def put_allowed_topics_channel(request: Request) -> dict:
    from app.channel_allowed import MAX_ALLOWED_CHARS, set_channel_allowed_text
    data = await request.json()
    channel = str(data.get("channel") or "")
    text = str(data.get("text") or "")
    if len(text) > MAX_ALLOWED_CHARS:
        return {"ok": False, "error": "too_long", "max_chars": MAX_ALLOWED_CHARS}
    try:
        rules = await set_channel_allowed_text(channel, text)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    await log_action("allowed_topics_channel_save", f"разрешённые темы канала #{channel} сохранены ({rules} правил)")
    return {"ok": True, "rules": rules}
