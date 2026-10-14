"""BRAIN_PLAN §3/§6: роуты мозга — KB import/export, «отменить последнее обучение».

По правилам FILE_ZONES.md новые эндпоинты живут в СВОЁМ модуле и подключаются
в server.py одной строкой include_router.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.database import get_db
from app.security import auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(auth_dependency)])


async def _log_action(action: str, detail: str) -> None:
    try:
        from app.routes import log_action
        await log_action(action, detail)
    except Exception as exc:
        logger.debug("log_action fallback: %s", exc)


# ==================== §3 KB import/export ====================


@router.get("/api/accounts/{account_id}/kb/export")
async def kb_export(account_id: int) -> dict:
    """Экспорт всей KB аккаунта (включая disabled) в JSON."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT topic, content, tags, priority, enabled, updated_at "
            "FROM streamer_kb WHERE account_id = ? ORDER BY id ASC",
            (account_id,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    entries = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d.get("enabled", 1))
        entries.append(d)
    await _log_action("kb_export", f"account={account_id} count={len(entries)}")
    return {"ok": True, "entries": entries}


@router.post("/api/accounts/{account_id}/kb/import")
async def kb_import(account_id: int, data: dict) -> dict:
    """Bulk-импорт KB.

    body: {"entries": [{topic, content, tags?, priority?, enabled?}], "mode": "merge"|"replace"}
    merge (дефолт): пропускает записи с уже существующим topic.
    replace: сначала удаляет всю KB аккаунта.
    """
    entries = data.get("entries")
    if not isinstance(entries, list):
        return {"ok": False, "error": "entries must be a list"}
    mode = (data.get("mode") or "merge").strip().lower()
    if mode not in ("merge", "replace"):
        mode = "merge"

    db = await get_db()
    added = skipped = 0
    try:
        if mode == "replace":
            await db.execute("DELETE FROM streamer_kb WHERE account_id = ?", (account_id,))
        existing: set[str] = set()
        if mode == "merge":
            cursor = await db.execute(
                "SELECT topic FROM streamer_kb WHERE account_id = ?", (account_id,)
            )
            existing = {
                (r["topic"] or "").strip().lower() for r in await cursor.fetchall()
            }
        for e in entries:
            if not isinstance(e, dict):
                skipped += 1
                continue
            topic = str(e.get("topic") or "").strip()
            content = str(e.get("content") or "").strip()
            if not topic or not content:
                skipped += 1
                continue
            if topic.lower() in existing:
                skipped += 1
                continue
            try:
                priority = max(0, min(10, int(e.get("priority", 5) or 5)))
            except (TypeError, ValueError):
                priority = 5
            enabled = 1 if e.get("enabled", 1) else 0
            await db.execute(
                "INSERT INTO streamer_kb (account_id, topic, content, tags, priority, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, topic[:200], content[:2000],
                 str(e.get("tags") or "").strip()[:200], priority, enabled),
            )
            existing.add(topic.lower())
            added += 1
        await db.commit()
    finally:
        await db.close()
    await _log_action(
        "kb_import", f"account={account_id} mode={mode} added={added} skipped={skipped}"
    )
    return {"ok": True, "added": added, "skipped": skipped, "mode": mode}


# ==================== §6 rollback: отменить последнее обучение ====================


@router.post("/api/accounts/{account_id}/learning/revert_last")
async def learning_revert_last(account_id: int, data: dict | None = None) -> dict:
    """Откатывает ПОСЛЕДНЕЕ применённое предложение (kind можно сузить).

    Инверсия действия из routes.learning_apply:
      style_example → удаляет добавленный пример
      kb_topic      → удаляет добавленную запись KB
      banned_topic  → удаляет добавленный banned topic
      persona_delta → только пометка reverted (прямого эффекта не было)
    """
    kind_filter = (data or {}).get("kind")
    db = await get_db()
    try:
        if kind_filter:
            cursor = await db.execute(
                """SELECT id, kind, payload_json, channel FROM learning_suggestions
                   WHERE account_id = ? AND status = 'applied' AND kind = ?
                   ORDER BY applied_at DESC, id DESC LIMIT 1""",
                (account_id, str(kind_filter)),
            )
        else:
            cursor = await db.execute(
                """SELECT id, kind, payload_json, channel FROM learning_suggestions
                   WHERE account_id = ? AND status = 'applied'
                   ORDER BY applied_at DESC, id DESC LIMIT 1""",
                (account_id,),
            )
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        return {"ok": False, "error": "nothing_applied"}

    import json as _json

    s = dict(row)
    try:
        payload = _json.loads(s.get("payload_json") or "{}")
    except (ValueError, TypeError):
        payload = {}
    kind = s.get("kind")
    channel = (s.get("channel") or "").strip().lower()
    undone = "noop"

    from app import learning as learning_mod

    try:
        if kind == "style_example":
            from app.ai_quality_db import delete_style_example, list_style_examples

            message = str(payload.get("message") or "").strip()
            examples = await list_style_examples(account_id, channel=channel, limit=500)
            target = next(
                (e for e in examples if (e.get("message") or "").strip() == message), None
            )
            if target and await delete_style_example(account_id, int(target["id"])):
                undone = "style_example_deleted"
        elif kind == "kb_topic":
            from app.ai_quality_db import delete_kb, list_kb

            topic = str(payload.get("topic") or "").strip().lower()
            kbs = await list_kb(account_id)
            target = next(
                (k for k in kbs if (k.get("topic") or "").strip().lower() == topic), None
            )
            if target and await delete_kb(account_id, int(target["id"])):
                undone = "kb_deleted"
        elif kind == "banned_topic":
            from app.ai_quality_db import delete_banned_topic, list_banned_topics

            pattern = str(payload.get("pattern") or "").strip().lower()
            topics = await list_banned_topics(account_id)
            target = next(
                (t for t in topics if (t.get("pattern") or "").strip().lower() == pattern),
                None,
            )
            if target and await delete_banned_topic(account_id, int(target["id"])):
                undone = "banned_topic_deleted"
        elif kind == "persona_delta":
            undone = "persona_delta_noop"
    except Exception as exc:
        return {"ok": False, "error": f"revert_failed: {exc}"}

    await learning_mod.mark_reverted(account_id, int(s["id"]))
    await _log_action(
        "learning_revert_last",
        f"account={account_id} id={s['id']} kind={kind} undone={undone}",
    )
    return {"ok": True, "reverted_id": int(s["id"]), "kind": kind, "undone": undone}


