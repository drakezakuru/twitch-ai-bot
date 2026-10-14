import pytest
from app import director


def test_default_config_is_valid_and_safe():
    config = director.validate_config({})
    assert config["ttl_sec"] >= config["send_delay_max_sec"]
    assert config["language"] == "auto"


@pytest.mark.parametrize("raw", [
    {"analysis_interval_sec": 2},
    {"ttl_sec": 5, "send_delay_max_sec": 10},
    {"reaction_mode": "percentage", "ranges": {"small": [0, 10], "medium": [9, 35], "large": [36, 70]}},
    {"ranges": {"small": [0, 3], "medium": [4, 12], "large": [11, 30]}},
])
def test_config_rejects_illegal_or_overlapping_values(raw):
    with pytest.raises(ValueError):
        director.validate_config(raw)


@pytest.mark.asyncio
async def test_config_schema_is_additive_and_save_is_versioned(tmp_db):
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (1, 'worker', 'x', 1, 'lurker')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (1, 'channel', 1)")
        await db.execute("INSERT INTO accounts (id, nickname, token, enabled, bot_role) VALUES (2, 'director', 'x', 1, 'director')")
        await db.execute("INSERT INTO channels (account_id, channel_name, enabled) VALUES (2, 'channel', 1)")
        await db.commit()
    finally:
        await db.close()
    await director.save_config("Channel", {}, [1], 2)
    await director.save_config("channel", {"analysis_interval_sec": 20}, [1], 2)
    db = await get_db()
    try:
        row = await (await db.execute("SELECT version FROM director_configs WHERE channel='channel'")).fetchone()
        assert row[0] == 2
    finally:
        await db.close()


def test_config_uses_exact_structured_plan_assignment_names():
    assert director.validate_config({"assignment_mode": "backend_random"})["assignment_mode"] == "backend_random"
    assert director.validate_config({"assignment_mode": "ai_assigned"})["assignment_mode"] == "ai_assigned"
    with pytest.raises(ValueError, match="invalid_assignment_mode"):
        director.validate_config({"assignment_mode": "random"})


@pytest.mark.asyncio
async def test_prompt_versions_require_test_before_activation_and_audit_is_scoped(tmp_db):
    from app.database import init_db
    await init_db()
    created = await director.create_prompt_version("one", "Keep reactions brief.")
    with pytest.raises(ValueError, match="prompt_not_tested"):
        await director.activate_prompt_version("one", created["id"])
    with pytest.raises(ValueError, match="replay_metadata_server_owned"):
        await director.set_prompt_tested("one", created["id"], {"fixture": "safe-plan-v1"})
    prompts = await director.list_prompt_versions("one")
    assert prompts["prompts"][0]["active"] is False
    assert prompts["prompts"][0]["tested"] is False
    assert (await director.list_audit("two"))["entries"] == []
    assert all(entry["action"] != "prompt_activated" for entry in (await director.list_audit("one"))["entries"])
