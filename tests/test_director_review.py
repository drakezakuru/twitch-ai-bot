import asyncio
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


def response_for(snapshot, *, text="Nice play", count=1):
    constraints = snapshot["plan_constraints"]
    group_id = str(uuid4())
    return json.dumps(
        {
            "schema_version": "director-plan/v1",
            "plan_id": str(uuid4()),
            **snapshot["scope"],
            "explanation": "A visible moment",
            "reaction_level": "small",
            "reaction_percentage": 5,
            "reaction_count": count,
            "assignment_mode": constraints["assignment_mode"],
            "groups": [
                {
                    "group_id": group_id,
                    "text": text,
                    "percentage": 100,
                    "delay_seconds": constraints["delay_window_seconds"]["min"],
                }
            ],
            "individual_messages": [
                {
                    "message_id": str(uuid4()),
                    "group_id": group_id,
                    "bot_id": "1",
                    "text": text,
                    "delay_seconds": constraints["delay_window_seconds"]["min"],
                }
            ]
            if constraints["assignment_mode"] == "ai_assigned"
            else [],
            "delay_window_seconds": constraints["delay_window_seconds"],
            "ttl_seconds": constraints["ttl_seconds"],
            "template_ids": [],
            "example_ids": [],
        }
    )


class FakeAI:
    SUPPORTED_PROVIDERS = (
        "ollama",
        "openai",
        "openrouter",
        "gemini",
        "anthropic",
        "custom",
    )
    ollama_host = "http://unused.invalid"
    openrouter_key = gemini_key = openai_key = anthropic_key = custom_base_url = (
        "configured"
    )

    def __init__(self):
        self.calls = []
        self.transform = None
        self.entered = None
        self.release = None

    def get_custom_provider(self, name):
        return {"models": ["chosen-model"]} if name == "named" else None

    async def generate_text_with(self, provider, model, prompt, system, **kwargs):
        snapshot = json.loads(prompt)
        self.calls.append((provider, model, snapshot, system, kwargs))
        if self.entered:
            self.entered.set()
            await self.release.wait()
        result = {"ok": True, "response": response_for(snapshot)}
        return self.transform(result, snapshot) if self.transform else result


async def prepare(monkeypatch, *, mode="live", provider="ollama"):
    await init_db()
    db = await get_db()
    try:
        for account_id, role in ((1, "lurker"), (2, "director")):
            await db.execute(
                "INSERT INTO accounts(id,nickname,token,enabled,bot_role) VALUES (?,?, 'x',1,?)",
                (account_id, role, role),
            )
            await db.execute(
                "INSERT INTO channels(account_id,channel_name,enabled) VALUES (?,'channel',1)",
                (account_id,),
            )
        await db.commit()
    finally:
        await db.close()
    await director.save_config(
        "channel", {"provider": provider, "model": "chosen-model", "mode": mode}, [1], 2
    )
    fake = FakeAI()
    bots = SimpleNamespace(
        get_status=lambda _: {"connected": True}, get_all_statuses=lambda: {}
    )
    adapter = director.ProductionDirectorAdapter(fake, SimpleNamespace(), bots)
    monkeypatch.setattr(director, "_production_adapter", adapter)
    prompt = await director.create_prompt_version(
        "channel", "Keep reactions short; this is an owner preference."
    )
    return fake, adapter, prompt["id"]


@pytest_asyncio.fixture
async def client(disable_auth):
    app = FastAPI()
    app.include_router(director_routes.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["ollama", "openai", "custom:named"])
