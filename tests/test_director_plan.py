"""Focused contract tests for the standalone Director structured-plan layer."""
from __future__ import annotations

import json
import random
from uuid import uuid4

import pytest

from app.director_plan import (
    DIRECTOR_PLAN_SCHEMA_VERSION,
    DirectorPlanScope,
    ReactionRanges,
    StrictPlanJSONError,
    WorkerSnapshot,
    calculate_reaction_count,
    extract_strict_plan_json,
    parse_provider_plan,
    validate_plan,
    validate_provider_response,
)


SCOPE = DirectorPlanScope("channel-42", "session-42", "sources-42")
RANGES = ReactionRanges("percentage", {"small": (0, 10), "medium": (10, 35), "large": (35, 100)})
WORKERS = tuple(WorkerSnapshot(f"bot-{number}", True, True, True) for number in range(1, 6))


def _id() -> str:
    return str(uuid4())


def _plan(*, mode: str = "backend_random") -> dict:
    return {
        "schema_version": DIRECTOR_PLAN_SCHEMA_VERSION,
        "plan_id": _id(),
        "channel_id": SCOPE.channel_id,
        "session_id": SCOPE.session_id,
        "source_snapshot_id": SCOPE.source_snapshot_id,
        "explanation": "Chat reacted to a verified game win.",
        "reaction_level": "large",
        "reaction_percentage": 100,
        "assignment_mode": mode,
        "groups": [
            {"group_id": _id(), "text": "That was a clean win", "percentage": 50, "delay_seconds": 2},
            {"group_id": _id(), "text": "Lets go", "percentage": 30, "delay_seconds": 4},
            {"group_id": _id(), "text": "Huge play", "percentage": 20, "delay_seconds": 6},
        ],
        "individual_messages": [],
        "delay_window_seconds": {"min": 1, "max": 20},
        "ttl_seconds": 45,
        "template_ids": [],
        "example_ids": [],
    }


def test_strict_json_rejects_prose_fences_and_trailing_content():
    assert extract_strict_plan_json('  {"ok": true}\n') == {"ok": True}
    for response in ("Here: {\"ok\": true}", "```json\n{}\n```", "{} another object", "[]"):
        with pytest.raises(StrictPlanJSONError):
            extract_strict_plan_json(response)


def test_only_unparseable_provider_response_can_use_one_repair_attempt():
    calls: list[str] = []

    def repair(value: str) -> str:
        calls.append(value)
        return '{"fixed": true}'

    assert parse_provider_plan("not json", repair) == {"fixed": True}
    assert calls == ["not json"]
    with pytest.raises(StrictPlanJSONError):
        parse_provider_plan("not json", lambda _: "still not json")


def test_percentage_and_absolute_target_counts_follow_owner_ranges():
    assert calculate_reaction_count(level="medium", ranges=RANGES, available_workers=5, reaction_percentage=10) == 1
    assert calculate_reaction_count(level="small", ranges=RANGES, available_workers=5, reaction_percentage=0) == 0
    absolute = ReactionRanges("absolute", {"small": (0, 3), "medium": (4, 12), "large": (13, 30)})
    assert calculate_reaction_count(level="medium", ranges=absolute, available_workers=5, reaction_count=4) == 4
    with pytest.raises(ValueError, match="out_of_range"):
        calculate_reaction_count(level="small", ranges=absolute, available_workers=5, reaction_count=4)


def test_backend_random_allocation_is_exact_and_deterministic_by_group():
    plan = _plan()
    result = validate_plan(plan, scope=SCOPE, workers=WORKERS, ranges=RANGES, rng=random.Random(9))
    counts = {group["group_id"]: 0 for group in plan["groups"]}
    for message in result.messages:
        counts[message.group_id] += 1
    assert list(counts.values()) == [3, 1, 1]
    assert len({message.worker_id for message in result.messages}) == 5
    assert len({message.message_id for message in result.messages}) == 5
    assert result.worker_snapshot == WORKERS


