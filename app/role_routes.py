"""PLAN_FEEDBACK_3008 §6: роли ботов — API смены роли и role-config.

По правилам FILE_ZONES.md эндпоинты живут в СВОЁМ модуле и подключаются
в server.py одной строкой include_router.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.security import auth_dependency
from app.bot_roles import (
    DEFAULT_ROLE,
    VALID_ROLES,
    load_role_config,
    validate_role_config,
)
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(auth_dependency)])


async def _log_action(action: str, detail: str) -> None:
    try:
        from app.routes import log_action
        await log_action(action, detail)
    except Exception as exc:
        logger.debug("log_action failed: %s", exc)


async def _read_account(account_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, bot_role, role_config_json FROM accounts WHERE id = ?",
            (account_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def _write_account(account_id: int, **cols: Any) -> bool:
    sets = ", ".join(f"{k} = ?" for k in cols)
    db = await get_db()
    try:
        cur = await db.execute(
            f"UPDATE accounts SET {sets} WHERE id = ?", (*cols.values(), account_id)
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


@router.get("/api/accounts/{account_id}/role-config")
async def get_role_config(account_id: int) -> dict:
    """Полная карта: текущая роль + configs по каждой роли (§6.7 — без потери)."""
    acc = await _read_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "params": {}})
    role = (acc.get("bot_role") or DEFAULT_ROLE).strip()
    if role not in VALID_ROLES:
        role = DEFAULT_ROLE
    configs = {
        r: load_role_config(acc.get("role_config_json"), r) for r in VALID_ROLES
    }
    return {"ok": True, "bot_role": role, "configs": configs}


@router.put("/api/accounts/{account_id}/role-config")
async def put_role_config(account_id: int, data: dict) -> dict:
    """Atomically select a role and save its validated config."""
    role = str(data.get("role") or "").strip()
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail={"code": "unknown_role", "params": {"role": role}},
        )
    try:
        clean = validate_role_config(role, data.get("config"))
    except ValueError as exc:
        code = "role_config_too_large" if str(exc) == "config too large" else "invalid_role_config"
        raise HTTPException(status_code=400, detail={"code": code, "params": {}}) from exc
    acc = await _read_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "params": {}})
    try:
        all_cfg = json.loads(acc.get("role_config_json") or "{}")
    except json.JSONDecodeError:
        all_cfg = {}
    if not isinstance(all_cfg, dict):
        all_cfg = {}
    all_cfg[role] = clean  # заменяем только скоуп этой роли
    raw = json.dumps(all_cfg, ensure_ascii=False)
    if len(raw) > 128 * 1024:
        raise HTTPException(
            status_code=400, detail={"code": "role_config_too_large", "params": {}},
        )
    previous_role = (acc.get("bot_role") or DEFAULT_ROLE).strip()
    cols: dict[str, Any] = {"bot_role": role, "role_config_json": raw}
    # BUGFIX: уходя с роли lurker, снимаем observation_only — иначе бот с
    # «Только наблюдает» продолжает молчать в новой роли (выглядело как
    # «смену роли не применилось»).
    if previous_role == "lurker" and role != "lurker":
        cols["observation_only"] = 0
    ok = await _write_account(account_id, **cols)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "not_found", "params": {}})
    # §R1: конфиг роли изменился — сбросить кэш гейта
    try:
        from app.server import chat_analyzer
        chat_analyzer.invalidate_role_cache(account_id)
        if "observation_only" in cols:
            chat_analyzer.update_settings(account_id, {"observation_only": False})
            await chat_analyzer.persist_settings(account_id)
    except Exception:
        pass
    if role != previous_role:
        if previous_role == "lurker" and role != "lurker":
            from app.director import revoke_worker
            await revoke_worker(account_id)
        await _log_action("role_change", f"account={account_id} role={role}")
    return {"ok": True, "bot_role": role, "config": clean, "observation_only_cleared": "observation_only" in cols}


# Q39: массовое применение роли — только сама роль, без изменения role_config_json
# (конфиг остаётся как был сохранён под эту роль ранее для каждого бота).
async def bulk_set_role(account_id: int, role: str) -> dict[str, Any]:
    if role not in VALID_ROLES:
        return {"ok": False, "reason": "unknown_role"}
    acc = await _read_account(account_id)
    if not acc:
        return {"ok": False, "reason": "not_found"}
    previous_role = (acc.get("bot_role") or DEFAULT_ROLE).strip()
    cols: dict[str, Any] = {"bot_role": role}
    if previous_role == "lurker" and role != "lurker":
        cols["observation_only"] = 0
    await _write_account(account_id, **cols)
    try:
        from app.server import chat_analyzer
        chat_analyzer.invalidate_role_cache(account_id)
        if "observation_only" in cols:
            chat_analyzer.update_settings(account_id, {"observation_only": False})
            await chat_analyzer.persist_settings(account_id)
    except Exception:
        pass
    if role != previous_role and previous_role == "lurker":
        from app.director import revoke_worker
        await revoke_worker(account_id)
    return {"ok": True, "bot_role": role}


# ── §R4: копирка «как у живого» + самообучение ──

@router.get("/api/accounts/{account_id}/mimic/candidates")
async def mimic_candidates(account_id: int, limit: int = 20) -> dict:
    """Активные юзеры чата (кто активнее — первым) для селекта копирки."""
    from app.database import get_db
    limit = max(1, min(50, limit))
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT author AS username, COUNT(*) AS cnt FROM chat_log "
            "WHERE account_id = ? AND is_bot = 0 AND author != '' "
            "GROUP BY author ORDER BY cnt DESC LIMIT ?",
            (account_id, limit),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    return {"ok": True, "items": rows}


@router.post("/api/accounts/{account_id}/mimic/copy")
async def mimic_copy(account_id: int, data: dict) -> dict:
    """Режим A «📋 Копия сообщений»: забрать историю юзера из chat_log,
    положить few-shot (последние 50, ≤200 симв.) + авто-выжимку стиля."""
    import re as _re
    from app.database import get_db
    from app.bot_roles import load_role_config

    user = str(data.get("user") or "").strip()
    limit = max(10, min(500, int(data.get("limit") or 500)))
    if not user:
        return {"ok": False, "error": "user required"}
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT message FROM chat_log WHERE account_id = ? AND author = ? "
            "AND is_bot = 0 ORDER BY id DESC LIMIT ?",
            (account_id, user, limit),
        )
        rows = [r["message"] for r in await cur.fetchall()]
    finally:
        await db.close()
    if not rows:
        return {"ok": False, "error": "no_messages"}
    msgs = [m.strip()[:200] for m in rows if m and m.strip()]
    # авто-выжимка (без редактора): длина, капс, эмодзи, частые слова
    joined = " ".join(msgs)
    avg_len = round(sum(len(m) for m in msgs) / max(1, len(msgs)))
    caps_ratio = round(100 * sum(1 for m in msgs if m.isupper()) / max(1, len(msgs)))
    emoji_cnt = len(_re.findall(r"[\U0001F300-\U0001FAFF]", joined))
    words = _re.findall(r"[а-яёa-z]{4,}", joined.lower())
    from collections import Counter
    top = ", ".join(w for w, _ in Counter(words).most_common(5)) or "—"
    summary = (f"средняя длина {avg_len} симв; капс в {caps_ratio}% сообщений; "
               f"эмодзи: {emoji_cnt}; частые слова: {top}")
    # сохранить в role_config.chatter
    acc = await _read_account(account_id)
    if not acc:
        return {"ok": False, "error": "not_found"}
    cfg = load_role_config(acc.get("role_config_json"), "chatter")
    cfg.update({
        "mimic_mode": "copy",
        "mimic_user": user,
        "mimic_copy_msgs": msgs[:50],
        "mimic_copy_summary": summary,
    })
    try:
        all_cfg = json.loads(acc.get("role_config_json") or "{}")
    except json.JSONDecodeError:
        all_cfg = {}
    if not isinstance(all_cfg, dict):
        all_cfg = {}
    all_cfg["chatter"] = validate_role_config("chatter", cfg)
    raw = json.dumps(all_cfg, ensure_ascii=False)
    await _write_account(account_id, role_config_json=raw)
    return {"ok": True, "fetched": len(rows), "saved": min(len(msgs), 50),
            "summary": summary}


@router.post("/api/accounts/{account_id}/mimic/profile-build")
async def mimic_profile_build(account_id: int, data: dict) -> dict:
    """Режим B «🎨 Стиль-профиль»: AI строит редактируемый профиль стиля.

    P8-C1: источник — ВЕСЬ наш chat_log по нику (до 400 сообщений, все каналы
    бота); если у бота мало/нет данных — best-effort докачка с logs.ivr.fi
    (публичный лог-сервис; не для всех каналов есть).
    """
    from app.database import get_db
    from app.ai_service import AIService

    user = str(data.get("user") or "").strip()
    sample = str(data.get("sample") or "").strip()
    sources = []
    if not sample and user:
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT message FROM chat_log WHERE account_id = ? AND author = ? "
                "AND is_bot = 0 ORDER BY id DESC LIMIT 400",
                (account_id, user),
            )
            rows = await cur.fetchall()
        finally:
            await db.close()
        if rows:
            sample = "\n".join((r["message"] or "")[:200] for r in rows)
            sources.append(f"chat_log:{len(rows)}")
        if len(sample) < 400:
            # best-effort: внешний лог-сервис (может быть пусто/404 — молча пропускаем)
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://logs.ivr.fi/lines",
                        params={"channel": user, "username": user, "limit": 200},
                    )
                if resp.status_code == 200:
                    texts = []
                    for line in resp.text.splitlines():
                        # формат: [<time>] #chan <user>: message
                        part = line.split(": ", 1)
                        if len(part) == 2 and part[1].strip():
                            texts.append(part[1].strip()[:200])
                    if texts:
                        sample = (sample + "\n" if sample else "") + "\n".join(texts[:200])
                        sources.append(f"ivr.fi:{len(texts)}")
            except Exception:
                pass
        if len(sample) < 400:
            # P8/C1-3-й источник: НАШ чат-логгер (data/chatlogger.sqlite3, вся
            # история юзера по всем каналам, что логгер сидел)
            try:
                from app.chat_logger_routes import DB_PATH as _cl_db
                if _cl_db.exists():
                    _conn = sqlite3.connect(_cl_db)
                    try:
                        rows = _conn.execute(
                            "SELECT message FROM messages WHERE username = ? "
                            "ORDER BY id DESC LIMIT 200", (user.lower(),)).fetchall()
                    finally:
                        _conn.close()
                    if rows:
                        texts = [r[0][:200] for r in rows]
                        sample = (sample + "\n" if sample else "") + "\n".join(texts)
                        sources.append(f"chatlogger:{len(texts)}")
            except Exception:
                pass
    sample = sample.strip()[:6000]
    if not sample:
        return {"ok": False, "error": "no_sample"}
    ai = AIService()
    prompt = (
        "Ниже — сообщения зрителя из Twitch-чата. Опиши ЕГО СТИЛЬ одной секцией "
        "текстом на русском (5-10 строк): лексика/сленг, эмодзи (какие и как часто), "
        "капс, пунктуация, средняя длина сообщений, типичные фразы (3-5 дословно). "
        "Без вступлений и обращений — только описание стиля.\n\nСообщения:\n" + sample
    )
    profile = await ai.generate_text(prompt=prompt, system="Ты анализатор стиля речи. Отвечай только описанием стиля.", account_id=account_id)
    if not profile:
        return {"ok": False, "error": "ai_empty"}
    return {"ok": True, "profile": profile.strip()[:2000], "sources": sources}


@router.post("/api/accounts/{account_id}/mimic/import-history")
async def mimic_import_history(account_id: int, data: dict) -> dict:
    """H (REWORK_PLAN 03.09): импорт истории чата ФАЙЛОМ (txt: `автор: текст`,
    json: [{author,text}]) → стил-профиль копирки (как profile-build, но
    источник — загруженная история, а не чат-логи)."""
    from app.ai_service import AIService

    acc = await _read_account(account_id)
    if not acc:
        return {"ok": False, "error": "not_found"}

    messages = data.get("messages") or []
    if isinstance(messages, str):
        messages = [
            {"author": ln.split(":", 1)[0].strip(), "text": ln.split(":", 1)[1].strip()}
            for ln in messages.splitlines() if ln.strip() and ": " in ln
        ]
    parsed = []
    for m in messages:
        if isinstance(m, dict):
            author = str(m.get("author") or "").strip()
            text = str(m.get("text") or "").strip()
        elif isinstance(m, str):
            if ": " not in m:
                continue
            author, text = (part.strip() for part in m.split(": ", 1))
        else:
            continue
        if author and text:
            parsed.append((author, text[:200]))
    if not parsed:
        return {"ok": False, "error": "no_messages"}

    user = str(data.get("user") or "").strip()
    if user:
        parsed = [(a, t) for a, t in parsed if a.lower() == user.lower()]
    if not parsed:
        return {"ok": False, "error": "user_not_found"}

    sample = "\n".join(f"{a}: {t}" for a, t in parsed[:600])[:8000]
    ai = AIService()
    prompt = (
        "Ниже — история сообщений зрителя из Twitch-чата (загружена файлом). "
        "Опиши ЕГО СТИЛЬ одной секцией текстом на русском (5-10 строк): лексика/сленг, "
        "эмодзи, капс, пунктуация, средняя длина, типичные фразы (3-5 дословно). "
        "Без вступлений — только описание стиля.\n\nИстория:\n" + sample
    )
    profile = await ai.generate_text(prompt=prompt, system="Ты анализатор стиля речи. Отвечай только описанием стиля.", account_id=account_id)
    if not profile:
        return {"ok": False, "error": "ai_empty"}
    return {"ok": True, "profile": profile.strip()[:2000], "messages_used": len(parsed[:600])}


@router.post("/api/accounts/{account_id}/mimic/learn-clear")
async def mimic_learn_clear(account_id: int) -> dict:
    """Очистить выученный пул (👍-ответы)."""
    acc = await _read_account(account_id)
    if not acc:
        return {"ok": False, "error": "not_found"}
    try:
        all_cfg = json.loads(acc.get("role_config_json") or "{}")
    except json.JSONDecodeError:
        all_cfg = {}
    if isinstance(all_cfg.get("chatter"), dict):
        all_cfg["chatter"]["learned_pool"] = []
        await _write_account(account_id, role_config_json=json.dumps(all_cfg, ensure_ascii=False))
    return {"ok": True}


@router.post("/api/accounts/{account_id}/role-sandbox")
async def role_sandbox(account_id: int, data: dict) -> dict:
    """§6.7 песочница: ЧТО сделает бот на тестовое сообщение, без реального чата."""
    role = str(data.get("role") or "").strip()
    message = str(data.get("message") or "").strip()
    if role not in VALID_ROLES:
        return {"ok": False, "error": f"unknown_role: {role}"}
    if not message:
        return {"ok": False, "error": "empty_message"}
    acc = await _read_account(account_id)
    if not acc:
        return {"ok": False, "error": "not_found"}
    cfg = load_role_config(acc.get("role_config_json"), role)

    if role == "moderator":
        from app import moderation
        verdicts = await moderation.check_message(account_id, "", "sandbox_user", message, role="viewer")
        if not verdicts:
            verdict = "✅ Чисто: словари/правила нарушений не нашли."
        else:
            v = verdicts[0]
            shown = v.masked_text or message
            if cfg.get("strictness") == "manual":
                verdict = f"📝 Ручной режим: только запись в лог для вас. [{v.category}] «{shown}»"
            elif cfg.get("strictness") == "soft":
                verdict = f"⚠️ Мягкая строгость: предупреждение в чат. [{v.category}] «{shown}»"
            elif cfg.get("strictness") == "strict":
                verdict = (f"⏱ Жёсткая строгость: сразу таймаут {cfg.get('ladder_t1_min', 1)} мин"
                           f"{'' if not cfg.get('confirm_mode') == 'confirm' else ' (ждёт вашего одобрения)'}"
                           f". [{v.category}] «{shown}»")
            else:
                verdict = (f"🪜 Лестница: 1-е нарушение → предупреждение"
                           f" (далее: №2 → таймаут {cfg.get('ladder_t1_min', 1)} мин,"
                           f" №3 → {cfg.get('ladder_t2_min', 10)} мин,"
                           f" №{cfg.get('ladder_ban', 4)} → бан). [{v.category}] «{shown}»")
            if cfg.get("announce_in_chat"):
                verdict += "\n💬 Анонс действия был бы отправлен в чат."
            else:
                verdict += "\n📺 Действие ушло бы всплывашкой в mod-feed (чат не тронут)."
        return {"ok": True, "verdict": verdict}

    if role == "lurker":
        verdict = ("👀 Промолчал бы и записал наблюдение."
                   if not cfg.get("mention_reply")
                   else "👀 Промолчал бы: это не прямое @упоминание.")
        return {"ok": True, "verdict": verdict}

    if role == "voice_companion":
        # W3: та же публичная chat_out-цепочка, что у обычного бота. После
        # успешной отправки существующий tts_reply_percent решает, озвучивать ли реплику.
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT tts_reply_percent FROM bot_attention_config WHERE account_id = ?",
                (account_id,),
            )
            row = await cur.fetchone()
            tts_percent = int(row["tts_reply_percent"]) if row and row["tts_reply_percent"] is not None else 100
        finally:
            await db.close()
        observed = "стрим и чат" if cfg.get("on_speech") else "чат"
        verdict = (
            f"🎙 Собеседник написал бы обычное сообщение в публичный Twitch-чат, "
            f"используя контекст: {observed}. После отправки реплика озвучивается "
            f"с вероятностью {max(0, min(100, tts_percent))}% (настройка tts_reply_percent)."
            f" Задержка {cfg.get('reply_delay_sec', 2)} сек, "
            f"лимит {cfg.get('max_per_10min', 6)}/10 мин."
        )
        return {"ok": True, "verdict": verdict}

    # chatter: текст ответа делает AI — песочница показывает гейты
    verdict = ("💬 Ответил бы обычным сообщением (лимиты/кулдауны общих настроек действуют)."
               if cfg.get("anti_assistant", True)
               else "💬 Ответил бы (анти-ассистент фильтр выключен вручную).")
    return {"ok": True, "verdict": verdict}
