"""P3 §1.4/К3 → P8-C3: отношение ботов к стримеру (негативные тона добавлены).

Центр управления — карточка бота → вкладка «Роль» (перенесено из Мозга по
вердикту C3). Канал берётся из первого подключённого канала бота; скоуп
per-bot × per-channel, fallback (bot, '') → neutral.

* adore    — бот обожает стримера (восторг, поддержка);
* friendly — дружелюбное тепло, уважение;
* neutral  — ничего особенного (дефолт, блок в промпт НЕ попадает);
* watching — просто случайный зритель, стример не близок;
* irritated   — «раздражает» (негативный тон, P8-C3);
* intolerable — «не выносит» (негативный тон, P8-C3);
* dismissive  — «пренебрегает» (негативный тон, P8-C3).

Строка попадает в блок «О стримере» в промпте (chat_analyzer).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.security import auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/streamer-attitude", tags=["streamer-attitude"],
                   dependencies=[Depends(auth_dependency)])

ATTITUDES = ("adore", "friendly", "neutral", "watching",
             "irritated", "intolerable", "dismissive")

ATTITUDE_PROMPT = {
    "adore": "Отношение к стримеру: ты его ОБОЖАЕШЬ — искренне восторгаешься, "
             "хвалишь и поддерживаешь даже мелочи.",
    "friendly": "Отношение к стримеру: дружелюбное тепло — уважаешь его и часто "
                "поддерживаешь.",
    "watching": "Отношение к стримеру: ты просто случайный зритель — стример тебе "
                "не близок, никакого восхищения.",
    # P8-C3: негативные тона
    "irritated": "Отношение к стримеру: он тебя РАЗДРАЖАЕТ — отвечаешь коротко и "
                 "сухо, раздражение проскальзывает в репликах, но прямых оскорблений нет.",
    "intolerable": "Отношение к стримеру: ты его НЕ ВЫНОСИШЬ — держишься холодно и "
                   "колко, сарказм и недовольство, но без мата и прямой грубости.",
    "dismissive": "Отношение к стримеру: ты его ПРЕНЕБРЕГАЕШЬ — свысока, без "
                  "уважения, отвечаешь нехотя, будто он тебя не интересует.",
}


async def ensure_schema(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS streamer_attitude (
            account_id INTEGER NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            attitude TEXT NOT NULL DEFAULT 'neutral'
                CHECK(attitude IN ('adore','friendly','neutral','watching',
                                   'irritated','intolerable','dismissive')),
            PRIMARY KEY (account_id, channel),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )""")
    # P8-C3: у существующих таблиц CHECK без негативных тонов — пересоздаём.
    # Идемпотентно: смотрим DDL в sqlite_master.
    cur = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='streamer_attitude'")
    row = await cur.fetchone()
    if row and "dismissive" not in (row["sql"] if isinstance(row, dict) else str(row[0])):
        await db.execute("ALTER TABLE streamer_attitude RENAME TO streamer_attitude_old")
        await db.execute("""
            CREATE TABLE streamer_attitude (
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                attitude TEXT NOT NULL DEFAULT 'neutral'
                    CHECK(attitude IN ('adore','friendly','neutral','watching',
                                       'irritated','intolerable','dismissive')),
                PRIMARY KEY (account_id, channel),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )""")
        await db.execute("""
            INSERT OR IGNORE INTO streamer_attitude (account_id, channel, attitude)
            SELECT account_id, channel, attitude FROM streamer_attitude_old""")
        await db.execute("DROP TABLE streamer_attitude_old")


def _norm_channel(channel: str) -> str:
    return (channel or "").strip().lstrip("#").lower()


async def get_attitude(account_id: int, channel: str = "") -> str:
    """(bot, channel) → (bot, '') → 'neutral'."""
    from app.database import get_db
    ch = _norm_channel(channel)
    if not ch:
        return "neutral"
    db = await get_db()
    try:
        await ensure_schema(db)
        cur = await db.execute(
            "SELECT attitude FROM streamer_attitude WHERE account_id = ? AND channel = ?",
            (int(account_id), ch))
        row = await cur.fetchone()
        if row and row["attitude"] in ATTITUDES:
            return row["attitude"]
        return "neutral"
    finally:
        await db.close()


async def set_attitude(account_id: int, channel: str, attitude: str) -> dict:
    from app.database import get_db
    if attitude not in ATTITUDES:
        return {"ok": False, "error": "bad_attitude"}
    ch = _norm_channel(channel)
    if not ch:
        raise HTTPException(status_code=400, detail="channel_required")
    db = await get_db()
    try:
        await ensure_schema(db)
        await db.execute(
            "INSERT INTO streamer_attitude (account_id, channel, attitude) VALUES (?, ?, ?) "
            "ON CONFLICT(account_id, channel) DO UPDATE SET attitude=excluded.attitude",
            (int(account_id), ch, attitude))
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


async def list_attitudes(channel: str = "") -> list[dict]:
    """Все боты с их отношением для выбранного канала (без fallback)."""
    from app.database import get_db
    ch = _norm_channel(channel)
    db = await get_db()
    try:
        await ensure_schema(db)
        cur = await db.execute("""
            SELECT a.id AS account_id, a.nickname, COALESCE(sa.attitude, 'neutral') AS attitude
            FROM accounts a
            LEFT JOIN streamer_attitude sa
              ON sa.account_id = a.id AND sa.channel = ?
            ORDER BY a.id
        """, (ch,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


def format_attitude_line(attitude: str) -> str:
    return ATTITUDE_PROMPT.get(attitude, "")


# ── HTTP ────────────────────────────────────────────────────────────────

@router.get("")
async def api_list(channel: str = "") -> dict:
    items = await list_attitudes(channel)
    # P8-C3: per-канальная карта для карточки бота (не ломает старый формат)
    per = await list_attitudes_per_channel()
    for it in items:
        it["_per_channel"] = per.get(int(it["account_id"]), {})
    return {"ok": True, "items": items}


async def list_attitudes_per_channel() -> dict[int, dict[str, str]]:
    """bot_id → {channel: attitude} по всем каналам (для карточки бота)."""
    from app.database import get_db
    db = await get_db()
    try:
        await ensure_schema(db)
        cur = await db.execute("SELECT account_id, channel, attitude FROM streamer_attitude")
        out: dict[int, dict[str, str]] = {}
        for r in await cur.fetchall():
            out.setdefault(int(r["account_id"]), {})[r["channel"]] = r["attitude"]
        return out
    finally:
        await db.close()


@router.put("/{account_id}")
async def api_set(account_id: int, request: Request) -> dict:
    data = await request.json() or {}
    channel = str(data.get("channel") or "")
    attitude = str(data.get("attitude") or "neutral")
    return await set_attitude(account_id, channel, attitude)