def test_ai_assigned_rejects_unavailable_and_duplicate_workers_without_replacement():
    plan = _plan(mode="ai_assigned")
    first_group, second_group = plan["groups"][:2]
    plan["individual_messages"] = [
        {"message_id": _id(), "group_id": first_group["group_id"], "bot_id": "bot-1", "text": "Nice", "delay_seconds": 2},
        {"message_id": _id(), "group_id": second_group["group_id"], "bot_id": "bot-1", "text": "Also nice", "delay_seconds": 3},
        {"message_id": _id(), "group_id": second_group["group_id"], "bot_id": "missing", "text": "Nope", "delay_seconds": 3},
    ]
    result = validate_plan(plan, scope=SCOPE, workers=WORKERS, ranges=RANGES)
    assert result.status == "partial"
    assert [message.worker_id for message in result.messages] == ["bot-1"]
    assert {item.reason for item in result.rejected} == {"worker_not_available_in_snapshot"}


@pytest.mark.parametrize("unsafe", [
    "https://example.test", "visit www.example.test", "!ban user", "!команда", "!123", "!🎲", "hello @viewer",
    "`rm -rf /`", "api_key=secret-value-very-long", "mail me viewer@example.com",
])
def test_hard_text_filters_reject_only_unsafe_group(unsafe: str):
    plan = _plan()
    plan["groups"][0]["text"] = unsafe
    result = validate_plan(plan, scope=SCOPE, workers=WORKERS, ranges=RANGES)
    assert result.status == "partial"
    assert len(result.messages) == 2
    assert result.rejected[0].kind == "group"


def test_scope_schema_and_timing_mismatches_fail_closed_without_repair():
    plan = _plan()
    plan["channel_id"] = "other-channel"
    result = validate_provider_response(json.dumps(plan), scope=SCOPE, workers=WORKERS, ranges=RANGES, repair=lambda _: pytest.fail("must not repair readable JSON"))
    assert result.status == "rejected"
    assert result.messages == ()
    assert result.rejected[0].reason == "scope_mismatch"


def test_duplicate_plan_group_and_message_ids_are_rejected():
    plan = _plan(mode="ai_assigned")
    plan["groups"][1]["group_id"] = plan["groups"][0]["group_id"]
    plan["individual_messages"] = [
        {"message_id": _id(), "group_id": plan["groups"][0]["group_id"], "bot_id": "bot-1", "text": "Nice", "delay_seconds": 2},
    ]
    result = validate_plan(plan, scope=SCOPE, workers=WORKERS, ranges=RANGES)
    assert result.status == "partial"
    assert any(item.reason == "invalid_or_duplicate_group_id" for item in result.rejected)


def test_text_longer_than_120_is_rejected():
    plan = _plan()
    plan["groups"][0]["text"] = "x" * 121
    result = validate_plan(plan, scope=SCOPE, workers=WORKERS, ranges=RANGES)
    assert any(item.reason == "text_too_long" for item in result.rejected)


# ── Optional §8/§11 features ──

def _duplicate_groups_plan(scope):
    group_a, group_b = str(uuid4()), str(uuid4())
    return {
        "schema_version": DIRECTOR_PLAN_SCHEMA_VERSION, "plan_id": str(uuid4()),
        "channel_id": scope.channel_id, "session_id": scope.session_id,
        "source_snapshot_id": scope.source_snapshot_id,
        "explanation": "Chant", "reaction_level": "medium", "reaction_percentage": 0,
        "reaction_count": 4, "assignment_mode": "backend_random",
        "groups": [
            {"group_id": group_a, "text": "LETS GOO", "percentage": 50, "delay_seconds": 1},
            {"group_id": group_b, "text": "LETS GOO", "percentage": 50, "delay_seconds": 1},
        ],
        "individual_messages": [], "delay_window_seconds": {"min": 1, "max": 2}, "ttl_seconds": 45,
        "template_ids": [], "example_ids": [],
    }