async def test_server_replay_exact_provider_and_quality_gate(
    monkeypatch, client, provider
):
    fake, _adapter, prompt_id = await prepare(monkeypatch, provider=provider)
    base = f"/api/director/channel/prompts/{prompt_id}"
    assert (
        await client.post(base + "/activate", json={"quality_confirmed": True})
    ).status_code == 400
    forged = await client.post(
        base + "/tested", json={"replay_metadata": {"passed": True}}
    )
    assert forged.status_code == 400
    assert not fake.calls
    result = await client.post(base + "/tested", json={})
    assert result.status_code == 200
    prompt = result.json()["prompts"][0]
    assert prompt["tested"] and not prompt["active"]
    assert len(fake.calls) == len(director_review.REPLAY_CASES)
    assert all(call[:2] == (provider, "chosen-model") for call in fake.calls)
    assert all(
        call[2]["synthetic"] and "owner_preferences" in call[2] for call in fake.calls
    )
    assert "Keep reactions" not in fake.calls[0][3]
    assert all(
        case["passed"] and case["response"]
        for case in prompt["replay_metadata"]["cases"]
    )
    for value in (False, "true", 1):
        assert (
            await client.post(base + "/activate", json={"quality_confirmed": value})
        ).status_code == 400
    activated = await client.post(
        base + "/activate",
        json={
            "quality_confirmed": True,
            "replay_run_id": prompt["replay_metadata"]["run_id"],
        },
    )
    assert activated.json()["prompts"][0]["active"]
    assert (await director.list_audit("other"))["entries"] == []
    loaded = await director._config("channel")
    assert await director_review.active_prompt("channel", loaded[0], loaded[2])
    db = await get_db()
    try:
        for table in (
            "director_sessions",
            "director_plans",
            "director_messages",
            "director_jobs",
        ):
            assert (
                await (await db.execute(f"SELECT count(*) FROM {table}")).fetchone()
            )[0] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["not JSON", "url", "unsafe_zero", "scope", "schema", "provider_error"]
)
async def test_replay_failure_never_authorizes_prompt(monkeypatch, bad):
    fake, _adapter, prompt_id = await prepare(monkeypatch)

    def transform(result, snapshot):
        if bad == "provider_error":
            return {
                "ok": False,
                "response": "",
                "error": "SECRET must never reach the client",
            }
        if bad == "not JSON":
            result["response"] = "not JSON"
        elif bad in {"url", "unsafe_zero"}:
            result["response"] = response_for(
                snapshot,
                text="https://example.invalid",
                count=0 if bad == "unsafe_zero" else 1,
            )
        else:
            plan = json.loads(result["response"])
            plan["channel_id" if bad == "scope" else "schema_version"] = "wrong"
            result["response"] = json.dumps(plan)
        return result

    fake.transform = transform
    result = await director.set_prompt_tested("channel", prompt_id)
    assert not result["prompts"][0]["tested"]
    assert "SECRET" not in json.dumps(result)
    with pytest.raises(ValueError, match="prompt_not_tested"):
        await director.activate_prompt_version(
            "channel", prompt_id, quality_confirmed=True
        )


@pytest.mark.asyncio
async def test_prompt_proof_invalidated_by_config_change_and_legacy_metadata(
    monkeypatch,
):
    _fake, _adapter, prompt_id = await prepare(monkeypatch)
    with pytest.raises(ValueError, match="server_owned"):
        await director.create_prompt_version(
            "channel", "x", replay_metadata={"passed": True}
        )
    replay = await director.set_prompt_tested("channel", prompt_id)
    await director.activate_prompt_version(
        "channel",
        prompt_id,
        quality_confirmed=True,
        replay_run_id=replay["prompts"][0]["replay_metadata"]["run_id"],
    )
    config = (await director._config("channel"))[0]
    await director.save_config(
        "channel", {**config, "model": "different-model"}, [1], 2
    )
    assert not (await director.list_prompt_versions("channel"))["prompts"][0]["tested"]
    with pytest.raises(ValueError, match="prompt_replay_stale"):
        await director.activate_prompt_version(
            "channel", prompt_id, quality_confirmed=True
        )
    loaded = await director._config("channel")
    with pytest.raises(ValueError, match="director_prompt_not_ready"):
        await director_review.active_prompt("channel", loaded[0], loaded[2])
    db = await get_db()
    try:
        await db.execute(
            "UPDATE director_prompt_versions SET tested_at=CURRENT_TIMESTAMP,activated_at=CURRENT_TIMESTAMP,replay_metadata_json='{}'"
        )
        await db.commit()
    finally:
        await db.close()
    with pytest.raises(ValueError, match="director_prompt_not_ready"):
        await director_review.active_prompt("channel", loaded[0], loaded[2])


