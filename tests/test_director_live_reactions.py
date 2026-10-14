"""Q30 / CAND-01: review of really sent live reactions (approve → positive example, reject → negative)."""
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import director, director_review, director_routes
from app.database import get_db, init_db

from tests.test_director_review import FakeAI, response_for


def response_two_texts(snapshot):
    """A two-group live plan; identical texts would be rejected as duplicates."""
    constraints = snapshot["plan_constraints"]
    return json.dumps(
        {
            "schema_version": "director-plan/v1",
            "plan_id": str(uuid4()),
            **snapshot["scope"],
            "explanation": "A visible moment",
            "reaction_level": "small",
            "reaction_percentage": 5,
            "reaction_count": 2,
            "assignment_mode": constraints["assignment_mode"],
            "groups": [
                {
                    "group_id": str(uuid4()),
                    "text": "Great win",
                    "percentage": 50,
                    "delay_seconds": constraints["delay_window_seconds"]["min"],
                },
                {
                    "group_id": str(uuid4()),
                    "text": "Well played",
                    "percentage": 50,
                    "delay_seconds": constraints["delay_window_seconds"]["min"],
                },
            ],
            "individual_messages": [],
            "delay_window_seconds": constraints["delay_window_seconds"],
            "ttl_seconds": constraints["ttl_seconds"],
            "template_ids": [],
            "example_ids": [],
        }
    )


async def prepare(monkeypatch):
    await init_db()
    db = await get_db()
    try:
        for account_id, nickname, role in ((1, "lurker", "lurker"), (2, "director", "director"), (3, "lurker2", "lurker")):
            await db.execute(
                "INSERT INTO accounts(id,nickname,token,enabled,bot_role) VALUES (?,?, 'x',1,?)",
                (account_id, nickname, role),
            )
            await db.execute(
                "INSERT INTO channels(account_id,channel_name,enabled) VALUES (?,'channel',1)",
                (account_id,),
            )
        await db.commit()
    finally:
        await db.close()
    await director.save_config(
        "channel", {"provider": "ollama", "model": "chosen-model", "mode": "live"}, [1, 3], 2
    )
    fake = FakeAI()
    bots = SimpleNamespace(
        get_status=lambda _: {"connected": True}, get_all_statuses=lambda: {}
    )
    adapter = director.ProductionDirectorAdapter(fake, SimpleNamespace(), bots)
    monkeypatch.setattr(director, "_production_adapter", adapter)
    return fake, adapter


async def _sender(*args):
    return {"ok": True}