# ==================== §4: настройки summarizer (язык = язык панели) ====================


@router.get("/api/accounts/{account_id}/summarizer/settings")
async def summarizer_settings_get(account_id: int, channel: str = "") -> dict:
    """§2.3: настройки live-сводок. Без channel — уровень бота; с channel —
    эффективные (override канала, иначе наследуется от бота)."""
    from app.server import chat_analyzer

    s = chat_analyzer.get_settings(account_id)
    resp: dict[str, Any] = {
        "ok": True,
        "live_enabled": bool(s.get("summarizer_live_enabled")),
        "live_lang": s.get("summarizer_live_lang") or "ru",
        "scope": "bot",
        "channel": "",
    }
    channel = (channel or "").strip().lower().lstrip("#")
    if not channel:
        return resp
    resp["channel"] = channel
    resp["inherited_enabled"] = bool(s.get("summarizer_live_enabled"))
    ov = await chat_analyzer._channel_overrides_cached(account_id, channel)
    if "summarizer_live_enabled" in ov or "summarizer_live_lang" in ov:
        resp["scope"] = "channel"
        if "summarizer_live_enabled" in ov:
            resp["live_enabled"] = bool(ov["summarizer_live_enabled"])
        if "summarizer_live_lang" in ov:
            resp["live_lang"] = ov["summarizer_live_lang"] or "ru"
    return resp


async def _merge_channel_overrides(account_id: int, channel: str, updates: dict) -> None:
    """§2.3: дописать summarizer-ключи в overrides_json канала (без затирания
    остальных override-полей) и сбросить кэш рантайма."""
    import json as _json

    from app.database import get_db
    from app.server import chat_analyzer

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT overrides_json FROM channel_overrides WHERE account_id = ? AND channel = ?",
            (account_id, channel),
        )
        row = await cur.fetchone()
        existing = {}
        if row:
            try:
                existing = _json.loads(row["overrides_json"] or "{}")
            except Exception:
                existing = {}
        existing.update(updates)
        await db.execute(
            "INSERT INTO channel_overrides (account_id, channel, overrides_json, enabled, updated_at) "
            "VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP) "
            "ON CONFLICT(account_id, channel) DO UPDATE SET "
            "overrides_json=excluded.overrides_json, enabled=1, updated_at=CURRENT_TIMESTAMP",
            (account_id, channel, _json.dumps(existing, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    chat_analyzer.invalidate_channel_overrides(account_id, channel)


@router.post("/api/accounts/{account_id}/summarizer/settings")
async def summarizer_settings_set(account_id: int, data: dict) -> dict:
    from app.server import chat_analyzer

    channel = (data.get("channel") or "").strip().lower().lstrip("#")
    updates: dict[str, Any] = {}
    if "live_enabled" in data:
        updates["summarizer_live_enabled"] = bool(data.get("live_enabled"))
    if "live_lang" in data:
        lang = str(data.get("live_lang") or "ru").strip().lower()
        # язык панели: ua/uk → ru (отчёты поддерживают ru/en)
        if lang in ("ua", "uk"):
            lang = "ru"
        if lang not in ("ru", "en"):
            lang = "ru"
        updates["summarizer_live_lang"] = lang
    if not updates:
        return {"ok": False, "error": "nothing_to_update"}
    if channel:
        # §2.3: per-channel override (наследование от настроек бота остаётся)
        await _merge_channel_overrides(account_id, channel, updates)
        s = chat_analyzer.get_settings(account_id)
        await _log_action(
            "summarizer_settings",
            f"account={account_id} channel=#{channel} "
            f"live_enabled={updates.get('summarizer_live_enabled')} "
            f"lang={updates.get('summarizer_live_lang')}",
        )
        return {
            "ok": True,
            "scope": "channel",
            "channel": channel,
            "live_enabled": updates.get("summarizer_live_enabled", bool(s.get("summarizer_live_enabled"))),
            "live_lang": updates.get("summarizer_live_lang") or s.get("summarizer_live_lang") or "ru",
        }
    s = chat_analyzer.update_settings(account_id, updates)
    await _log_action(
        "summarizer_settings",
        f"account={account_id} "
        f"live_enabled={s.get('summarizer_live_enabled')} lang={s.get('summarizer_live_lang')}",
    )
    return {
        "ok": True,
        "scope": "bot",
        "live_enabled": bool(s.get("summarizer_live_enabled")),
        "live_lang": s.get("summarizer_live_lang") or "ru",
    }


# ==================== §7 уровни привязанности (API-хелпер) ====================


@router.get("/api/accounts/{account_id}/affinity_level")
async def affinity_level_route(account_id: int, channel: str = "", username: str = "") -> dict:
    """Возвращает привязанность + уровень (незнакомец…близкий)."""
    from app.affinity_rules import affinity_summary

    if not username.strip():
        return {"ok": False, "error": "username required"}
    info = await affinity_summary(account_id, channel, username)
    if not info:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, **info}
