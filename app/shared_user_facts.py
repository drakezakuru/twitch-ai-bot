"""Additive compatibility migration from legacy shared facts to per-bot memory."""

from __future__ import annotations

import json


def normalize_username(name: str) -> str:
    return (name or "").strip().lstrip("@").lower()


def normalize_fact(fact: str, *, max_len: int = 240) -> str:
    f = (fact or "").strip()
    if len(f) > max_len:
        f = f[:max_len - 1] + "…"
    return f


# --- P8-C2: миграция в per-bot user_memory ---------------------------------


async def migrate_shared_facts_once(db) -> dict:
    """Разовый переезд shared_user_facts → user_memory КАЖДОГО бота (P8-C2).

    Вердикт владельца: общая память удалена; чтобы факты не потерялись, каждый
    бот получает копию в свою user_memory (facts JSON), дубликаты фактов
    (case-insensitive) не задваиваются. Идемпотентно: флаг-метка в settings.

    `db` — соединение из init_db (открытый транзакционный контекст).
    """
    if db is None:
        return {"skipped": "no db"}
    try:
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shared_user_facts'")
        if not await cur.fetchone():
            return {"skipped": "no table"}
        cur = await db.execute("SELECT value FROM settings WHERE key = 'shared_facts_migrated_to_per_bot'")
        row = await cur.fetchone()
        if row and str(row[0]) == "1":
            return {"skipped": "already migrated"}
    except Exception:
        return {"skipped": "check failed"}

    cur = await db.execute("SELECT username, fact, confidence FROM shared_user_facts ORDER BY id")
    rows = [(r[0], r[1], r[2]) for r in await cur.fetchall()]
    cur = await db.execute("SELECT id FROM accounts ORDER BY id")
    bots = [int(r[0]) for r in await cur.fetchall()]

    copied = 0
    for bot_id in bots:
        cur = await db.execute("SELECT username, facts FROM user_memory WHERE account_id = ?", (bot_id,))
        existing = {str(r[0]): json.loads(r[1] or "[]") for r in await cur.fetchall()}
        for (r_user, r_fact, r_conf) in rows:
            u = normalize_username(r_user)
            f = normalize_fact(r_fact)
            if not u or not f:
                continue
            facts = existing.get(u, [])
            if any(str(x.get("fact", "")).strip().lower() == f.lower() for x in facts):
                continue
            facts.append({
                "fact": f,
                "confidence": round(max(0.0, min(1.0, float(r_conf or 0.8))), 2),
                "source": "migrated_shared",
            })
            existing[u] = facts
            await db.execute(
                """INSERT INTO user_memory (account_id, username, facts, last_seen)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(account_id, username) DO UPDATE SET facts = excluded.facts""",
                (bot_id, u, json.dumps(facts, ensure_ascii=False)),
            )
            copied += 1

    await db.execute(
        """INSERT INTO settings (key, value) VALUES ('shared_facts_migrated_to_per_bot', '1')
           ON CONFLICT(key) DO UPDATE SET value = '1'""")
    await db.commit()
    return {"accounts": len(bots), "facts_copied": copied, "rows": len(rows)}