async def make_live_plan():
    """A live plan with two sent messages, one pending and one cancelled dispatch."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_sessions(id,channel,state,config_version) VALUES ('session','channel','live',1)"
        )
        await db.commit()
    finally:
        await db.close()
    config = (await director._config("channel"))[0]
    snapshot = director_review._replay_snapshot("channel", "x", "moment", "test", config)
    snapshot["scope"]["session_id"] = "session"
    runtime = director.DirectorScheduler(sender=_sender, worker_status=lambda _: {"connected": True})
    plan_id = await runtime.submit_response(
        "channel",
        response_two_texts(snapshot),
        source_snapshot_id="moment",
        source_context={
            "chat": [
                {"author": "RealViewer", "text": "RealViewer wins", "kind": "viewer"}
            ],
            "vision": "RealViewer celebrates",
            "speech": "Nice, RealViewer",
        },
    )
    db = await get_db()
    try:
        rows = await (
            await db.execute(
                "SELECT id FROM director_messages WHERE plan_id=? ORDER BY id", (plan_id,)
            )
        ).fetchall()
        assert len(rows) == 2
        first, second = (row[0] for row in rows)
        now = time.time()
        await db.execute(
            "UPDATE director_messages SET state='sent', sent_at=? WHERE id=?", (now, first)
        )
        await db.execute(
            "UPDATE director_messages SET state='sent', sent_at=? WHERE id=?", (now + 1, second)
        )
        await db.executemany(
            "INSERT INTO director_messages(id,plan_id,session_id,account_id,text,due_at,expires_at,state,sent_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                (f"{plan_id}-pending", plan_id, "session", 1, "sent one", now + 999, now + 1000, "pending", None),
                (f"{plan_id}-cancelled", plan_id, "session", 3, "sent two", now + 999, now + 1000, "cancelled", None),
            ),
        )
        await db.commit()
    finally:
        await db.close()
    return plan_id, [first, second]


@pytest_asyncio.fixture
async def client(disable_auth):
    app = FastAPI()
    app.include_router(director_routes.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_live_approve_roundtrip_sent_only_and_idempotent(monkeypatch, client):
    _fake, _adapter = await prepare(monkeypatch)
    plan_id, _sent_ids = await make_live_plan()
    other = (await client.get("/api/director/other/reactions/live")).json()
    assert other["reactions"] == []
    listed = (await client.get("/api/director/channel/reactions/live")).json()[
        "reactions"
    ]
    assert [item["id"] for item in listed] == [plan_id]
    assert listed[0]["decision"] is None
    # Only really dispatched messages are visible; pending/cancelled stay hidden.
    assert len(listed[0]["messages"]) == 2
    assert all(message["sent_at"] for message in listed[0]["messages"])

    url = f"/api/director/channel/reactions/live/{plan_id}/approve"
    assert (
        await client.post(url, json={"texts": ["Different"]})
    ).status_code == 400
    approved = await client.post(url, json={})
    assert approved.status_code == 200
    example_id = approved.json()["example_id"]
    repeat = await client.post(url, json={})
    assert repeat.status_code == 200 and repeat.json()["example_id"] == example_id
    assert (
        await client.post(f"/api/director/channel/reactions/live/{plan_id}/reject", json={})
    ).status_code == 400

    examples = (await client.get("/api/director/channel/examples")).json()["examples"]
    assert len(examples) == 1 and examples[0]["kind"] == "positive"
    assert sorted(item["text"] for item in examples[0]["messages"]) == sorted(
        item["text"] for item in listed[0]["messages"]
    )
    dumped = json.dumps(examples)
    assert "RealViewer" not in dumped  # context is anonymized
    assert "Viewer-1" in dumped
    decisions = (
        await client.get("/api/director/channel/reactions/live")
    ).json()["reactions"][0]["decision"]
    assert decisions == "approved"
    db = await get_db()
    try:
        review = await (
            await db.execute(
                "SELECT decision FROM director_suggestion_reviews WHERE channel='channel' AND plan_id=?",
                (plan_id,),
            )
        ).fetchone()
        assert review[0] == "approved"
        audit = (await director.list_audit("channel"))["entries"]
        assert any(
            entry["action"] == "live_reaction_reviewed" and entry["result"] == "approved"
            for entry in audit
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_live_reject_roundtrip_and_not_sent_guard(monkeypatch, client):
    _fake, _adapter = await prepare(monkeypatch)
    plan_id, _sent_ids = await make_live_plan()
    url = f"/api/director/channel/reactions/live/{plan_id}/reject"
    rejected = await client.post(url, json={})
    assert rejected.status_code == 200
    repeat = await client.post(url, json={})
    assert repeat.status_code == 200 and (
        repeat.json()["example_id"] == rejected.json()["example_id"]
    )
    assert (
        await client.post(f"/api/director/channel/reactions/live/{plan_id}/approve", json={})
    ).status_code == 400
    examples = (await client.get("/api/director/channel/examples")).json()["examples"]
    assert len(examples) == 1 and examples[0]["kind"] == "negative"
    assert "RealViewer" not in json.dumps(examples)
    # A negative example must never be sent: only positive ones enter production context.
    assert (
        await client.get("/api/director/channel/examples?kind=positive")
    ).json()["examples"] == []

    # A live plan without any sent message cannot be reviewed.
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_plans(id,session_id,channel,source_snapshot_id,mode,status,payload_json,created_at) "
            "VALUES ('plan-unsent','session','channel','moment','live','valid','{}',?)",
            (time.time(),),
        )
        await db.commit()
    finally:
        await db.close()
    listed = (await client.get("/api/director/channel/reactions/live")).json()[
        "reactions"
    ]
    assert [item["id"] for item in listed] == [plan_id]
    with pytest.raises(ValueError, match="reaction_not_sent"):
        await director_review.review_live_reaction("channel", "plan-unsent", "approved")
    assert (
        await client.post(
            "/api/director/channel/reactions/live/plan-unsent/approve", json={}
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/director/channel/reactions/live/missing/reject", json={}
        )
    ).status_code == 400


@pytest.mark.asyncio
async def test_suggest_plans_never_appear_in_live_reactions(monkeypatch, client):
    _fake, _adapter = await prepare(monkeypatch)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_sessions(id,channel,state,config_version) VALUES ('session','channel','suggest',1)"
        )
        await db.execute(
            "INSERT INTO director_plans(id,session_id,channel,source_snapshot_id,mode,status,payload_json,created_at) "
            "VALUES ('plan-suggest','session','channel','moment','suggest','valid','{}',?)",
            (time.time(),),
        )
        await db.execute(
            "INSERT INTO director_messages(id,plan_id,session_id,account_id,text,due_at,expires_at,state,sent_at) "
            "VALUES ('msg-suggest','plan-suggest','session',1,'hello',?,?, 'sent', ?)",
            (time.time() + 5, time.time() + 60, time.time()),
        )
        await db.commit()
    finally:
        await db.close()
    assert (
        await client.get("/api/director/channel/reactions/live")
    ).json()["reactions"] == []
