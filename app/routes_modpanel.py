"""modpanel — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any
from datetime import datetime, timezone
import json
from fastapi import Response
from app.routes import router, decrypt_token, get_db, log_action, logger  # noqa: E402


# ===================== v14 MODERATION_PLAN §4: ПАНЕЛЬ МОДЕРАЦИИ =====================

_MOD_MODES = ("off", "log_only", "replace", "full", "shadow")
_MOD_CATEGORIES = ("custom", "insult", "hate", "threat", "sexual", "spam", "links", "caps", "repeat")
_MOD_ACTIONS = ("replace", "block", "timeout", "log")


@router.get("/api/accounts/{account_id}/moderation/settings")
async def moderation_get_settings(account_id: int) -> dict:
    """Настройки модерации аккаунта + per-channel overrides + каналы для UI."""
    from app import moderation as _mod
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT moderation_mode, moderation_can_timeout, moderation_escalation_enabled, antispam_viewer_enabled, "
            "antispam_caps_pct, antispam_repeat_count, antispam_links, antispam_emote_pct, "
            "antispam_exempt_roles, eventsub_chat_messages FROM accounts WHERE id = ?",
            (account_id,),
        )
        acc = await cur.fetchone()
        if not acc:
            return {"ok": False, "error": "Аккаунт не найден"}
        keys = acc.keys()
        chans_cur = await db.execute(
            "SELECT DISTINCT channel_name FROM channels WHERE account_id = ? AND enabled = 1 ORDER BY channel_name",
            (account_id,),
        )
        channels = [r["channel_name"] for r in await chans_cur.fetchall()]
        ov_cur = await db.execute(
            "SELECT channel, overrides_json FROM channel_overrides WHERE account_id = ? AND enabled = 1",
            (account_id,),
        )
        overrides = {r["channel"]: json.loads(r["overrides_json"] or "{}") for r in await ov_cur.fetchall()}
    finally:
        await db.close()

    def _get(col: str, default: Any) -> Any:
        return acc[col] if col in keys and acc[col] is not None else default

    return {
        "ok": True,
        "mode": _get("moderation_mode", "off"),
        "can_timeout": bool(_get("moderation_can_timeout", 0)),
        "escalation_enabled": bool(_get("moderation_escalation_enabled", 1)),
        "antispam_enabled": bool(_get("antispam_viewer_enabled", 0)),
        "antispam_caps_pct": int(_get("antispam_caps_pct", 70)),
        "antispam_repeat_count": int(_get("antispam_repeat_count", 3)),
        "antispam_links": bool(_get("antispam_links", 1)),
        "antispam_emote_pct": int(_get("antispam_emote_pct", 80)),
        "antispam_exempt_roles": _get("antispam_exempt_roles", "streamer,mod,vip"),
        "eventsub_chat_messages": bool(_get("eventsub_chat_messages", 0)),
        "channels": channels,
        "channel_overrides": {
            ch: (ov.get("moderation_mode") or "")
            for ch, ov in overrides.items() if "moderation_mode" in ov
        },
        "modes": list(_MOD_MODES),
    }


@router.put("/api/accounts/{account_id}/moderation/settings")
async def moderation_put_settings(account_id: int, data: dict[str, Any]) -> dict:
    """Сохранение настроек модерации. Тумблер «Автомодерация» → mode=full/off.

    Если передан ``channel`` — пишется per-channel override в channel_overrides.
    """
    from app import moderation as _mod
    db = await get_db()
    try:
        cur = await db.execute("SELECT id FROM accounts WHERE id = ?", (account_id,))
        if not await cur.fetchone():
            return {"ok": False, "error": "Аккаунт не найден"}
        sets: list[str] = []
        values: list[Any] = []
        mode = data.get("mode")
        if mode is not None:
            mode = str(mode).strip().lower()
            if mode not in _MOD_MODES:
                return {"ok": False, "error": f"Режим должен быть одним из {list(_MOD_MODES)}"}
            sets.append("moderation_mode = ?"); values.append(mode)
        if "can_timeout" in data:
            sets.append("moderation_can_timeout = ?"); values.append(1 if data["can_timeout"] else 0)
        if "escalation_enabled" in data:
            sets.append("moderation_escalation_enabled = ?"); values.append(1 if data["escalation_enabled"] else 0)
        if "antispam_enabled" in data:
            sets.append("antispam_viewer_enabled = ?"); values.append(1 if data["antispam_enabled"] else 0)
        if "antispam_caps_pct" in data:
            sets.append("antispam_caps_pct = ?")
            values.append(max(0, min(100, int(data["antispam_caps_pct"] or 0))))
        if "antispam_repeat_count" in data:
            sets.append("antispam_repeat_count = ?")
            values.append(max(0, min(50, int(data["antispam_repeat_count"] or 0))))
        if "antispam_links" in data:
            sets.append("antispam_links = ?"); values.append(1 if data["antispam_links"] else 0)
        if "antispam_emote_pct" in data:
            sets.append("antispam_emote_pct = ?")
            values.append(max(0, min(100, int(data["antispam_emote_pct"] or 0))))
        if "antispam_exempt_roles" in data:
            sets.append("antispam_exempt_roles = ?")
            values.append(str(data["antispam_exempt_roles"] or "")[:100])
        if "eventsub_chat_messages" in data:
            sets.append("eventsub_chat_messages = ?"); values.append(1 if data["eventsub_chat_messages"] else 0)
        if sets:
            values.append(account_id)
            await db.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", tuple(values))

        # Per-channel override (plan §1): channel + mode ('' = убрать override).
        channel = str(data.get("channel") or "").lower().strip().lstrip("#")
        if channel and "channel_mode" in data:
            ch_mode = str(data["channel_mode"] or "").strip().lower()
            ov_cur = await db.execute(
                "SELECT overrides_json FROM channel_overrides WHERE account_id = ? AND channel = ?",
                (account_id, channel),
            )
            ov_row = await ov_cur.fetchone()
            overrides = json.loads(ov_row["overrides_json"] or "{}") if ov_row else {}
            if ch_mode in _MOD_MODES:
                overrides["moderation_mode"] = ch_mode
                await db.execute(
                    "INSERT INTO channel_overrides (account_id, channel, overrides_json, enabled) "
                    "VALUES (?, ?, ?, 1) ON CONFLICT(account_id, channel) DO UPDATE SET "
                    "overrides_json = excluded.overrides_json, enabled = 1",
                    (account_id, channel, json.dumps(overrides)),
                )
            elif ov_row:
                overrides.pop("moderation_mode", None)
                await db.execute(
                    "UPDATE channel_overrides SET overrides_json = ? WHERE account_id = ? AND channel = ?",
                    (json.dumps(overrides), account_id, channel),
                )
        await db.commit()
    finally:
        await db.close()
    _mod.invalidate_cache(account_id)
    await log_action("moderation_settings", str(account_id))
    return {"ok": True}


@router.get("/api/accounts/{account_id}/moderation/rules")
async def moderation_list_rules(account_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_rules WHERE account_id = ? ORDER BY id",
            (account_id,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    return {"ok": True, "rules": rows}


def _validate_action_ext(data: dict) -> tuple[str | None, str]:
    """Q01: расширенное действие правила. '' / отсутствует = NULL = прежняя лестница."""
    from app import moderation as _mod
    raw = data.get("action_ext")
    if raw is None:
        return None, ""
    value = str(raw).strip().lower()
    if value in ("", "auto"):
        return None, ""
    if value not in _mod.ACTION_EXT_CHOICES:
        allowed = sorted(k for k in _mod.ACTION_EXT_CHOICES if k and k != "auto")
        return None, f"Расширенное действие: одно из {allowed} (или пусто = по тяжести)"
    return value, ""


def _validate_moderation_rule(data: dict) -> tuple[dict | None, str]:
    pattern = str(data.get("pattern") or "").strip()
    if not pattern:
        return None, "Укажите слово или regex"
    category = str(data.get("category") or "custom").strip().lower()
    if category not in _MOD_CATEGORIES:
        return None, f"Категория: одна из {list(_MOD_CATEGORIES)}"
    action = str(data.get("action") or "block").strip().lower()
    if action not in _MOD_ACTIONS:
        return None, f"Действие: одно из {list(_MOD_ACTIONS)}"
    action_ext, err = _validate_action_ext(data)
    if err:
        return None, err
    try:
        severity = max(1, min(5, int(data.get("severity") or 3)))
    except (TypeError, ValueError):
        return None, "Severity: число 1-5"
    if pattern.startswith("re:"):
        import re as _re
        try:
            _re.compile(pattern[3:])
        except _re.error as exc:
            return None, f"Некорректный regex: {exc}"
    return {
        "pattern": pattern[:200],
        "category": category,
        "action": action,
        "action_ext": action_ext,
        "severity": severity,
        "channel": str(data.get("channel") or "").lower().strip().lstrip("#")[:100],
        "name": str(data.get("name") or "")[:100],
        "lang": str(data.get("lang") or "")[:5],
        "exempt_roles": str(data.get("exempt_roles") or "")[:100],
    }, ""


@router.post("/api/accounts/{account_id}/moderation/rules")
async def moderation_add_rule(account_id: int, data: dict[str, Any]) -> dict:
    from app import moderation as _mod
    rule, err = _validate_moderation_rule(data)
    if err:
        return {"ok": False, "error": err}
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_rules (account_id, channel, name, category, pattern, action, "
            "severity, enabled, lang, exempt_roles, action_ext) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (account_id, rule["channel"], rule["name"], rule["category"], rule["pattern"],
             rule["action"], rule["severity"], rule["lang"], rule["exempt_roles"], rule["action_ext"]),
        )
        await db.commit()
        rule_id = cur.lastrowid
    finally:
        await db.close()
    _mod.invalidate_cache(account_id)
    await log_action("moderation_rule_add", rule["pattern"])
    return {"ok": True, "id": rule_id}


@router.put("/api/moderation/rules/{rule_id}")
async def moderation_update_rule(rule_id: int, data: dict[str, Any]) -> dict:
    from app import moderation as _mod
    db = await get_db()
    try:
        cur = await db.execute("SELECT account_id FROM moderation_rules WHERE id = ?", (rule_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Правило не найдено"}
        account_id = row["account_id"]
        rule, err = _validate_moderation_rule(data)
        if err:
            return {"ok": False, "error": err}
        await db.execute(
            "UPDATE moderation_rules SET channel = ?, name = ?, category = ?, pattern = ?, "
            "action = ?, severity = ?, lang = ?, exempt_roles = ?, action_ext = ? WHERE id = ?",
            (rule["channel"], rule["name"], rule["category"], rule["pattern"],
             rule["action"], rule["severity"], rule["lang"], rule["exempt_roles"],
             rule["action_ext"], rule_id),
        )
        await db.commit()
    finally:
        await db.close()
    _mod.invalidate_cache(account_id)
    await log_action("moderation_rule_update", rule["pattern"])
    return {"ok": True}


@router.post("/api/moderation/rules/{rule_id}/toggle")
async def moderation_toggle_rule(rule_id: int) -> dict:
    from app import moderation as _mod
    db = await get_db()
    try:
        cur = await db.execute("SELECT account_id, enabled FROM moderation_rules WHERE id = ?", (rule_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Правило не найдено"}
        account_id = row["account_id"]
        new_val = 0 if row["enabled"] else 1
        await db.execute("UPDATE moderation_rules SET enabled = ? WHERE id = ?", (new_val, rule_id))
        await db.commit()
    finally:
        await db.close()
    _mod.invalidate_cache(account_id)
    return {"ok": True, "enabled": bool(new_val)}


@router.post("/api/accounts/{account_id}/moderation/rules/bulk-toggle")
async def moderation_rules_bulk_toggle(account_id: int, data: dict[str, Any]) -> dict:
    """Массовое включение/выключение всех правил бота."""
    from app import moderation as _mod
    enabled = 1 if data.get("enabled", True) else 0
    db = await get_db()
    updated = 0
    try:
        cur = await db.execute(
            "UPDATE moderation_rules SET enabled = ? WHERE account_id = ?",
            (enabled, account_id),
        )
        await db.commit()
        updated = cur.rowcount
    finally:
        await db.close()
    _mod.invalidate_cache(account_id)
    await log_action("moderation_rules_bulk_toggle", f"account {account_id}: enabled={enabled} (updated {updated})")
    return {"ok": True, "updated": updated, "enabled": bool(enabled)}


@router.delete("/api/moderation/rules/{rule_id}")
async def moderation_delete_rule(rule_id: int) -> dict:
    from app import moderation as _mod
    db = await get_db()
    try:
        cur = await db.execute("SELECT account_id FROM moderation_rules WHERE id = ?", (rule_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Правило не найдено"}
        account_id = row["account_id"]
        await db.execute("DELETE FROM moderation_rules WHERE id = ?", (rule_id,))
        await db.commit()
    finally:
        await db.close()
    _mod.invalidate_cache(account_id)
    await log_action("moderation_rule_delete", str(rule_id))
    return {"ok": True}


@router.post("/api/accounts/{account_id}/moderation/rules/import")
async def moderation_import_rules(account_id: int, data: dict[str, Any]) -> dict:
    """Импорт списка слов текстом (по строке). Опционально: action/severity/category."""
    from app import moderation as _mod
    text = str(data.get("text") or "")
    words = [w.strip() for w in text.splitlines() if w.strip() and not w.strip().startswith("#")]
    if not words:
        return {"ok": False, "error": "Список пуст"}
    action = str(data.get("action") or "block").strip().lower()
    if action not in _MOD_ACTIONS:
        return {"ok": False, "error": f"Действие: одно из {list(_MOD_ACTIONS)}"}
    action_ext, ext_err = _validate_action_ext(data)
    if ext_err:
        return {"ok": False, "error": ext_err}
    try:
        severity = max(1, min(5, int(data.get("severity") or 3)))
    except (TypeError, ValueError):
        severity = 3
    category = str(data.get("category") or "custom").strip().lower()
    if category not in _MOD_CATEGORIES:
        category = "custom"
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    db = await get_db()
    added = 0
    try:
        for w in words[:500]:
            try:
                await db.execute(
                    "INSERT INTO moderation_rules (account_id, channel, name, category, pattern, "
                    "action, severity, enabled, lang, action_ext) VALUES (?, ?, '', ?, ?, ?, ?, 1, '', ?)",
                    (account_id, channel, category, w[:200], action, severity, action_ext),
                )
                added += 1
            except Exception:
                continue
        await db.commit()
    finally:
        await db.close()
    _mod.invalidate_cache(account_id)
    await log_action("moderation_rules_import", f"{added} слов")
    return {"ok": True, "added": added}


# ─── Q03 (DEC-OWNER-004): база правил модерации per-канал + пресет Twitch ───

def _norm_base_channel(channel: str) -> str:
    return str(channel or "").lower().strip().lstrip("#")


def _preset_rules(name: str = "twitch") -> list[dict]:
    """Содержимое пресета правил (app/moderation_dicts/preset_*.json)."""
    from pathlib import Path
    fname = "preset_ru.json" if str(name).lower() in ("ru", "russian") else "preset_twitch.json"
    path = Path(__file__).resolve().parent / "moderation_dicts" / fname
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in data.get("rules", []) if isinstance(r, dict)]
    except Exception as exc:
        logger.warning("%s read error: %s", fname, exc)
        return []


def _twitch_preset_rules() -> list[dict]:
    """Содержимое пресета Twitch (app/moderation_dicts/preset_twitch.json)."""
    return _preset_rules("twitch")


def _validate_base_rule(data: dict) -> tuple[dict | None, str]:
    """Как _validate_moderation_rule, но без channel/name/lang/exempt_roles."""
    rule, err = _validate_moderation_rule(data)
    if err:
        return None, err
    return {k: rule[k] for k in ("pattern", "category", "action", "severity", "action_ext")}, ""


@router.get("/api/moderation/twitch-preset")
async def twitch_preset() -> dict:
    return {"ok": True, "rules": _twitch_preset_rules()}


@router.get("/api/moderation/base-rules")
async def base_rules_list(channel: str = "") -> dict:
    ch = _norm_base_channel(channel)
    if not ch:
        return {"ok": False, "error": "Укажите канал"}
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_channel_rules WHERE channel = ? ORDER BY id", (ch,)
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    return {"ok": True, "channel": ch, "rules": rows, "preset": _twitch_preset_rules()}


@router.post("/api/moderation/base-rules")
async def base_rules_add(data: dict[str, Any]) -> dict:
    from app import moderation as _mod
    ch = _norm_base_channel(str(data.get("channel") or ""))
    if not ch:
        return {"ok": False, "error": "Укажите канал"}
    rule, err = _validate_base_rule(data)
    if err:
        return {"ok": False, "error": err}
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT OR IGNORE INTO moderation_channel_rules "
            "(channel, pattern, category, action, severity, action_ext, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (ch, rule["pattern"], rule["category"], rule["action"],
             rule["severity"], rule["action_ext"]),
        )
        await db.commit()
        rule_id = cur.lastrowid
        if not rule_id:
            return {"ok": False, "error": "Такое правило уже есть у канала"}
    finally:
        await db.close()
    _mod.invalidate_base_rules(ch)
    await log_action("moderation_base_rule_add", f"{ch}: {rule['pattern']}")
    return {"ok": True, "id": rule_id}


@router.put("/api/moderation/base-rules/{rule_id}")
async def base_rules_update(rule_id: int, data: dict[str, Any]) -> dict:
    from app import moderation as _mod
    db = await get_db()
    try:
        cur = await db.execute("SELECT channel FROM moderation_channel_rules WHERE id = ?", (rule_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Правило не найдено"}
        if "enabled" in data and not any(k in data for k in ("pattern", "category", "action", "severity", "action_ext")):
            enabled = 1 if data.get("enabled") else 0
            await db.execute("UPDATE moderation_channel_rules SET enabled = ? WHERE id = ?", (enabled, rule_id))
            await db.commit()
            ch = row["channel"]
        else:
            rule, err = _validate_base_rule(data)
            if err:
                return {"ok": False, "error": err}
            await db.execute(
                "UPDATE moderation_channel_rules SET pattern = ?, category = ?, action = ?, "
                "severity = ?, action_ext = ? WHERE id = ?",
                (rule["pattern"], rule["category"], rule["action"],
                 rule["severity"], rule["action_ext"], rule_id),
            )
            await db.commit()
            ch = row["channel"]
    finally:
        await db.close()
    _mod.invalidate_base_rules(ch)
    return {"ok": True}


@router.post("/api/moderation/base-rules/bulk-toggle")
async def base_rules_bulk_toggle(data: dict[str, Any]) -> dict:
    """Массовое включение/выключение всех правил канала."""
    from app import moderation as _mod
    ch = _norm_base_channel(data.get("channel", ""))
    if not ch:
        return {"ok": False, "error": "Укажите канал"}
    enabled = 1 if data.get("enabled", True) else 0
    db = await get_db()
    updated = 0
    try:
        cur = await db.execute(
            "UPDATE moderation_channel_rules SET enabled = ? WHERE channel = ?",
            (enabled, ch),
        )
        await db.commit()
        updated = cur.rowcount
    finally:
        await db.close()
    _mod.invalidate_base_rules(ch)
    await log_action("moderation_base_rules_bulk_toggle", f"{ch}: enabled={enabled} (updated {updated})")
    return {"ok": True, "updated": updated, "enabled": bool(enabled)}


@router.post("/api/moderation/test")
async def moderation_test_phrase(data: dict[str, Any]) -> dict:
    """Песочница модерации: проверяет фразу без применения реальных наказаний."""
    from app import moderation as _mod

    text = str(data.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "Введите текст для проверки"}

    channel = _norm_base_channel(data.get("channel", ""))
    account_id = int(data.get("account_id") or 0)
    role = str(data.get("role") or "viewer").strip().lower()

    if account_id <= 0 and channel:
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT a.id FROM accounts a JOIN channels c ON a.id = c.account_id "
                "WHERE LOWER(c.channel_name) = ? AND a.bot_role = 'moderator' LIMIT 1",
                (channel,),
            )
            row = await cur.fetchone()
            if row:
                account_id = row["id"]
        finally:
            await db.close()

    verdicts = await _mod.check_message(
        account_id=account_id,
        channel=channel,
        username="sandbox_user",
        text=text,
        role=role,
    )

    direct_base_matched = []
    if not verdicts and channel:
        base_rules = await _mod.load_channel_base_rules(channel)
        norm_text = _mod._normalize(text)
        for rule in base_rules:
            if not rule.get("enabled", 1):
                continue
            rx = rule.get("regex")
            if rx and rx.search(norm_text):
                m = rx.search(norm_text)
                act, ext, dur = _mod.resolve_rule_action(rule.get("action") or "block", rule.get("action_ext"))
                direct_base_matched.append({
                    "category": rule.get("category") or "custom",
                    "action": act,
                    "severity": int(rule.get("severity") or 3),
                    "rule_id": rule.get("id"),
                    "rule_name": rule.get("pattern", ""),
                    "rule_action": rule.get("action", "block"),
                    "match": m.group(0) if m else "",
                    "action_ext": ext,
                    "duration_sec": dur,
                })

    result_verdicts = [v.to_dict() for v in verdicts] if verdicts else direct_base_matched

    return {
        "ok": True,
        "text": text,
        "channel": channel,
        "account_id": account_id,
        "matched": len(result_verdicts) > 0,
        "verdicts": result_verdicts,
        "primary_verdict": result_verdicts[0] if result_verdicts else None,
    }


@router.delete("/api/moderation/base-rules/clear")
async def base_rules_clear(channel: str = "") -> dict:
    """Удалить все правила модерации канала."""
    from app import moderation as _mod
    ch = _norm_base_channel(channel)
    if not ch:
        return {"ok": False, "error": "Укажите канал"}
    db = await get_db()
    deleted = 0
    try:
        cur = await db.execute("DELETE FROM moderation_channel_rules WHERE channel = ?", (ch,))
        await db.commit()
        deleted = cur.rowcount
    finally:
        await db.close()
    _mod.invalidate_base_rules(ch)
    await log_action("moderation_base_rules_clear", f"{ch}: очищено {deleted} правил")
    return {"ok": True, "channel": ch, "deleted": deleted}


@router.delete("/api/moderation/base-rules/{rule_id}")
async def base_rules_delete(rule_id: int) -> dict:
    from app import moderation as _mod
    db = await get_db()
    try:
        cur = await db.execute("SELECT channel, pattern FROM moderation_channel_rules WHERE id = ?", (rule_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Правило не найдено"}
        await db.execute("DELETE FROM moderation_channel_rules WHERE id = ?", (rule_id,))
        await db.commit()
        ch, pattern = row["channel"], row["pattern"]
    finally:
        await db.close()
    _mod.invalidate_base_rules(ch)
    await log_action("moderation_base_rule_delete", f"{ch}: {pattern}")
    return {"ok": True}


@router.post("/api/moderation/base-rules/seed")
async def base_rules_seed(data: dict[str, Any]) -> dict:
    """Скопировать пресет (Twitch или RU) в базу канала (идемпотентно, по UNIQUE(channel, pattern))."""
    from app import moderation as _mod
    ch = _norm_base_channel(str(data.get("channel") or ""))
    if not ch:
        return {"ok": False, "error": "Укажите канал"}
    preset_name = str(data.get("preset") or "twitch")
    preset = _preset_rules(preset_name)
    if not preset:
        return {"ok": False, "error": f"Пресет {preset_name} не найден"}
    db = await get_db()
    added = 0
    try:
        for r in preset:
            try:
                cur = await db.execute(
                    "INSERT OR IGNORE INTO moderation_channel_rules "
                    "(channel, pattern, category, action, severity, action_ext, enabled) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (ch, str(r.get("pattern") or "")[:200],
                     str(r.get("category") or "custom"),
                     str(r.get("action") or "block"),
                     max(1, min(5, int(r.get("severity") or 3))),
                     str(r.get("action_ext") or "") or None),
                )
                added += cur.rowcount
            except Exception:
                continue
        await db.commit()
    finally:
        await db.close()
    _mod.invalidate_base_rules(ch)
    await log_action("moderation_base_rule_seed", f"{ch}: +{added}")
    return {"ok": True, "added": added}


@router.get("/api/moderation/base-rules/export")
async def base_rules_export(channel: str = "") -> Response:
    """Экспорт правил модерации канала в виде JSON-файла для скачивания."""
    ch = _norm_base_channel(channel)
    if not ch:
        return Response(status_code=400, content=json.dumps({"ok": False, "error": "Укажите канал"}))
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT pattern, category, action, severity, action_ext, enabled FROM moderation_channel_rules "
            "WHERE channel = ? ORDER BY id",
            (ch,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    export_data = {
        "channel": ch,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "rules": rows,
    }
    content = json.dumps(export_data, indent=2, ensure_ascii=False)
    fname = f"mod-rules-{ch}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/api/moderation/base-rules/import")
async def base_rules_import(data: dict[str, Any]) -> dict:
    """Импорт списка правил для канала (из JSON или списка строк)."""
    from app import moderation as _mod
    ch = _norm_base_channel(str(data.get("channel") or ""))
    if not ch:
        return {"ok": False, "error": "Укажите канал"}

    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        return {"ok": False, "error": "Список правил пуст или некорректен"}

    db = await get_db()
    added = 0
    try:
        for item in raw_rules:
            if isinstance(item, str):
                pat = item.strip()
                if not pat or pat.startswith("#"):
                    continue
                r_dict = {"pattern": pat, "category": "custom", "action": "block", "severity": 3, "action_ext": None}
            elif isinstance(item, dict):
                pat = str(item.get("pattern") or "").strip()
                if not pat:
                    continue
                cat = str(item.get("category") or "custom")
                act = str(item.get("action") or "block")
                if act not in ("replace", "block", "timeout", "log"):
                    act = "block"
                sev = max(1, min(5, int(item.get("severity") or 3)))
                act_ext = str(item.get("action_ext") or "") or None
                r_dict = {"pattern": pat, "category": cat, "action": act, "severity": sev, "action_ext": act_ext}
            else:
                continue

            try:
                cur = await db.execute(
                    "INSERT OR IGNORE INTO moderation_channel_rules "
                    "(channel, pattern, category, action, severity, action_ext, enabled) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (ch, r_dict["pattern"][:200], r_dict["category"], r_dict["action"],
                     r_dict["severity"], r_dict["action_ext"]),
                )
                added += cur.rowcount
            except Exception:
                continue
        await db.commit()
    finally:
        await db.close()

    _mod.invalidate_base_rules(ch)
    await log_action("moderation_base_rules_import", f"{ch}: +{added}/{len(raw_rules)}")
    return {"ok": True, "channel": ch, "imported": added, "total": len(raw_rules)}


@router.get("/api/accounts/{account_id}/moderation/events")
async def moderation_events(
    account_id: int,
    limit: int = 100,
    username: str = "",
    category: str = "",
    channel: str = "",
    source: str = "",
) -> dict:
    limit = max(1, min(500, limit))
    q = "SELECT * FROM moderation_events WHERE account_id = ?"
    params: list[Any] = [account_id]
    if username:
        q += " AND username = ?"; params.append(username.lower().lstrip("#"))
    if category:
        q += " AND category = ?"; params.append(category)
    if channel:
        q += " AND channel = ?"; params.append(channel.lower().lstrip("#"))
    if source:
        q += " AND source = ?"; params.append(source)
    q += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    db = await get_db()
    try:
        cur = await db.execute(q, tuple(params))
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    return {"ok": True, "events": rows}


@router.get("/api/accounts/{account_id}/moderation/events/export.csv")
async def moderation_events_export_csv(account_id: int) -> Response:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_events WHERE account_id = ? ORDER BY created_at DESC LIMIT 5000",
            (account_id,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["id", "created_at", "channel", "username", "rule_name", "category",
                     "severity", "action_taken", "source", "message_excerpt"])
    for r in rows:
        writer.writerow([r["id"], r["created_at"], r["channel"], r["username"], r["rule_name"],
                         r["category"], r["severity"], r["action_taken"], r["source"],
                         (r["message_excerpt"] or "").replace("\n", " ")[:200]])
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=moderation_events_{account_id}.csv"},
    )


@router.delete("/api/accounts/{account_id}/moderation/events")
async def moderation_events_clear(account_id: int) -> dict:
    db = await get_db()
    try:
        await db.execute("DELETE FROM moderation_events WHERE account_id = ?", (account_id,))
        await db.commit()
    finally:
        await db.close()
    await log_action("moderation_events_clear", str(account_id))
    return {"ok": True}


@router.get("/api/accounts/{account_id}/moderation/stats")
async def moderation_stats(account_id: int) -> dict:
    """§4: нарушений за 24ч, топ-нарушители, распределение по категориям."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM moderation_events "
            "WHERE account_id = ? AND created_at >= datetime('now', '-1 day')",
            (account_id,),
        )
        day = (await cur.fetchone())["n"]
        top_cur = await db.execute(
            "SELECT username, COUNT(*) AS n FROM moderation_events "
            "WHERE account_id = ? AND created_at >= datetime('now', '-7 day') "
            "GROUP BY username ORDER BY n DESC LIMIT 10",
            (account_id,),
        )
        top = [{"username": r["username"], "count": r["n"]} for r in await top_cur.fetchall()]
        cat_cur = await db.execute(
            "SELECT category, COUNT(*) AS n FROM moderation_events "
            "WHERE account_id = ? AND created_at >= datetime('now', '-7 day') "
            "GROUP BY category ORDER BY n DESC",
            (account_id,),
        )
        by_category = [{"category": r["category"], "count": r["n"]} for r in await cat_cur.fetchall()]
    finally:
        await db.close()
    return {"ok": True, "day": day, "top_offenders": top, "by_category": by_category}


