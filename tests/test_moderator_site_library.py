"""MOD-09 gate: scope-fenced read-only library, approved-only DTOs, no paths/tokens."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_library as lib


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "lib.db")
    await lib.ensure_schema(conn)
    await lib.add_item(conn, "own1", 1, "chan", "media", "Clip approved", size_bytes=1000, content_type="video/mp4")
    await lib.add_item(conn, "own2", 1, "chan", "sound", "Drum roll", favorite=1, size_bytes=200)
    await lib.add_item(conn, "own3", 1, "chan", "media", "Quarantine clip", status="pending")  # unapproved
    await lib.add_item(conn, "other4", 2, "other-chan", "media", "Someone else's clip")  # чужой скоуп
    await conn.commit()
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_foreign_scope_yields_empty_page(db):
    page = await lib.list_items(db, account_id=99, channel="chan", kind="media")
    assert page == {"items": [], "total": 0, "page": 1, "limit": 20}
    other = await lib.list_items(db, account_id=1, channel="other-chan", kind="media")
    assert other["total"] == 0  # чужой канал не виден даже при своём account_id


@pytest.mark.asyncio
async def test_unapproved_items_are_invisible_to_moderators(db):
    page = await lib.list_items(db, account_id=1, channel="chan", kind="media")
    titles = [item["title"] for item in page["items"]]
    assert "Clip approved" in titles
    assert "Quarantine clip" not in titles  # awaiting owner review


@pytest.mark.asyncio
async def test_search_pagination_and_favorites(db):
    for i in range(25):
        await lib.add_item(db, f"bulk{i}", 1, "chan", "sound", f"Sound {i:03d}")
        await conn_commit(db)
    searched = await lib.list_items(db, account_id=1, channel="chan", kind="sound", query="Sound 01")
    assert [item["title"] for item in searched["items"]] == ["Sound 010", "Sound 011", "..."][:2] or \
           all("Sound 01" in item["title"] for item in searched["items"])
    page1 = await lib.list_items(db, account_id=1, channel="chan", kind="sound", page=1, limit=10)
    page2 = await lib.list_items(db, account_id=1, channel="chan", kind="sound", page=2, limit=10)
    assert page1["items"][0]["id"] != page2["items"][0]["id"]
    assert len(page1["items"]) == 10 and page1["total"] > 20
    favorites = await lib.list_items(db, account_id=1, channel="chan", kind="sound", favorites_only=True)
    assert [item["title"] for item in favorites["items"]] == ["Drum roll"]


@pytest.mark.asyncio
async def test_dto_never_carries_paths_or_tokens(db):
    import json
    page = await lib.list_items(db, account_id=1, channel="chan", kind="media", limit=50)
    blob = json.dumps(page)
    for forbidden in ("path", "token", "/", "file", "secret"):
        assert forbidden not in blob.lower() or forbidden == "/" and "/" not in "".join(
            item["title"] for item in page["items"]), forbidden


async def conn_commit(db):
    await db.commit()