@pytest.mark.asyncio
async def test_replay_claim_blocks_duplicates_and_stale_completion(monkeypatch):
    fake, _adapter, prompt_id = await prepare(monkeypatch)
    fake.entered, fake.release = asyncio.Event(), asyncio.Event()
    pending = asyncio.create_task(director.set_prompt_tested("channel", prompt_id))
    await fake.entered.wait()
    with pytest.raises(ValueError, match="replay_in_progress"):
        await director.set_prompt_tested("channel", prompt_id)
    config = (await director._config("channel"))[0]
    await director.save_config("channel", {**config, "model": "new-model"}, [1], 2)
    fake.release.set()
    with pytest.raises(ValueError, match="replay_config_changed"):
        await pending
    assert not (await director.list_prompt_versions("channel"))["prompts"][0]["tested"]


@pytest.mark.asyncio
async def test_cancelled_replay_releases_claim(monkeypatch):
    fake, _adapter, prompt_id = await prepare(monkeypatch)
    fake.entered, fake.release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(director.set_prompt_tested("channel", prompt_id))
    await fake.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    fake.release.set()
    result = await director.set_prompt_tested("channel", prompt_id)
    assert result["prompts"][0]["tested"]


@pytest.mark.asyncio
async def test_prompt_mutations_locked_during_running_session(monkeypatch):
    _fake, _adapter, prompt_id = await prepare(monkeypatch)
    await director.set_prompt_tested("channel", prompt_id)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_sessions(id,channel,state,config_version) VALUES ('session','channel','live',1)"
        )
        await db.commit()
    finally:
        await db.close()
    for operation in (
        lambda: director.create_prompt_version("channel", "new"),
        lambda: director.set_prompt_tested("channel", prompt_id),
        lambda: director.activate_prompt_version(
            "channel", prompt_id, quality_confirmed=True
        ),
    ):
        with pytest.raises(ValueError, match="settings_locked"):
            await operation()


async def make_suggestion(monkeypatch):
    fake, adapter, _prompt_id = await prepare(monkeypatch, mode="suggest")
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_sessions(id,channel,state,config_version) VALUES ('session','channel','suggest',1)"
        )
        await db.commit()
    finally:
        await db.close()
    config = (await director._config("channel"))[0]
    snapshot = director_review._replay_snapshot(
        "channel", "x", "moment", "test", config
    )
    snapshot["scope"]["session_id"] = "session"
    sent = []

    async def sender(*args):
        sent.append(args)
        return {"ok": True}

    runtime = director.DirectorScheduler(
        sender=sender, worker_status=lambda _: {"connected": True}
    )
    plan_id = await runtime.submit_response(
        "channel",
        response_for(snapshot),
        source_snapshot_id="moment",
        source_context={
            "chat": [
                {"author": "RealViewer", "text": "RealViewer wins", "kind": "viewer"}
            ],
            "vision": "RealViewer celebrates",
            "speech": "Nice, RealViewer",
        },
    )
    return fake, adapter, runtime, sent, plan_id


