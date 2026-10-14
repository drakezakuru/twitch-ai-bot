"""Q32 / OPTIONAL-10: export and import of the per-channel Director training base."""
import json
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import director_review, director_routes
from app.database import get_db, init_db


def example_payload():
    return {
        "context": {"chat": [{"author": "Viewer-1", "text": "Viewer-1 wins", "kind": "viewer"}],
                    "vision": "celebration", "speech": ""},
        "messages": [{"text": "Well done Viewer-1"}],
    }


async def seed_source_channel():
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_prompt_versions(id,channel,version,prompt_text,content_hash,replay_metadata_json,tested_at,activated_at) "
            "VALUES ('p1','source',1,'Keep reactions short',?, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (uuid.uuid4().hex,),
        )
        payload = example_payload()
        await db.execute(
            "INSERT INTO director_examples(id,channel,source_plan_id,payload_json,kind,payload_hash) "
            "VALUES ('e1','source','plan-1',?,'positive',?)",
            (json.dumps(payload, ensure_ascii=False), "hash-e1"),
        )
        await db.execute(
            "INSERT INTO director_chants(id,channel,text,source,approved_at) VALUES ('c1','source','Lets go','owner',CURRENT_TIMESTAMP)"
        )
        await db.execute(
            "INSERT INTO director_chants(id,channel,text,source,session_id) VALUES ('c2','source','session only','ai','s1')"
        )
        await db.execute(
            "INSERT INTO director_templates(id,channel,text,mode,source) VALUES ('t1','source','GG {player}','placeholders','owner')"
        )
        await db.commit()
    finally:
        await db.close()


def training_document():
    return {
        "kind": director_review.TRAINING_EXPORT_VERSION,
        "channel": "source",
        "prompts": ["Keep reactions short"],
        "examples": [{"kind": "positive", "payload": example_payload()}],
        "chants": ["Lets go"],
        "templates": [{"text": "GG {player}", "mode": "placeholders"}],
    }


