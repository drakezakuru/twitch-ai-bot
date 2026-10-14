from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.qa_profile import (
    ACCOUNT_IDS,
    ACCOUNT_NAMES,
    _configured_runtime,
    profile_root,
    reset_profile,
    seed_profile,
    verify_profile,
)


def test_fake_profile_is_deterministic_and_contains_expected_data(tmp_path: Path):
    base = tmp_path / "qa-profiles"
    asyncio.run(reset_profile("local", base_root=base))
    first = asyncio.run(seed_profile("local", base_root=base))
    second = asyncio.run(seed_profile("local", base_root=base))

    assert first["fingerprint"] == second["fingerprint"]
    assert tuple(item["id"] for item in second["accounts"]) == ACCOUNT_IDS
    assert tuple(item["nickname"] for item in second["accounts"]) == ACCOUNT_NAMES
    assert [item["bot_role"] for item in second["accounts"]] == [
        "moderator", "voice_companion", "chatter",
    ]
    assert second["safe_tokens"] is True
    assert second["foreign_key_errors"] == 0
    assert second["row_counts"]["moderation_events"] == 4
    assert second["row_counts"]["soundboard_tracks"] == 3
    assert len(second["audio"]) == 3
    assert verify_profile("local", base_root=base)["fingerprint"] == second["fingerprint"]


def test_reset_requires_marker_and_does_not_touch_sibling(tmp_path: Path):
    base = tmp_path / "qa-profiles"
    root = profile_root("local", base_root=base)
    root.mkdir(parents=True)
    sentinel = root / "do-not-delete.txt"
    sentinel.write_text("production-like", encoding="utf-8")

    with pytest.raises(ValueError, match="unmarked"):
        asyncio.run(reset_profile("local", base_root=base))
    assert sentinel.read_text(encoding="utf-8") == "production-like"


