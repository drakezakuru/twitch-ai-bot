"""Feature V: HEATMAP — вынесено из app/routes.py (P5-сплит, PLAN.md).

Модуль декорирует ОБЩИЙ `router` из app.routes (тот же объект, что монтируют
тесты `from app.routes import router`), поэтому импортируется ВНИЗУ routes.py
(после создания router) — поздний импорт разрывает цикл. Новые вынесенные
секции следуют этому же шаблону: `from app.routes import router` + декораторы,
одна строка импорта внизу routes.py.
"""
from typing import Any

from app.database import get_db
from app.routes import router  # noqa: E402 — валиден: модуль импортируется из конца routes.py


@router.get("/api/stats/heatmap")
async def get_chat_heatmap(days: int = 30, account_id: int = 0, channel: str = "") -> dict:
    """Heatmap активности чата по дням недели и часам.

    Возвращает 7×24 grid: строки 0..6 = Пн..Вс, колонки 0..23 — час.
    """
    days = max(1, min(365, days))
    channel = (channel or "").strip().lstrip("#")
    db = await get_db()
    try:
        sql = (
            "SELECT strftime('%w', timestamp) AS dow, strftime('%H', timestamp) AS hour, "
            "COUNT(*) AS cnt FROM chat_log "
            "WHERE timestamp > datetime('now', ?) AND is_bot = 0 "
        )
        params: list[Any] = [f"-{days} days"]
        if channel:
            sql += "AND channel = ? "
            params.append(channel)
        if account_id:
            sql += "AND account_id = ? "
            params.append(account_id)
        sql += "GROUP BY dow, hour"
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
    finally:
        await db.close()

    # Инициализируем grid: ключ — (dow_iso, hour). dow_iso: 0=Пн..6=Вс
    # SQLite '%w': 0=Sunday..6=Saturday → конвертим в ISO (Пн=0..Вс=6)
    grid: dict[tuple[int, int], int] = {}
    max_cell = 0
    total = 0
    for r in rows:
        sql_dow = int(r["dow"])  # 0..6 (вс..сб)
        iso_dow = (sql_dow - 1) % 7  # 0=Пн, 6=Вс
        hour = int(r["hour"])
        cnt = int(r["cnt"])
        grid[(iso_dow, hour)] = cnt
        if cnt > max_cell:
            max_cell = cnt
        total += cnt

    cells = []
    for d in range(7):
        for h in range(24):
            cells.append({"dow": d, "hour": h, "count": grid.get((d, h), 0)})

    return {
        "days": days,
        "channel": channel,
        "account_id": account_id,
        "grid": cells,
        "max_cell": max_cell,
        "total": total,
    }
