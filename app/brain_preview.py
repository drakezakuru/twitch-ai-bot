"""P3 PLAN_PANEL_REWORK §1.2/§1.3: экран «Мозг бота X» + промпт-инспектор.

Read-only сводка «что влияет на бота» + сборка СТАТИЧЕСКОЙ части system
prompt теми же функциями-источниками, что и рантайм (chat_analyzer):
  base (settings→account A/B variants), persona_block, chatter_style (роль chatter),
  streamer_profile, streamer_lore, personality_shift.

Динамические (per-message) блоки — memory/KB/few-shot/conv — показываются
как счётчики (сколько фактов/примеров доступно), сам текст зависит от
конкретного сообщения и в инспекторе не изображается честно.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.security import auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brain-preview", tags=["brain-preview"],
                   dependencies=[Depends(auth_dependency)])


async def _base_system(account_id: int) -> str:
    """Base system prompt from analyzer settings, as in runtime."""
    system = ""
    try:
        from app.server import chat_analyzer
        system = (chat_analyzer.get_settings(account_id) or {}).get("system_prompt") or ""
    except Exception as exc:
        logger.debug("brain-preview base settings: %s", exc)
    return system or ""


def _persona_summary(raw: str) -> dict:
    try:
        p = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    levels = {k: p[k] for k in (
        "humor_level", "sarcasm_level", "darkness_level", "emotionality",
        "seriousness", "crudeness_level") if k in p}
    return {
        "name": p.get("name") or "",
        "occupation": p.get("occupation") or "",
        "speaking_style": p.get("speaking_style") or "",
        "levels": levels,
        "enabled_flags": {k: p[k] for k in p if k.endswith("_enabled") and p[k]},
    }


@router.get("/{account_id}")
async def brain_preview(account_id: int, channel: str = "") -> dict:
    from app.database import get_db
    from app.bot_roles import load_role_config, chatter_style_block

    out: dict[str, Any] = {"ok": True, "account_id": account_id}

    # base system
    out["base_system"] = await _base_system(account_id)

    # persona
    persona_raw = ""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT persona_json, bot_role, role_config_json, ai_provider_override, proxy "
            "FROM accounts WHERE id = ?", (account_id,))
        row = await cur.fetchone()
    finally:
        await db.close()
    row = dict(row) if row else {}
    persona_raw = row.get("persona_json") or ""
    out["persona"] = _persona_summary(persona_raw)

    # роль + chatter_style (тот же chatter_style_block, что и в рантайме)
    role = row.get("bot_role") or "chatter"
    role_cfg = load_role_config(row.get("role_config_json"), role)
    chatter_style = chatter_style_block(role_cfg) if role == "chatter" else ""
    out["chatter_style_chars"] = len(chatter_style)
    out["role"] = role

    # профиль стримера (channel → fallback global) — та же функция
    profile_block = ""
    try:
        from app.streamer_profile import get_streamer_profile_resolved
        prof = await get_streamer_profile_resolved(account_id, channel)
        if prof:
            out["streamer_profile"] = {
                "scope": prof.get("scope", ""),
                "bio": (prof.get("bio") or "")[:200],
                "style": prof.get("style") or "",
            }
            profile_block = "; ".join(
                f"{k}: {v}" for k, v in prof.items()
                if k not in ("scope",) and v) or ""
    except Exception as exc:
        logger.debug("brain-preview profile: %s", exc)
    out["streamer_profile_chars"] = len(profile_block)

    # lore (approved) — счётчик
    lore_count = 0
    try:
        from app import streamer_lore
        lore_rows = await streamer_lore.list_approved(account_id, channel, limit=10)
        lore_count = len(lore_rows)
    except Exception as exc:
        logger.debug("brain-preview lore: %s", exc)
    out["lore_count"] = lore_count

    # personality shift hint — та же функция
    shift_hint = ""
    try:
        from app.personality_shift import shift_manager
        shift_hint = shift_manager.get_hint(account_id, channel)
    except Exception as exc:
        logger.debug("brain-preview shift: %s", exc)
    out["shift_chars"] = len(shift_hint)

    # динамические счётчики (per-message, показываем как «сколько доступно»)
    counts: dict[str, Any] = {}
    try:
        from app.ai_quality_db import list_style_examples, list_kb
        counts["style_examples"] = len(await list_style_examples(account_id))
        counts["kb_entries"] = len(await list_kb(account_id))
    except Exception as exc:
        logger.debug("brain-preview counts: %s", exc)
    try:
        from app import user_memory
        import aiosqlite  # noqa: F401
        db2 = await get_db()
        try:
            cur = await db2.execute(
                "SELECT COUNT(DISTINCT username) c FROM user_memory WHERE account_id = ?",
                (account_id,))
            r = await cur.fetchone()
            counts["users_with_memory"] = (r["c"] if r else 0)
        finally:
            await db2.close()
    except Exception as exc:
        logger.debug("brain-preview memory count: %s", exc)
    # P8-C2: скоуп shared-фактов удалён (общая память убрана) — память только per-bot.
    out["counts"] = counts

    # итоговая СТАТИЧЕСКАЯ часть промпта (те же функции-источники, тот же порядок)
    # Q18 (DEC-OWNER-004): база запреток per-канал → пресет, идёт первой.
    prompt_base_block = ""
    try:
        from app.server import chat_analyzer as _ca
        prompt_base_block = await _ca._load_prompt_base_block(channel)
    except Exception as exc:
        logger.debug("brain-preview prompt base: %s", exc)
        prompt_base_block = ""
    allowed_topics_block = ""
    try:
        from app.server import chat_analyzer as _ca
        allowed_topics_block = await _ca._load_allowed_topics_block(channel)
    except Exception as exc:
        logger.debug("brain-preview allowed topics: %s", exc)
        allowed_topics_block = ""
    persona_block = persona_block_from_summary(out)
    out["persona_block_chars"] = len(persona_block)
    out["prompt_base_chars"] = len(prompt_base_block)
    out["allowed_topics_chars"] = len(allowed_topics_block)
    parts = [s for s in (prompt_base_block, out["base_system"], allowed_topics_block,
                         persona_block, profile_block, shift_hint, chatter_style) if s]
    out["static_prompt"] = "\n\n".join(parts)
    out["static_prompt_chars"] = len(out["static_prompt"])

    # провайдер/модель
    out["provider"] = {
        "ai_provider_override": row.get("ai_provider_override") or "",
        "proxy": bool(row.get("proxy")),
    }
    return out


def persona_block_from_summary(out: dict) -> str:
    """Краткое текстовое представление персоны (для инспектора)."""
    p = out.get("persona") or {}
    if not p:
        return ""
    lines = []
    if p.get("name"):
        lines.append(f"Имя: {p['name']}")
    if p.get("occupation"):
        lines.append(f"Род занятий: {p['occupation']}")
    if p.get("speaking_style"):
        lines.append(f"Стиль речи: {p['speaking_style']}")
    for k, v in (p.get("levels") or {}).items():
        lines.append(f"{k}: {v}")
    return "[Персона]\n" + "\n".join(lines) if lines else ""


@router.post("/{account_id}/snapshot")
async def snapshot_prompts(account_id: int, channel: str = "") -> dict:
    """P5: записать снапшот всех промптов в data/bots/<ник>/prompts/."""
    from app.database import get_db
    from app.prompt_snapshot import refresh_prompt_snapshot
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT nickname FROM accounts WHERE id = ?", (account_id,))
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return {"ok": False, "error": "bot_not_found"}
    return await refresh_prompt_snapshot(account_id, row["nickname"], channel)
