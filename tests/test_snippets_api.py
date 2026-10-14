"""P5-фоллоуап: таблица snippets должна существовать в init_db и работать через API.

Баг01.09: на живой БД GET /api/accounts/1/snippets падал
«no such table: snippets» — эндпоинты существовали, а CREATE TABLE в init_db
не было (тестами не покрывалось). """
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[1]


def _js_function(source: str, name: str) -> str:
    start = source.index(f"async function {name}(")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unterminated JavaScript function: {name}")


async def test_snippets_table_created_by_init_db(tmp_db):
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='snippets'"
        )
        assert await cursor.fetchone(), "init_db не создаёт таблицу snippets"
    finally:
        await db.close()


async def test_snippets_crud_roundtrip(tmp_db, disable_auth):
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, enabled) VALUES (1, 'snipbot', 'oauth:x', 1)"
        )
        await db.commit()
    finally:
        await db.close()
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/accounts/1/snippets")
        assert r.status_code == 200 and r.json() == []

        r = await client.post(
            "/api/accounts/1/snippets",
            json={"name": "привет", "text": "Привет, {{user}}!"},
        )
        assert r.status_code == 200 and r.json().get("ok") is True
        sid = r.json()["snippet_id"]

        r = await client.get("/api/accounts/1/snippets")
        assert r.status_code == 200 and len(r.json()) == 1
        assert r.json()[0]["name"] == "привет"

        r = await client.put(
            f"/api/accounts/1/snippets/{sid}",
            json={"name": "привет2", "text": "Йо"},
        )
        assert r.status_code == 200 and r.json().get("ok") is True

        r = await client.delete(f"/api/accounts/1/snippets/{sid}")
        assert r.status_code == 200 and r.json().get("ok") is True

        r = await client.get("/api/accounts/1/snippets")
        assert r.json() == []


async def test_snippet_mutations_reject_foreign_account(tmp_db, disable_auth):
    from app.database import init_db, get_db

    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, 'oauth:x', 1)",
            ((1, "owner"), (2, "foreign")),
        )
        cur = await db.execute(
            "INSERT INTO snippets (account_id, name, text) VALUES (1, 'owned', 'original')"
        )
        snippet_id = cur.lastrowid
        await db.commit()
    finally:
        await db.close()

    from fastapi import FastAPI
    from app.routes import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        update_result = await client.put(
            f"/api/accounts/2/snippets/{snippet_id}",
            json={"name": "stolen", "text": "changed"},
        )
        delete_result = await client.delete(
            f"/api/accounts/2/snippets/{snippet_id}"
        )
        legacy_unscoped_update = await client.put(
            f"/api/snippets/{snippet_id}",
            json={"name": "stolen", "text": "changed"},
        )
        legacy_unscoped_delete = await client.delete(f"/api/snippets/{snippet_id}")

    assert update_result.json() == {"ok": False}
    assert delete_result.json() == {"ok": False}
    assert legacy_unscoped_update.status_code == 422
    assert legacy_unscoped_delete.status_code == 422

    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT account_id, name, text FROM snippets WHERE id = ?",
                (snippet_id,),
            )
        ).fetchone()
    finally:
        await db.close()
    assert dict(row) == {"account_id": 1, "name": "owned", "text": "original"}


async def test_legacy_snippet_routes_require_matching_account_scope(tmp_db, disable_auth):
    from app.database import init_db, get_db

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, enabled) VALUES (1, 'owner', 'oauth:x', 1)"
        )
        cur = await db.execute(
            "INSERT INTO snippets (account_id, name, text) VALUES (1, 'owned', 'original')"
        )
        snippet_id = cur.lastrowid
        await db.commit()
    finally:
        await db.close()

    from fastapi import FastAPI
    from app.routes import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        foreign = await client.put(
            f"/api/snippets/{snippet_id}?account_id=2",
            json={"name": "foreign", "text": "blocked"},
        )
        owner = await client.put(
            f"/api/snippets/{snippet_id}?account_id=1",
            json={"name": "owner", "text": "updated"},
        )
        deleted = await client.delete(
            f"/api/snippets/{snippet_id}?account_id=1"
        )

    assert foreign.json() == {"ok": False}
    assert owner.json() == {"ok": True}
    assert deleted.json() == {"ok": True}


async def test_snippet_panel_mutations_send_current_account_scope():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")

    source = (ROOT / "static/app/05_bots_tabs.js").read_text(encoding="utf-8")
    functions = "\n".join(
        _js_function(source, name)
        for name in ("deleteSnippet", "bulkDeleteSnippets")
    )
    harness = f"""
const vm = require('vm');
const calls = [];
const context = {{
  api: async (url, options) => {{ calls.push([url, options]); return {{}}; }},
  confirm: () => true,
  loadBotSnippets: () => {{}},
  t: () => '',
  toast: () => {{}},
  _currentBotId: 2,
  _selectedSnippets: new Set([7, 8]),
}};
vm.createContext(context);
vm.runInContext({json.dumps(functions)}, context);
(async () => {{
  await context.deleteSnippet(7);
  await context.bulkDeleteSnippets();
  console.log(JSON.stringify(calls));
}})();
"""
    result = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    calls = json.loads(result.stdout)
    assert [call[0] for call in calls] == [
        "/api/accounts/2/snippets/7",
        "/api/accounts/2/snippets/7",
        "/api/accounts/2/snippets/8",
    ]
    assert all(call[1] == {"method": "DELETE"} for call in calls)


async def test_learning_mutations_reject_foreign_account(tmp_db, disable_auth):
    from app import learning
    from app.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.executemany(
            "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, 'oauth:x', 1)",
            ((1, "owner"), (2, "foreign")),
        )
        await db.commit()
    finally:
        await db.close()
    pending_id = await learning.add_suggestion(
        1, "c", "style_example", {"message": "owned"}
    )
    applied_id = await learning.add_suggestion(
        1, "c", "persona_delta", {"key": "mood", "value": "calm"}
    )
    assert await learning.apply_suggestion(1, applied_id)

    from fastapi import FastAPI
    from app.routes import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        apply_result = await client.post(
            f"/api/accounts/2/learning/{pending_id}/apply"
        )
        reject_result = await client.post(
            f"/api/accounts/2/learning/{pending_id}/reject"
        )
        revert_result = await client.post(
            f"/api/accounts/2/learning/{applied_id}/revert"
        )

    assert apply_result.json() == {"ok": False, "error": "not_found"}
    assert reject_result.json() == {"ok": False}
    assert revert_result.json() == {"ok": False}
    assert (await learning.get_suggestion(1, pending_id))["status"] == "pending"
    assert (await learning.get_suggestion(1, applied_id))["status"] == "applied"
