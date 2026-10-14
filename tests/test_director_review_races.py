import asyncio
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from app import director, director_review
from app.database import get_db
from tests.test_director_review import prepare, response_for, make_suggestion


async def activate_reviewed(prompt_id):
    report = await director.set_prompt_tested("channel", prompt_id)
    run_id = report["prompts"][0]["replay_metadata"]["run_id"]
    await director.activate_prompt_version(
        "channel", prompt_id, quality_confirmed=True, replay_run_id=run_id
    )
    return run_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "individual",
    [
        [{"text": "Nice play", "unexpected": "schema violation"}],
        [
            {
                "message_id": "not-uuid",
                "group_id": "not-uuid",
                "bot_id": "1",
                "text": "Nice play",
                "delay_seconds": 1,
            }
        ],
    ],
)
async def test_replay_validates_unused_schema_fields(monkeypatch, individual):
    fake, _, prompt_id = await prepare(monkeypatch)

    def transform(result, _snapshot):
        plan = json.loads(result["response"])
        plan["individual_messages"] = individual
        result["response"] = json.dumps(plan)
        return result

    fake.transform = transform
    result = await director.set_prompt_tested("channel", prompt_id)
    prompt = result["prompts"][0]
    assert not prompt["tested"]
    assert all(
        case["reason"] == "schema_mismatch"
        for case in prompt["replay_metadata"]["cases"]
    )


@pytest.mark.asyncio
async def test_resume_serializes_against_replay_invalidation(monkeypatch):
    fake, _, prompt_id = await prepare(monkeypatch)
    await activate_reviewed(prompt_id)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO director_sessions(id,channel,state,config_version) VALUES ('session','channel','paused',1)"
        )
        await db.commit()
    finally:
        await db.close()
    checked, finish_resume = asyncio.Event(), asyncio.Event()
    original = director_review.active_prompt

    async def delayed_active(*args):
        result = await original(*args)
        checked.set()
        await finish_resume.wait()
        return result

    monkeypatch.setattr(director_review, "active_prompt", delayed_active)
    monkeypatch.setattr(director.health, "stable", lambda *_, **__: True)
    resuming = asyncio.create_task(director.transition("channel", "resume"))
    await checked.wait()
    replaying = asyncio.create_task(director.set_prompt_tested("channel", prompt_id))
    await asyncio.sleep(0.03)
    assert not replaying.done()
    finish_resume.set()
    assert (await resuming)["session"]["state"] == "warming"
    with pytest.raises(ValueError, match="settings_locked"):
        await replaying
    loaded = await director._config("channel")
    assert await original("channel", loaded[0], loaded[2])
    assert len(fake.calls) == len(director_review.REPLAY_CASES)


@pytest.mark.asyncio
async def test_director_revocation_shares_bulk_delete_transaction(monkeypatch):
    await prepare(monkeypatch)
    from app import routes

    async def stop_bot(_):
        pass

    async def log(*_):
        pass

    monkeypatch.setitem(
        sys.modules,
        "app.server",
        SimpleNamespace(bot_manager=SimpleNamespace(stop_bot=stop_bot)),
    )
    monkeypatch.setattr(routes, "log_action", log)
    result = await routes.bulk_delete({"type": "accounts", "ids": [1, 2]})
    assert result == {"ok": True, "deleted": 2}
    db = await get_db()
    try:
        assert not await (await db.execute("SELECT id FROM accounts")).fetchall()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_username_case_variants_are_masked_in_examples(monkeypatch):
    _, _, _, _, plan_id = await make_suggestion(monkeypatch)
    await director_review.review_suggestion(
        "channel", plan_id, "approved", [{"text": "Well done REALVIEWER"}]
    )
    example = (await director_review.list_examples("channel"))["examples"][0]
    assert example["context"]["chat"][0]["author"] == "Viewer-1"
    assert example["messages"][0]["text"] == "Well done Viewer-1"
    assert "realviewer" not in json.dumps(example).casefold()


@pytest.mark.asyncio
@pytest.mark.parametrize("during_replay", [False, True])
async def test_provider_endpoint_change_invalidates_replay_proof(
    monkeypatch, during_replay
):
    from app.ai_service import AIService

    _, adapter, prompt_id = await prepare(monkeypatch, provider="custom:named")
    ai = AIService()
    await ai._client.aclose()

    def provider(host):
        return [
            {
                "name": "named",
                "base_url": f"http://{host}/v1",
                "api_key": "",
                "models": ["chosen-model"],
                "enabled": 1,
            }
        ]

    ai.set_custom_providers(provider("before.invalid"))
    calls = []

    def handle(request):
        calls.append(request.url.host)
        snapshot = json.loads(json.loads(request.content)["messages"][-1]["content"])
        if during_replay:
            ai.set_custom_providers(provider("after.invalid"))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": response_for(snapshot)}}]}
        )

    ai._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter.ai_service = ai
    try:
        if during_replay:
            with pytest.raises(ValueError, match="replay_config_changed"):
                await director.set_prompt_tested("channel", prompt_id)
            assert calls == ["before.invalid"]
        else:
            run_id = await activate_reviewed(prompt_id)
            assert calls == ["before.invalid"] * len(director_review.REPLAY_CASES)
            ai.set_custom_providers(provider("after.invalid"))
            with pytest.raises(ValueError, match="prompt_replay_stale"):
                await director.activate_prompt_version(
                    "channel", prompt_id, quality_confirmed=True, replay_run_id=run_id
                )
        config, _, version, _ = await director._config("channel")
        with pytest.raises(ValueError, match="director_prompt_not_ready"):
            await director_review.active_prompt("channel", config, version)
        assert not (await director.list_prompt_versions("channel"))["prompts"][0][
            "active"
        ]
    finally:
        await ai.close()


@pytest.mark.asyncio
async def test_quality_confirmation_is_bound_to_the_report_reviewed(monkeypatch):
    _, _, prompt_id = await prepare(monkeypatch)
    original_run = await activate_reviewed(prompt_id)
    new = await director.set_prompt_tested("channel", prompt_id)
    for run_id in (None, original_run):
        with pytest.raises(ValueError, match="prompt_quality_confirmation_required"):
            await director.activate_prompt_version(
                "channel", prompt_id, quality_confirmed=True, replay_run_id=run_id
            )
    await director.activate_prompt_version(
        "channel",
        prompt_id,
        quality_confirmed=True,
        replay_run_id=new["prompts"][0]["replay_metadata"]["run_id"],
    )


@pytest.mark.asyncio
async def test_in_flight_plan_cannot_use_replaced_prompt(monkeypatch):
    _, adapter, runtime, sent, _ = await make_suggestion(monkeypatch)

    async def active(*_):
        return "Replacement prompt"

    monkeypatch.setattr(director_review, "active_prompt", active)
    config, _, version, _ = await director._config("channel")
    snapshot = director_review._replay_snapshot(
        "channel", "unused", "new-moment", "test", config
    )
    snapshot["scope"]["session_id"] = "session"
    proof = {
        "config_version": version,
        "prompt_hash": "previous-prompt-hash",
        "provider_fingerprint": adapter.provider_fingerprint(config),
    }
    with pytest.raises(ValueError, match="prompt_replay_stale"):
        await runtime.submit_response(
            "channel",
            response_for(snapshot),
            source_snapshot_id="new-moment",
            request_proof=proof,
        )
    assert not sent