@pytest.mark.asyncio
async def test_suggest_review_is_scoped_durable_idempotent_and_never_sends(
    monkeypatch, client
):
    _fake, _adapter, runtime, sent, plan_id = await make_suggestion(monkeypatch)
    assert (await client.get("/api/director/other/suggestions")).json()[
        "suggestions"
    ] == []
    assert (
        await client.post(f"/api/director/other/suggestions/{plan_id}/approve", json={})
    ).status_code == 400
    url = f"/api/director/channel/suggestions/{plan_id}/approve"
    approved = await client.post(
        url, json={"messages": [{"text": "Well done RealViewer"}]}
    )
    assert approved.status_code == 200
    assert (
        await client.post(url, json={"messages": [{"text": "Well done RealViewer"}]})
    ).json() == approved.json()
    assert (
        await client.post(url, json={"messages": [{"text": "Changed"}]})
    ).status_code == 400
    assert (
        await client.post(
            f"/api/director/channel/suggestions/{plan_id}/reject", json={}
        )
    ).status_code == 400
    examples = (await client.get("/api/director/channel/examples")).json()["examples"]
    assert (
        len(examples) == 1
        and examples[0]["messages"][0]["text"] == "Well done Viewer-1"
    )
    assert "RealViewer" not in json.dumps(examples)
    assert (await client.get("/api/director/other/examples")).json()["examples"] == []
    await director.delete_session_evidence("channel", "session", "УДАЛИТЬ")
    await director.recover_after_restart()
    await runtime._dispatch_due(time.monotonic() + 100)
    assert len((await director_review.list_examples("channel"))["examples"]) == 1
    assert not sent
    db = await get_db()
    try:
        assert (
            await (
                await db.execute("SELECT count(*) FROM director_messages")
            ).fetchone()
        )[0] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_suggest_reject_and_unsafe_or_over_quota_approval(monkeypatch):
    _fake, _adapter, _runtime, _sent, plan_id = await make_suggestion(monkeypatch)
    for messages in (
        [],
        [{"text": "!command"}],
        [{"text": "https://example.invalid"}],
        [{"text": "@someone"}],
        [{"text": "password=example"}],
        [{"text": "x"}, {"text": "y"}],
    ):
        with pytest.raises(ValueError):
            await director_review.review_suggestion(
                "channel", plan_id, "approved", messages
            )
    monkeypatch.setattr(director_review, "EXAMPLE_LIMIT_BYTES", 1)
    with pytest.raises(ValueError, match="example_storage_full"):
        await director_review.review_suggestion("channel", plan_id, "approved")
    await director_review.review_suggestion("channel", plan_id, "rejected")
    await director_review.review_suggestion("channel", plan_id, "rejected")
    assert (await director_review.list_suggestions("channel"))["suggestions"][0][
        "decision"
    ] == "rejected"
    # DIR-LIVE-04: a rejected plan is stored as a masked negative example, never sendable.
    negatives = (await director_review.list_examples("channel"))["examples"]
    assert len(negatives) == 1 and negatives[0]["kind"] == "negative"
    assert "RealViewer" not in json.dumps(negatives)
    assert (await director_review.list_examples("channel", kind="positive"))["examples"] == []


@pytest.mark.asyncio
async def test_approved_examples_enter_production_context_not_twitch(monkeypatch):
    fake, adapter, _runtime, sent, plan_id = await make_suggestion(monkeypatch)
    await director_review.review_suggestion("channel", plan_id, "approved")

    async def active(*_):
        return "Short reactions"

    async def snapshot(*_, **__):
        return {"chat": [], "vision": "", "speech": ""}

    monkeypatch.setattr(director_review, "active_prompt", active)
    monkeypatch.setattr(adapter, "snapshot", snapshot)
    request = {"channel": "channel", "source_snapshot_id": "fresh"}
    await adapter.plan(request)
    assert len(fake.calls[0][2]["approved_examples"]) == 1
    assert "RealViewer" not in json.dumps(fake.calls[0][2]["approved_examples"])
    assert request["context"]["chat"] == [] and request["context"]["vision"] == "" and request["context"]["speech"] == ""
    assert request["context"]["builtin_moments"]["version"] == director_review.BUILTIN_MOMENTS_VERSION
    assert "events" in request["context"] and "stream" in request["context"]
    assert not sent


@pytest.mark.asyncio
async def test_state_mode_mismatch_does_not_queue_suggest_as_live(monkeypatch):
    _fake, _adapter, runtime, sent, _plan_id = await make_suggestion(monkeypatch)
    config = (await director._config("channel"))[0]
    db = await get_db()
    try:
        await db.execute(
            "UPDATE director_configs SET config_json=? WHERE channel='channel'",
            (json.dumps({**config, "mode": "live"}),),
        )
        await db.commit()
    finally:
        await db.close()
    snapshot = director_review._replay_snapshot(
        "channel", "x", "moment", "test", config
    )
    snapshot["scope"]["session_id"] = "session"
    with pytest.raises(ValueError, match="session_not_executable"):
        await runtime.submit_response(
            "channel", response_for(snapshot), source_snapshot_id="moment"
        )
    assert not sent
