"""import_export — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from fastapi import Request

from app.database import get_db
from app.routes import log_action, logger
from app.routes import router  # noqa: E402


# ===================== IMPORT =====================

@router.post("/api/import")
async def import_settings(request: Request) -> dict:
    data = await request.json()
    if not data.get("accounts"):
        return {"ok": False, "error": "No accounts in import"}
    db = await get_db()
    try:
        # Import AI config
        ai = data.get("ai_config", {})
        if ai:
            for key in ("provider", "openrouter_key", "openrouter_chat", "openrouter_vision",
                         "ollama_host", "ollama_chat", "ollama_vision"):
                if key in ai:
                    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                                     (f"ai_{key}", str(ai[key])))
        # Import accounts
        for acc in data.get("accounts", []):
            nick = acc.get("nickname", "")
            token = acc.get("token", "")
            if not nick or not token:
                continue
            await db.execute("INSERT OR IGNORE INTO accounts (nickname, token, enabled) VALUES (?, ?, ?)",
                             (nick, token, acc.get("enabled", 1)))
            row = await db.execute("SELECT id FROM accounts WHERE nickname = ?", (nick,))
            row = await row.fetchone()
            if not row:
                continue
            aid = row[0]
            for ch in acc.get("channels", []):
                await db.execute("INSERT OR IGNORE INTO channels (account_id, channel_name) VALUES (?, ?)",
                                 (aid, ch.get("channel_name", "")))
            for p in acc.get("personas", []):
                await db.execute("INSERT INTO personas (account_id, name, system_prompt, is_active) VALUES (?, ?, ?, ?)",
                                 (aid, p.get("name",""), p.get("system_prompt",""), p.get("is_active",0)))
            for t in acc.get("triggers", []):
                await db.execute("INSERT INTO triggers (account_id, keyword, response, use_ai) VALUES (?, ?, ?, ?)",
                                 (aid, t.get("keyword",""), t.get("response",""), t.get("use_ai",1)))
            for e in acc.get("events", []):
                await db.execute("INSERT INTO event_responses (account_id, event_type, response, use_ai, chance) VALUES (?, ?, ?, ?, ?)",
                                 (aid, e.get("event_type",""), e.get("response",""), e.get("use_ai",0), e.get("chance",100)))
            for b in acc.get("banlist", []):
                await db.execute("INSERT OR IGNORE INTO banlist (account_id, username) VALUES (?, ?)",
                                 (aid, b.get("username","")))
            for ph in acc.get("phrases", []):
                await db.execute("INSERT INTO quick_phrases (account_id, phrase) VALUES (?, ?)",
                                 (aid, ph.get("phrase","")))
            for w in acc.get("wordfilter", []):
                await db.execute("INSERT INTO word_filter (account_id, word) VALUES (?, ?)",
                                 (aid, w.get("word","")))
        await db.commit()
        await log_action("import", f"Импортировано {len(data.get('accounts',[]))} аккаунтов")
        return {"ok": True}
    except Exception as e:
        logger.error("Import error: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        await db.close()
