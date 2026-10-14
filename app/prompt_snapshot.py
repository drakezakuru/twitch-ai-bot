"""P5 PLAN.md: снимок ВСЕХ промптов бота в data/bots/<ник>/prompts/.

Источники — те же функции, что собирают system prompt (см.
docs/ARCHITECTURE.md и app/brain_preview.py):

    prompts/system.txt           — базовая инструкция (settings)
    prompts/personality.txt      — persona_json (как есть)
    prompts/chatter_style.txt    — пресет/копирка/самообучение болтуна
    prompts/streamer_profile.txt — профиль стримера (resolved)
    prompts/lore.txt             — approved lore (top-10)
    prompts/shift.txt            — Personality Shift hint (если активен)
    prompts/SUMMARY.txt          — человекочитаемая сводка + статический промпт

Файлы перезаписываются при каждом вызове refresh — это СНИМОК (runtime читает
БД; файлы — для владельца, чтобы видеть «что реально влияет на бота»).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def refresh_prompt_snapshot(account_id: int, nickname: str, channel: str = "") -> dict:
    """Собрать и записать снапшот. Возвращает {ok, files:[имена], bot_dir}."""
    from app.bot_dirs import get_bot_dir, init_bot_dir
    from app.brain_preview import persona_block_from_summary  # переиспользуем сборку

    bot_dir = init_bot_dir(account_id, nickname)
    prompts_dir = bot_dir / "prompts"

    # данные — из brain_preview (те же функции-источники, ноль дублей)
    from app.brain_preview import brain_preview
    data = (await brain_preview(account_id, channel))
    if not data.get("ok"):
        return {"ok": False, "error": "preview_failed"}

    persona_raw = ""
    try:
        from app.database import get_db
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT persona_json FROM accounts WHERE id = ?", (account_id,))
            row = await cur.fetchone()
            persona_raw = (dict(row).get("persona_json") if row else "") or ""
        finally:
            await db.close()
    except Exception as exc:
        logger.debug("snapshot persona: %s", exc)

    written: list[str] = []

    def _write(name: str, content: str) -> None:
        p: Path = prompts_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content or "", encoding="utf-8")
        written.append(name)

    _write("system.txt", data.get("base_system") or "")
    _write("personality.txt", persona_raw)

    if data.get("chatter_style_chars"):
        # chatter_style — собран в brain_preview, но текст там не отдаётся;
        # перечитаем тем же источником:
        try:
            from app.database import get_db
            from app.bot_roles import load_role_config, chatter_style_block
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT bot_role, role_config_json FROM accounts WHERE id = ?",
                    (account_id,))
                row = dict(await cur.fetchone())
            finally:
                await db.close()
            cfg = load_role_config(row.get("role_config_json"), row.get("bot_role") or "chatter")
            _write("chatter_style.txt", chatter_style_block(cfg))
        except Exception as exc:
            logger.debug("snapshot chatter_style: %s", exc)

    sp = data.get("streamer_profile") or {}
    if sp:
        _write("streamer_profile.txt", json.dumps(sp, ensure_ascii=False, indent=2))

    if data.get("lore_count"):
        try:
            from app import streamer_lore
            rows = await streamer_lore.list_approved(account_id, channel, limit=10)
            _write("lore.txt", streamer_lore.format_lore_for_prompt(rows))
        except Exception as exc:
            logger.debug("snapshot lore: %s", exc)

    if data.get("shift_chars"):
        try:
            from app.personality_shift import shift_manager
            _write("shift.txt", shift_manager.get_hint(account_id, channel))
        except Exception as exc:
            logger.debug("snapshot shift: %s", exc)

    counts = data.get("counts") or {}
    summary_lines = [
        f"Бот: #{account_id} ({nickname}) · роль: {data.get('role')}",
        f"Канал: {channel or '(все)'}",
        "",
        "== Из чего складывается system prompt ==",
        "1. База: analyzer settings (prompts/system.txt)",
        "2. Персона: accounts.persona_json (prompts/personality.txt)",
    ]
    if data.get("streamer_profile"):
        summary_lines.append("3. Профиль стримера (prompts/streamer_profile.txt)")
    if data.get("lore_count"):
        summary_lines.append(f"3. Lore approved ({data['lore_count']} шт, prompts/lore.txt)")
    if data.get("shift_chars"):
        summary_lines.append("+ Personality Shift (prompts/shift.txt)")
    if data.get("chatter_style_chars"):
        summary_lines.append("+ Стиль болтуна (prompts/chatter_style.txt)")
    summary_lines += [
        "",
        f"Память: юзеров в памяти — {counts.get('users_with_memory', '—')}",
        f"Style examples: {counts.get('style_examples', '—')} (few-shot, top-K по теме)",
        f"KB записей: {counts.get('kb_entries', '—')}",
        "",
        "== Динамические блоки (подмешиваются на каждое сообщение) ==",
        "факты юзера (user_memory), история юзера, контекст беседы (chat_log),",
        "KB по запросу, few-shot по теме, mimicry, multi-bot чат, mood.",
        "",
        "== Статическая часть system prompt (как увидит AI) ==",
        data.get("static_prompt") or "(пусто)",
    ]
    _write("SUMMARY.txt", "\n".join(summary_lines))

    logger.info("prompt snapshot: %s (%d файлов)", bot_dir, len(written))
    return {"ok": True, "files": written, "bot_dir": str(bot_dir)}