def test_reset_refuses_symlinked_marked_profile_before_resolving(tmp_path: Path):
    base = tmp_path / "qa-profiles"
    protected = base / "marked-profile"
    asyncio.run(reset_profile("local", base_root=base))
    profile_root("local", base_root=base).rename(protected)
    sentinel = protected / "do-not-delete.txt"
    sentinel.write_text("production-like", encoding="utf-8")
    (base / "local").symlink_to(protected, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot contain symlinks"):
        asyncio.run(reset_profile("local", base_root=base))

    assert sentinel.read_text(encoding="utf-8") == "production-like"


def test_profile_root_refuses_symlinked_namespace(tmp_path: Path):
    real_namespace = tmp_path / "real-qa-profiles"
    real_namespace.mkdir()
    namespace = tmp_path / "qa-profiles"
    namespace.symlink_to(real_namespace, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot contain symlinks"):
        profile_root("local", base_root=namespace)


@pytest.mark.parametrize("name", ("../data", "", "UPPER", "has space", "a/b"))
def test_unsafe_profile_names_are_rejected(tmp_path: Path, name: str):
    with pytest.raises(ValueError):
        profile_root(name, base_root=tmp_path / "qa-profiles")


def test_reset_returns_to_empty_baseline(tmp_path: Path):
    base = tmp_path / "qa-profiles"
    asyncio.run(reset_profile("local", base_root=base))
    asyncio.run(seed_profile("local", base_root=base))
    baseline = asyncio.run(reset_profile("local", base_root=base))

    assert baseline["accounts"] == []
    assert baseline["channels"] == []
    assert baseline["row_counts"]["chat_log"] == 0
    assert baseline["audio"] == []


@pytest.mark.asyncio
async def test_local_profile_moderator_acceptance_uses_only_stubs(tmp_path: Path, monkeypatch):
    """Track 6.2: fake violations reach the incident, action, feed, and audit paths offline."""
    from app import database, moderation
    from app.mod_feed_routes import _BUFFER, _DEDUP, _LAST_VIOLATOR, _moderator_action, publish_event

    base = tmp_path / "qa-profiles"
    await reset_profile("local", base_root=base)
    await seed_profile("local", base_root=base)
    root = profile_root("local", base_root=base)
    calls: list[dict] = []

    async def timeout_stub(token, channel, moderator_login, username, duration_sec=600, reason=""):
        calls.append({"kind": "timeout", "channel": channel, "user": username,
                      "duration": duration_sec, "token": token})
        return True, ""

    async def settings_stub(token, channel, moderator_login, **settings):
        calls.append({"kind": "slow-mode", "channel": channel, "token": token, **settings})
        return True, ""

    monkeypatch.setattr("app.twitch_helix.timeout_user", timeout_stub)
    monkeypatch.setattr("app.twitch_helix.update_chat_settings", settings_stub)

    async with _configured_runtime(root):
        await database.init_db()
        moderation.invalidate_cache()
        _BUFFER.clear()
        _DEDUP.clear()
        _LAST_VIOLATOR.clear()
        db = await database.get_db()
        try:
            settings = await moderation.get_settings(101)
            assert settings["moderation_mode"] == "full"
            assert settings["moderation_can_timeout"] is True
            assert settings["antispam_viewer_enabled"] is True
            rows = await (await db.execute(
                "SELECT message FROM chat_log WHERE account_id = 101 ORDER BY id"
            )).fetchall()
            assert {"BUY NOW BUY NOW", "you are a retard", "visit https://unsafe.example"} <= {
                row["message"] for row in rows
            }
            # The local profile is normally disabled; enable only this in-process stub flow.
            await db.execute("UPDATE accounts SET enabled = 1 WHERE id = 101")
            await db.commit()
        finally:
            await db.close()

        toxic, _ = await moderation.check_incoming(
            101, "qa_mod_channel", "viewer_toxic", "you are a retard"
        )
        _, links = await moderation.check_incoming(
            101, "qa_mod_channel", "viewer_link", "visit https://unsafe.example"
        )
        _, spam = await moderation.check_incoming(
            101, "qa_mod_channel", "viewer_spam", "BUY NOW BUY NOW"
        )
        assert toxic[0].category == "insult" and toxic[0].action == "block"
        assert any(hit.category == "links" for hit in links)
        assert any(hit.category == "caps" for hit in spam)

        incident = publish_event(
            101, "qa_mod_channel", "violation", user="viewer_toxic",
            text="you are a retard", severity=toxic[0].severity,
        )
        assert incident is not None

        from app.server import chat_analyzer
        chat_analyzer._account_token[101] = "qa-local-stub"
        try:
            assert await _moderator_action(101, "qa_mod_channel", "warn_last") == {
                "ok": True, "warned": "viewer_toxic",
            }
            assert (await _moderator_action(101, "qa_mod_channel", "timeout_last"))["ok"] is True
            assert (await _moderator_action(101, "qa_mod_channel", "slow_on", "7"))["ok"] is True
            assert await moderation.maybe_timeout(
                101, "qa_mod_channel", "viewer_toxic",
                moderation.Verdict(category="insult", action="timeout", severity=3,
                                   rule_name="QA acceptance"),
                token="qa-local-stub", bot_nickname="qa_modbot",
            )
        finally:
            chat_analyzer._account_token.pop(101, None)

        assert [call["kind"] for call in calls] == ["timeout", "slow-mode", "timeout"]
        assert calls[1]["slow_mode"] is True and calls[1]["slow_mode_wait_time"] == 7
        assert all(call["token"] == "qa-local-stub" for call in calls)
        assert {event["action"] for event in _BUFFER if event["kind"] == "action"} >= {
            "warn", "timeout 1 мин", "slow_on",
        }
        db = await database.get_db()
        try:
            audits = await (await db.execute(
                "SELECT category, action_taken FROM moderation_events "
                "WHERE account_id = 101 AND username = 'viewer_toxic'"
            )).fetchall()
            await db.execute("UPDATE accounts SET enabled = 0 WHERE id = 101")
            await db.commit()
        finally:
            await db.close()
        assert ("insult", "block") in {(row["category"], row["action_taken"]) for row in audits}
        assert ("insult", "timeout") in {(row["category"], row["action_taken"]) for row in audits}

    assert verify_profile("local", base_root=base)["safe_tokens"] is True