@router.post("/api/accounts/{account_id}/moderation/test")
async def moderation_test(account_id: int, data: dict[str, Any]) -> dict:
    """§4: «Проверить сообщение» — тестовый ввод → какой вердикт и почему.

    Не пишет в журнал и не применяет таймауты.
    """
    from app import moderation as _mod
    text = str(data.get("text") or "")
    channel = str(data.get("channel") or "").lower().strip().lstrip("#")
    username = str(data.get("username") or "test_user")
    role = str(data.get("role") or "viewer").lower()
    if not text.strip():
        return {"ok": False, "error": "Введите текст сообщения"}
    mode = await _mod.get_mode(account_id, channel)
    verdicts = await _mod.check_message(account_id, channel, username, text, role=role)
    settings = await _mod.get_settings(account_id)
    hits: list[dict] = []
    if mode != "off" and settings.get("antispam_viewer_enabled"):
        raw_hits = _mod.spam_detector.check(account_id, channel, username, text, settings, role=role, mode=mode)
        hits = [
            {"category": h.category, "severity": h.severity, "detail": h.detail, "action": h.action}
            for h in raw_hits
        ]
    return {
        "ok": True,
        "mode": mode,
        "verdicts": [v.to_dict() for v in verdicts],
        "spam": hits,
        "summary": _mod.summarize(verdicts),
    }


