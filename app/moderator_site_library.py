"""Moderator-site read-only library projection (MOD-09).

Moderators see approved items of their own account+channel scope only. DTOs never
contain filesystem paths or tokens; unapproved (quarantine) items stay invisible
to moderators — those belong to the owner review queue in the local panel.
"""
from __future__ import annotations

from typing import Any


async def ensure_schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS ms_library_items (
      id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, channel TEXT NOT NULL,
      kind TEXT NOT NULL CHECK (kind IN ('media','sound')),
      title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'approved',
      favorite INTEGER NOT NULL DEFAULT 0,
      size_bytes INTEGER NOT NULL DEFAULT 0, content_type TEXT NOT NULL DEFAULT '',
      owner_approved_at TEXT);
    CREATE INDEX IF NOT EXISTS ms_library_scope ON ms_library_items(account_id, channel, kind, status);
    """)


async def add_item(db: Any, item_id: str, account_id: int, channel: str, kind: str,
                   title: str, *, status: str = "approved", size_bytes: int = 0,
                   content_type: str = "", favorite: int = 0) -> None:
    await db.execute(
        "INSERT INTO ms_library_items(id, account_id, channel, kind, title, status, favorite,"
        " size_bytes, content_type) VALUES (?,?,?,?,?,?,?,?,?)",
        (item_id, account_id, channel, kind, title, status, favorite, size_bytes, content_type),
    )
    await db.commit()


def _dto(row: tuple) -> dict[str, Any]:
    # Deliberately minimal: no paths, no tokens, no internal filenames.
    return {"id": row[0], "kind": row[1], "title": row[2], "status": row[3],
            "favorite": bool(row[4]), "size_bytes": row[5], "content_type": row[6]}


async def list_items(db: Any, *, account_id: int, channel: str, kind: str,
                     query: str = "", page: int = 1, limit: int = 20,
                     favorites_only: bool = False) -> dict[str, Any]:
    """Scope-fenced read-only projection; unknown scope yields an empty page, not an error."""
    if kind not in {"media", "sound"}:
        raise ValueError("invalid_kind")
    page = max(1, int(page))
    limit = max(1, min(int(limit), 100))
    where = ["account_id=?", "channel=?", "kind=?", "status='approved'"]
    args: list[Any] = [account_id, channel, kind]
    if query:
        where.append("title LIKE ? ESCAPE '\\'")
        args.append("%" + query.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%")
    if favorites_only:
        where.append("favorite=1")
    clause = " AND ".join(where)
    total = (await (await db.execute(f"SELECT count(*) FROM ms_library_items WHERE {clause}", args)).fetchone())[0]
    rows = await (await db.execute(
        f"SELECT id, kind, title, status, favorite, size_bytes, content_type FROM ms_library_items"
        f" WHERE {clause} ORDER BY title LIMIT ? OFFSET ?",
        (*args, limit, (page - 1) * limit),
    )).fetchall()
    return {"items": [_dto(r) for r in rows], "total": total, "page": page, "limit": limit}
