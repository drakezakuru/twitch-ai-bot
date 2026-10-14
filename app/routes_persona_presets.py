"""persona_presets — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from fastapi import Request

from app.database import get_db
import json
from app.routes import router  # noqa: E402


# ===================== v11: PERSONA PRESETS + GENERATE =====================

@router.get("/api/accounts/{account_id}/behavior-presets")
async def list_custom_behavior_presets(account_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute("SELECT id, name, description, values_json FROM custom_behavior_presets WHERE account_id = ? ORDER BY name", (account_id,))
        items = []
        for row in await cur.fetchall():
            item = dict(row)
            try:
                item["values"] = json.loads(item.pop("values_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["values"] = {}
            items.append(item)
        return {"ok": True, "presets": items}
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/behavior-presets")
async def create_custom_behavior_preset(account_id: int, data: dict[str, Any]) -> dict:
    name = str(data.get("name") or "").strip()[:80]
    if not name:
        return {"ok": False, "error": "name required"}
    values = data.get("values") if isinstance(data.get("values"), dict) else {}
    allowed = {f for f in ("humor_level", "sarcasm_level", "darkness_level", "crudeness_level", "adult_humor", "seriousness", "emotionality", "contact_level", "chat_affinity", "observation_only")}
    values = {k: v for k, v in values.items() if k in allowed}
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO custom_behavior_presets (account_id, name, description, values_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(account_id, name) DO UPDATE SET description=excluded.description, values_json=excluded.values_json, updated_at=CURRENT_TIMESTAMP",
            (account_id, name, str(data.get("description") or "")[:200], json.dumps(values, ensure_ascii=False)),
        )
        await db.commit()
        return {"ok": True, "id": cur.lastrowid, "name": name, "values": values}
    finally:
        await db.close()


@router.delete("/api/behavior-presets/{preset_id}")
async def delete_custom_behavior_preset(preset_id: int) -> dict:
    db = await get_db()
    try:
        cur = await db.execute("DELETE FROM custom_behavior_presets WHERE id = ?", (preset_id,))
        await db.commit()
        return {"ok": cur.rowcount > 0}
    finally:
        await db.close()

@router.get("/api/persona-presets")
async def list_persona_presets_route():
    from app.bot_presets import OBSERVER_PRESET, list_presets
    presets = list_presets()
    presets.append({"id": "observer", **OBSERVER_PRESET})
    return {"ok": True, "presets": presets}


@router.post("/api/accounts/{account_id}/persona/apply-preset")
async def apply_persona_preset_route(account_id: int, request: Request):
    from app.bot_presets import apply_preset
    from app.bot_persona import BotPersona
    body = await request.json()
    preset_id = body.get("preset_id", "")
    preset = apply_preset(preset_id)
    if preset_id == "observer":
        preset = {"label": "👀 Спостерігач", "observation_only": True}
    if not preset:
        return {"error": f"Preset '{preset_id}' not found"}
    # Завантажуємо існуючу персону та мержимо з пресетом
    db = await get_db()
    try:
        cur = await db.execute("SELECT persona_json FROM accounts WHERE id = ?", (account_id,))
        row = await cur.fetchone()
        existing = BotPersona.from_json(row["persona_json"] if row else None)
    finally:
        await db.close()

    # Застосовуємо пресет
    for k, v in preset.items():
        if k in ("label", "description"):
            continue
        if hasattr(existing, k):
            setattr(existing, k, v)
    existing.clamp()

    # Зберігаємо
    db = await get_db()
    try:
        await db.execute(
            "UPDATE accounts SET persona_json = ? WHERE id = ?",
            (existing.to_json(), account_id),
        )
        await db.commit()
    finally:
        await db.close()

    return {"ok": True, "persona": existing.to_dict()}


@router.post("/api/accounts/{account_id}/generate-persona")
async def generate_persona_route(account_id: int, request: Request):
    from app.bot_presets import generate_persona_via_ai
    from app.bot_persona import BotPersona
    body = await request.json()
    description = body.get("description", "")
    if not description:
        return {"error": "No description provided"}
    result = await generate_persona_via_ai(description, account_id)
    persona = BotPersona.from_dict(result)
    persona.clamp()

    # Зберігаємо
    db = await get_db()
    try:
        await db.execute(
            "UPDATE accounts SET persona_json = ? WHERE id = ?",
            (persona.to_json(), account_id),
        )
        await db.commit()
    finally:
        await db.close()

    return {"ok": True, "persona": persona.to_dict()}


@router.post("/api/accounts/{account_id}/persona/from-history")
async def persona_from_history(account_id: int, request: Request):
    """H (REWORK_PLAN): «Описать характер по истории» — AI читает загруженную
    историю сообщений (txt/json, поле messages или history) и предлагает поля
    персоны (имя/черты/фразы/уровни). Возвращает proposal — НЕ сохраняет:
    владелец смотрит и жмёт «Сохранить персонажа» сам."""
    from app.ai_service import AIService
    import json as _json
    import re as _re

    body = await request.json()
    history = body.get("messages") or body.get("history") or []
    if isinstance(history, str):
        history = [
            {"author": ln.split(":", 1)[0].strip(), "text": ln.split(":", 1)[1].strip()}
            for ln in history.splitlines() if ln.strip() and ": " in ln
        ]
    lines = []
    for m in history:
        if isinstance(m, dict):
            author, text = str(m.get("author") or "").strip(), str(m.get("text") or "").strip()
        elif isinstance(m, str) and ": " in m:
            author, text = (p.strip() for p in m.split(": ", 1))
        else:
            continue
        if author and text:
            lines.append(f"{author}: {text[:200]}")
    user = str(body.get("user") or "").strip()
    if user:
        lines = [ln for ln in lines if ln.lower().startswith(f"{user.lower()}:")]
    sample = "\n".join(lines[:600])[:8000]
    if len(sample) < 100:
        return {"ok": False, "error": "not_enough_history"}

    ai = AIService()
    prompt = (
        "Ниже — история сообщений зрителя из Twitch-чата. Определи по ней ЕГО ХАРАКТЕР "
        "и верни ТОЛЬКО JSON-объект (без пояснений) вида:\n"
        '{"name": "", "age": 0, "location": "", "occupation": "", '
        '"personality": ["", ""], "favorite_games": [""], "catchphrases": ["", ""], '
        '"background": "", "humor_level": 50, "sarcasm_level": 50, '
        '"seriousness": 50, "emotionality": 50}\n'
        "Уровни — целые 0-100 по тону сообщений.\n\nИстория:\n" + sample
    )
    raw = await ai.generate_text(prompt=prompt, system="Ты анализатор личности. Верни только JSON.", account_id=account_id)
    match = _re.search(r"\{.*\}", raw or "", _re.DOTALL)
    if not match:
        return {"ok": False, "error": "no_json"}
    try:
        proposal = _json.loads(match.group())
    except _json.JSONDecodeError:
        return {"ok": False, "error": "json_parse_error"}
    return {"ok": True, "proposal": proposal, "messages_used": len(lines[:600])}