@router.get("/api/moderation/recent")
async def moderation_recent() -> dict:
    """Мини-виджет Dashboard (§3): последние нарушения, топ-5 за час, все аккаунты."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT e.*, a.nickname AS bot_nickname FROM moderation_events e "
            "LEFT JOIN accounts a ON a.id = e.account_id "
            "WHERE e.created_at >= datetime('now', '-1 hour') "
            "ORDER BY e.severity DESC, e.created_at DESC LIMIT 5",
        )
        rows = [dict(r) for r in await cur.fetchall()]
        cnt_cur = await db.execute(
            "SELECT COUNT(*) AS n FROM moderation_events WHERE created_at >= datetime('now', '-1 hour')",
        )
        hour_total = (await cnt_cur.fetchone())["n"]
    finally:
        await db.close()
    return {"ok": True, "events": rows, "hour_total": hour_total}


@router.post("/api/accounts/{account_id}/moderation/eventsub-chat")
async def moderation_eventsub_chat_toggle(account_id: int, data: dict[str, Any]) -> dict:
    """Toggle «Слушать сообщения через EventSub» (§3). При работающем EventSub
    переподключает клиент, чтобы подписка применилась сразу."""
    enabled = bool(data.get("enabled"))
    db = await get_db()
    try:
        await db.execute(
            "UPDATE accounts SET eventsub_chat_messages = ? WHERE id = ?",
            (1 if enabled else 0, account_id),
        )
        cur = await db.execute(
            "SELECT nickname, token, eventsub_enabled FROM accounts WHERE id = ?",
            (account_id,),
        )
        acc = await cur.fetchone()
        ch_cur = await db.execute(
            "SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1",
            (account_id,),
        )
        channels = [r["channel_name"] for r in await ch_cur.fetchall()]
        await db.commit()
    finally:
        await db.close()
    from app.server import eventsub_manager, bot_manager
    if (
        acc
        and bool(acc["eventsub_enabled"])
        and channels
        and bot_manager.get_status(account_id).get("connected")
    ):
        try:
            await eventsub_manager.stop_for_account(account_id)
            await eventsub_manager.start_for_account(
                account_id, acc["nickname"], decrypt_token(acc["token"]), channels,
            )
        except Exception as exc:
            logger.warning("eventsub chat toggle restart error: %s", exc)
    return {"ok": True, "enabled": enabled}