def test_diverse_similarity_modes_gate_duplicates(tmp_db):
    scope = DirectorPlanScope("runtime", str(uuid4()), str(uuid4()))
    workers = [WorkerSnapshot("1", True, True, True)]
    ranges = ReactionRanges("absolute", {"small": (0, 3), "medium": (4, 12), "large": (13, 30)})
    plan = _duplicate_groups_plan(scope)
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges, similarity_mode="normal")
    assert "duplicate_text" in [part.reason for part in result.rejected]
    # strict also flags near-duplicates; off allows them
    strict = dict(plan); strict["groups"] = [
        {"group_id": plan["groups"][0]["group_id"], "text": "LETS GOO!", "percentage": 50, "delay_seconds": 1},
        {"group_id": plan["groups"][1]["group_id"], "text": "LETS GOO", "percentage": 50, "delay_seconds": 1},
    ]
    result = validate_plan(strict, scope=scope, workers=workers, ranges=ranges, similarity_mode="strict")
    assert "similar_text" in [part.reason for part in result.rejected]
    # chant dictionary exempts the phrase
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges,
                           allowed_duplicate_texts=frozenset({"lets goo"}))
    assert result.status == "valid"


def _template_message_plan(scope):
    message_id = str(uuid4())
    return {
        "schema_version": DIRECTOR_PLAN_SCHEMA_VERSION, "plan_id": str(uuid4()),
        "channel_id": scope.channel_id, "session_id": scope.session_id,
        "source_snapshot_id": scope.source_snapshot_id,
        "explanation": "Template", "reaction_level": "small", "reaction_percentage": 0,
        "reaction_count": 1, "assignment_mode": "ai_assigned",
        "groups": [{"group_id": "00000000-0000-4000-8000-000000000001", "text": "GG {name}", "percentage": 100, "delay_seconds": 1}],
        "individual_messages": [{
            "message_id": message_id, "group_id": "00000000-0000-4000-8000-000000000001",
            "bot_id": "1", "text": "GG {name}", "delay_seconds": 1, "template_id": "t1",
        }],
        "delay_window_seconds": {"min": 1, "max": 2}, "ttl_seconds": 45,
        "template_ids": ["t1"], "example_ids": [],
    }


def test_templates_per_item_modes(tmp_db):
    scope = DirectorPlanScope("runtime", str(uuid4()), str(uuid4()))
    workers = [WorkerSnapshot("1", True, True, True)]
    ranges = ReactionRanges("absolute", {"small": (0, 3), "medium": (4, 12), "large": (13, 30)})
    plan = _template_message_plan(scope)
    # exact mode: text must equal the template
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges, templates={"t1": ("GG {name}", "exact")})
    assert result.status == "valid"
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges, templates={"t1": ("GG wp", "exact")})
    assert "template_exact_mismatch" in [part.reason for part in result.rejected]
    # placeholders: every {token} must survive into the text
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges, templates={"t1": ("GG {name}!", "placeholders")})
    assert result.status == "valid"
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges, templates={"t1": ("{greeting} {name}", "placeholders")})
    assert "template_placeholder_missing" in [part.reason for part in result.rejected]
    # adaptable: any safe text passes
    adaptable = json.loads(json.dumps(plan)); adaptable["individual_messages"][0]["text"] = "Что за игра?"
    result = validate_plan(adaptable, scope=scope, workers=workers, ranges=ranges, templates={"t1": ("GG {name}", "adaptable")})
    assert result.status == "valid"
    # unknown template id is rejected
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges, templates={})
    assert "unknown_template_id" in [part.reason for part in result.rejected]


def test_copypasta_needs_channel_toggle(tmp_db):
    scope = DirectorPlanScope("runtime", str(uuid4()), str(uuid4()))
    workers = [WorkerSnapshot("1", True, True, True)]
    ranges = ReactionRanges("absolute", {"small": (0, 3), "medium": (4, 12), "large": (13, 30)})
    plan = json.loads(json.dumps(_template_message_plan(scope)))
    plan["groups"][0]["text"] = "REPOLOL REPOLOL"
    plan["individual_messages"][0].pop("template_id", None)
    chat_texts = frozenset({"REPOLOL REPOLOL"})
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges, chat_texts=chat_texts)
    assert "copypasta_disabled" in [part.reason for part in result.rejected]
    result = validate_plan(plan, scope=scope, workers=workers, ranges=ranges, chat_texts=chat_texts, copypasta_allowed=True)
    assert result.status == "valid"