@pytest_asyncio.fixture
async def client(disable_auth):
    app = FastAPI()
    app.include_router(director_routes.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


async def target_counts():
    db = await get_db()
    try:
        result = {}
        for table in ("director_prompt_versions", "director_examples", "director_chants", "director_templates"):
            result[table] = (
                await (await db.execute(f"SELECT count(*) FROM {table} WHERE channel='target'")).fetchone()
            )[0]
        return result
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_export_import_roundtrip_to_another_channel():
    await seed_source_channel()
    document = await director_review.export_training("source")
    assert document["kind"] == director_review.TRAINING_EXPORT_VERSION
    # Server-owned replay state is never exported.
    assert document["prompts"] == ["Keep reactions short"]
    assert len(document["examples"]) == 1 and document["examples"][0]["kind"] == "positive"
    assert document["chants"] == ["Lets go"]  # session-scoped AI chants stay local
    assert document["templates"] == [{"text": "GG {player}", "mode": "placeholders"}]

    result = await director_review.import_training("target", document, confirm=True)
    assert result["ok"] and (result["prompts"], result["examples"], result["chants"], result["templates"]) == (1, 1, 1, 1)
    counts = await target_counts()
    assert counts == {
        "director_prompt_versions": 1,
        "director_examples": 1,
        "director_chants": 1,
        "director_templates": 1,
    }
    db = await get_db()
    try:
        prompt = await (
            await db.execute("SELECT version, tested_at, activated_at, replay_metadata_json FROM director_prompt_versions WHERE channel='target'")
        ).fetchone()
        assert prompt[0] == 1 and prompt[1] is None and prompt[2] is None and prompt[3] == "{}"
        example = await (
            await db.execute("SELECT payload_json, kind FROM director_examples WHERE channel='target'")
        ).fetchone()
        assert json.loads(example[0]) == example_payload() and example[1] == "positive"
        chant = await (await db.execute("SELECT source FROM director_chants WHERE channel='target'")).fetchone()
        assert chant[0] == "owner"
    finally:
        await db.close()

    # Idempotent re-import: duplicates are skipped without replace.
    repeat = await director_review.import_training("target", document, confirm=True)
    assert (repeat["prompts"], repeat["examples"], repeat["chants"], repeat["templates"]) == (0, 0, 0, 0)
    assert sum((await target_counts()).values()) == 4

    # Confirmation is mandatory; malformed and unsafe documents are refused.
    with pytest.raises(ValueError, match="import_confirmation_required"):
        await director_review.import_training("target", document)
    for bad in (
        {**document, "kind": "other/v1"},
        {**document, "examples": [{"kind": "positive", "payload": {"messages": [{"text": "!command"}]}}]},
        {**document, "chants": ["https://example.invalid"]},
        {**document, "templates": [{"text": "x", "mode": "weird"}]},
    ):
        with pytest.raises(ValueError, match="invalid_training_export"):
            await director_review.import_training("target", bad, confirm=True)
    assert sum((await target_counts()).values()) == 4


@pytest.mark.asyncio
async def test_import_replace_wipes_channel_rows_and_files_and_locks_during_session():
    await seed_source_channel()
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_prompt_versions(id,channel,version,prompt_text,content_hash) VALUES ('p9','target',1,'Old prompt',?)",
            (uuid.uuid4().hex,),
        )
        await db.execute(
            "INSERT INTO director_chants(id,channel,text,source,approved_at) VALUES ('c9','target','Old chant','owner',CURRENT_TIMESTAMP)"
        )
        await db.execute(
            "INSERT INTO director_examples(id,channel,source_plan_id,payload_json,kind) VALUES ('e9','target','plan-9','{}','negative')"
        )
        from app.director_review import example_dir

        frame = example_dir("e9") / "frames" / "shot.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"png")
        await db.execute(
            "INSERT INTO director_example_files(example_id,channel,kind,path,size_bytes) VALUES ('e9','target','frame','frames/shot.png',3)"
        )
        await db.commit()
    finally:
        await db.close()
    document = training_document()
    result = await director_review.import_training("target", document, replace=True, confirm=True)
    assert (result["prompts"], result["examples"], result["chants"], result["templates"]) == (1, 1, 1, 1)
    counts = await target_counts()
    assert counts["director_prompt_versions"] == 1 and counts["director_examples"] == 1
    db = await get_db()
    try:
        text = await (
            await db.execute("SELECT prompt_text FROM director_prompt_versions WHERE channel='target'")
        ).fetchone()
        assert text[0] == "Keep reactions short"
        chant = await (await db.execute("SELECT text FROM director_chants WHERE channel='target'")).fetchone()
        assert chant[0] == "Lets go"
        leftover_files = await (await db.execute("SELECT count(*) FROM director_example_files")).fetchone()
        assert leftover_files[0] == 0
    finally:
        await db.close()
    from app.director_review import example_dir

    assert not (example_dir("e9") / "frames" / "shot.png").exists()

    # A running session locks the training base.
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_sessions(id,channel,state,config_version) VALUES ('s9','target','live',1)"
        )
        await db.commit()
    finally:
        await db.close()
    with pytest.raises(ValueError, match="settings_locked"):
        await director_review.import_training("target", document, replace=True, confirm=True)


@pytest.mark.asyncio
async def test_training_routes_export_and_import(client):
    await seed_source_channel()
    document = training_document()
    exported = await client.get("/api/director/source/training/export")
    assert exported.status_code == 200 and exported.json()["kind"] == director_review.TRAINING_EXPORT_VERSION
    unconfirmed = await client.post(
        "/api/director/target/training/import",
        json={"data": document, "replace": False, "confirm": False},
    )
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["detail"]["code"] == "import_confirmation_required"
    imported = await client.post(
        "/api/director/target/training/import",
        json={"data": document, "replace": False, "confirm": True},
    )
    assert imported.status_code == 200 and imported.json()["examples"] == 1
    bad = await client.post(
        "/api/director/target/training/import",
        json={"data": {"kind": "nope"}, "confirm": True},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "invalid_training_export"
