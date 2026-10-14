"""Versioned, provider-neutral validation for Director structured reaction plans.

This module is deliberately pure: runtime code supplies an immutable worker snapshot and
may later persist or schedule the returned validated messages.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import difflib
import random
import re
from typing import Any, Callable, Literal, Mapping, Sequence
from uuid import UUID, uuid4

DIRECTOR_PLAN_SCHEMA_VERSION = "director-plan/v1"
MAX_MESSAGE_CHARS = 120

ASSIGNMENT_MODES = frozenset({"backend_random", "ai_assigned"})
REACTION_LEVELS = frozenset({"small", "medium", "large"})

# Exported for adapters that support JSON Schema/tool calling.
DIRECTOR_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "plan_id", "channel_id", "session_id", "source_snapshot_id",
        "explanation", "reaction_level", "reaction_percentage", "assignment_mode",
        "groups", "delay_window_seconds", "ttl_seconds", "template_ids", "example_ids",
    ],
    "properties": {
        "schema_version": {"const": DIRECTOR_PLAN_SCHEMA_VERSION},
        "plan_id": {"type": "string", "format": "uuid"},
        "channel_id": {"type": "string", "minLength": 1},
        "session_id": {"type": "string", "minLength": 1},
        "source_snapshot_id": {"type": "string", "minLength": 1},
        "explanation": {"type": "string", "minLength": 1, "maxLength": 400},
        "reaction_level": {"enum": sorted(REACTION_LEVELS)},
        "reaction_percentage": {"type": "number", "minimum": 0, "maximum": 100},
        "reaction_count": {"type": "integer", "minimum": 0, "description": "Required when plan_constraints.reaction_mode is absolute; must fit the selected level range."},
        "assignment_mode": {"enum": sorted(ASSIGNMENT_MODES)},
        "groups": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["group_id", "text", "percentage", "delay_seconds"],
            "properties": {
                "group_id": {"type": "string", "format": "uuid"},
                "text": {"type": "string", "minLength": 1, "maxLength": MAX_MESSAGE_CHARS},
                "percentage": {"type": "number", "minimum": 0, "maximum": 100},
                "delay_seconds": {"type": "integer", "minimum": 0, "maximum": 300},
            },
        }},
        "individual_messages": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["message_id", "group_id", "bot_id", "text", "delay_seconds"],
            "properties": {
                "message_id": {"type": "string", "format": "uuid"},
                "group_id": {"type": "string", "format": "uuid"},
                "bot_id": {"type": "string", "minLength": 1},
                "text": {"type": "string", "minLength": 1, "maxLength": MAX_MESSAGE_CHARS},
                "delay_seconds": {"type": "integer", "minimum": 0, "maximum": 300},
                "template_id": {"type": "string", "format": "uuid"},
            },
        }},
        "delay_window_seconds": {
            "type": "object", "additionalProperties": False, "required": ["min", "max"],
            "properties": {key: {"type": "integer", "minimum": 0, "maximum": 300} for key in ("min", "max")},
        },
        "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
        "template_ids": {"type": "array", "items": {"type": "string"}},
        "example_ids": {"type": "array", "items": {"type": "string"}},
    },
}

_URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/\S*)?", re.I)
_COMMAND_RE = re.compile(r"(?:^|\s)!\S+")
_MENTION_RE = re.compile(r"@[\w.-]+")
_CODE_RE = re.compile(r"```|`[^`]+`|(?:^|\s)(?:import |def |class |SELECT |INSERT |DROP |curl |wget |rm -rf)", re.I)
_SECRET_RE = re.compile(
    r"\b(?:api[_ -]?key|access[_ -]?token|auth(?:orization)?|password|secret)\b\s*[:=]|"
    r"\b(?:sk|ghp|oauth):?[A-Za-z0-9_\-]{12,}\b|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b\+?\d[\d ()-]{7,}\d\b",
    re.I,
)


@dataclass(frozen=True)
class WorkerSnapshot:
    """Availability captured when the plan was created, never queried again by this layer."""

    worker_id: str
    enabled: bool
    online: bool
    free: bool


@dataclass(frozen=True)
class DirectorPlanScope:
    channel_id: str
    session_id: str
    source_snapshot_id: str


@dataclass(frozen=True)
class ReactionRanges:
    """Owner-approved count ranges keyed by the stable reaction level."""

    mode: Literal["absolute", "percentage"]
    ranges: Mapping[str, tuple[float, float]]


@dataclass(frozen=True)
class ValidatedMessage:
    message_id: str
    group_id: str
    worker_id: str
    text: str
    delay_seconds: int


@dataclass(frozen=True)
class RejectedPlanPart:
    kind: str
    identifier: str
    reason: str


@dataclass(frozen=True)
class PlanValidationResult:
    plan_id: str | None
    planned_count: int
    messages: tuple[ValidatedMessage, ...]
    rejected: tuple[RejectedPlanPart, ...]
    status: Literal["valid", "partial", "rejected"]
    worker_snapshot: tuple[WorkerSnapshot, ...]

    @property
    def is_executable(self) -> bool:
        return bool(self.messages)


class StrictPlanJSONError(ValueError):
    """The provider response was not one complete JSON object."""


def extract_strict_plan_json(response: str) -> dict[str, Any]:
    """Accept exactly one JSON object; prose and Markdown fences are not a fallback format."""
    if not isinstance(response, str):
        raise StrictPlanJSONError("response must be a JSON string")
    candidate = response.strip()
    try:
        value, end = json.JSONDecoder().raw_decode(candidate)
    except json.JSONDecodeError as exc:
        raise StrictPlanJSONError("invalid JSON") from exc
    if candidate[end:].strip() or not isinstance(value, dict):
        raise StrictPlanJSONError("response must contain exactly one JSON object")
    return value


def parse_provider_plan(
    response: str,
    repair: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Parse a provider response, using the single permitted repair boundary once."""
    try:
        return extract_strict_plan_json(response)
    except StrictPlanJSONError:
        if repair is None:
            raise
    repaired = repair(response)
    return extract_strict_plan_json(repaired)


def _uuid(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        return None


def _new_id() -> str:
    return str(uuid4())


def _safe_text(text: Any) -> str | None:
    if not isinstance(text, str):
        return "text_not_string"
    if not text.strip():
        return "text_empty"
    if len(text) > MAX_MESSAGE_CHARS:
        return "text_too_long"
    for pattern, reason in (
        (_URL_RE, "url_forbidden"), (_COMMAND_RE, "command_forbidden"),
        (_MENTION_RE, "mention_forbidden"), (_CODE_RE, "code_like_forbidden"),
        (_SECRET_RE, "secret_or_personal_data_forbidden"),
    ):
        if pattern.search(text):
            return reason
    return None


def _largest_remainder(total: int, percentages: Sequence[float], denominator: float) -> list[int]:
    """Allocate integers without silently changing the requested overall group size."""
    if total <= 0 or denominator <= 0:
        return [0] * len(percentages)
    raw = [total * percent / denominator for percent in percentages]
    amounts = [int(value) for value in raw]
    remaining = total - sum(amounts)
    for index in sorted(range(len(raw)), key=lambda i: (raw[i] - amounts[i], -i), reverse=True)[:remaining]:
        amounts[index] += 1
    return amounts


def calculate_reaction_count(
    *, level: str, ranges: ReactionRanges, available_workers: int, reaction_count: Any = None,
    reaction_percentage: Any = None,
) -> int:
    """Return an owner-bounded target. Positive percentages always select at least one worker."""
    if level not in REACTION_LEVELS or level not in ranges.ranges:
        raise ValueError("unknown_reaction_level")
    lower, upper = ranges.ranges[level]
    if lower < 0 or upper < lower:
        raise ValueError("invalid_reaction_ranges")
    if ranges.mode == "absolute":
        if not isinstance(reaction_count, int) or isinstance(reaction_count, bool):
            raise ValueError("reaction_count_required")
        if not lower <= reaction_count <= upper:
            raise ValueError("reaction_count_out_of_range")
        return min(reaction_count, available_workers)
    if not isinstance(reaction_percentage, (int, float)) or isinstance(reaction_percentage, bool):
        raise ValueError("reaction_percentage_required")
    if not lower <= reaction_percentage <= upper:
        raise ValueError("reaction_percentage_out_of_range")
    if reaction_percentage == 0:
        return 0
    return min(available_workers, max(1, round(available_workers * float(reaction_percentage) / 100)))


def _base_plan_errors(plan: Mapping[str, Any], scope: DirectorPlanScope) -> list[RejectedPlanPart]:
    rejected: list[RejectedPlanPart] = []
    unknown_keys = set(plan) - set(DIRECTOR_PLAN_JSON_SCHEMA["properties"])
    if unknown_keys:
        rejected.append(RejectedPlanPart("plan", ",".join(sorted(unknown_keys)), "unknown_schema_field"))
    plan_id = _uuid(plan.get("plan_id"))
    if plan_id is None:
        rejected.append(RejectedPlanPart("plan", "plan_id", "invalid_plan_id"))
    if plan.get("schema_version") != DIRECTOR_PLAN_SCHEMA_VERSION:
        rejected.append(RejectedPlanPart("plan", str(plan.get("schema_version", "")), "unsupported_schema_version"))
    for key, expected in (("channel_id", scope.channel_id), ("session_id", scope.session_id),
                          ("source_snapshot_id", scope.source_snapshot_id)):
        if plan.get(key) != expected:
            rejected.append(RejectedPlanPart("plan", key, "scope_mismatch"))
    if plan.get("assignment_mode") not in ASSIGNMENT_MODES:
        rejected.append(RejectedPlanPart("plan", "assignment_mode", "invalid_assignment_mode"))
    if plan.get("reaction_level") not in REACTION_LEVELS:
        rejected.append(RejectedPlanPart("plan", "reaction_level", "invalid_reaction_level"))
    percentage = plan.get("reaction_percentage")
    if not isinstance(percentage, (int, float)) or isinstance(percentage, bool) or not 0 <= percentage <= 100:
        rejected.append(RejectedPlanPart("plan", "reaction_percentage", "invalid_reaction_percentage"))
    explanation = plan.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip() or len(explanation) > 400:
        rejected.append(RejectedPlanPart("plan", "explanation", "invalid_explanation"))
    delay = plan.get("delay_window_seconds")
    ttl = plan.get("ttl_seconds")
    if not isinstance(delay, dict) or set(delay) != {"min", "max"} or any(
        not isinstance(delay.get(key), int) or isinstance(delay.get(key), bool) for key in ("min", "max")
    ) or not 0 <= delay.get("min", -1) <= delay.get("max", -1) <= 300:
        rejected.append(RejectedPlanPart("plan", "delay_window_seconds", "invalid_delay_window"))
    elif not isinstance(ttl, int) or isinstance(ttl, bool) or not 1 <= ttl <= 600 or ttl < delay["max"]:
        rejected.append(RejectedPlanPart("plan", "ttl_seconds", "invalid_ttl"))
    if not isinstance(plan.get("groups"), list) or not plan["groups"]:
        rejected.append(RejectedPlanPart("plan", "groups", "groups_required"))
    if not isinstance(plan.get("individual_messages", []), list):
        rejected.append(RejectedPlanPart("plan", "individual_messages", "invalid_individual_messages"))
    for key in ("template_ids", "example_ids"):
        if not isinstance(plan.get(key), list) or not all(isinstance(value, str) and value for value in plan[key]):
            rejected.append(RejectedPlanPart("plan", key, "invalid_reference_ids"))
    return rejected


def validate_plan(
    plan: Mapping[str, Any], *, scope: DirectorPlanScope, workers: Sequence[WorkerSnapshot],
    ranges: ReactionRanges, rng: random.Random | None = None,
    allowed_duplicate_texts: frozenset[str] = frozenset(), similarity_mode: str = "normal",
    templates: Mapping[str, tuple[str, str]] | None = None, chat_texts: frozenset[str] = frozenset(),
    copypasta_allowed: bool = False,
) -> PlanValidationResult:
    """Validate readable plan parts and return a frozen, scheduler-ready execution snapshot.

    Invalid plan envelope prevents execution. Invalid individual groups/messages stay in the
    rejection list, deliberately without repair, replacement, or allocation compensation.
    """
    snapshot = tuple(workers)
    templates = dict(templates) if isinstance(templates, Mapping) else {}
    if not isinstance(plan, Mapping):
        return PlanValidationResult(None, 0, (), (RejectedPlanPart("plan", "", "plan_not_object"),), "rejected", snapshot)
    rejected = _base_plan_errors(plan, scope)
    plan_id = _uuid(plan.get("plan_id"))
    if rejected:
        return PlanValidationResult(plan_id, 0, (), tuple(rejected), "rejected", snapshot)
    available = [worker for worker in snapshot if worker.enabled and worker.online and worker.free]
    try:
        target = calculate_reaction_count(
            level=plan["reaction_level"], ranges=ranges, available_workers=len(available),
            reaction_count=plan.get("reaction_count"), reaction_percentage=plan.get("reaction_percentage"),
        )
    except ValueError as exc:
        return PlanValidationResult(plan_id, 0, (), (RejectedPlanPart("plan", "reaction", str(exc)),), "rejected", snapshot)

    mode = plan["assignment_mode"]
    randomizer = rng or random.Random()
    messages: list[ValidatedMessage] = []
    seen_group_ids: set[str] = set()
    seen_message_ids: set[str] = set()
    valid_groups: list[tuple[str, str, float, int]] = []
    declared_groups: list[tuple[str, float]] = []
    group_percent_sum = 0.0
    for position, group in enumerate(plan["groups"]):
        identifier = str(position)
        if not isinstance(group, dict):
            rejected.append(RejectedPlanPart("group", identifier, "group_not_object")); continue
        if set(group) - set(DIRECTOR_PLAN_JSON_SCHEMA["properties"]["groups"]["items"]["properties"]):
            rejected.append(RejectedPlanPart("group", identifier, "unknown_schema_field")); continue
        group_id = _uuid(group.get("group_id"))
        if group_id is None or group_id in seen_group_ids:
            rejected.append(RejectedPlanPart("group", identifier, "invalid_or_duplicate_group_id")); continue
        seen_group_ids.add(group_id)
        percentage = group.get("percentage")
        delay = group.get("delay_seconds")
        if not isinstance(percentage, (int, float)) or isinstance(percentage, bool) or not 0 <= percentage <= 100:
            rejected.append(RejectedPlanPart("group", group_id, "invalid_group_percentage")); continue
        declared_groups.append((group_id, float(percentage)))
        text_error = _safe_text(group.get("text"))
        if text_error:
            rejected.append(RejectedPlanPart("group", group_id, text_error)); continue
        if not isinstance(delay, int) or isinstance(delay, bool) or not plan["delay_window_seconds"]["min"] <= delay <= plan["delay_window_seconds"]["max"]:
            rejected.append(RejectedPlanPart("group", group_id, "delay_outside_window")); continue
        valid_groups.append((group_id, group["text"], float(percentage), delay))
        group_percent_sum += float(percentage)
    if valid_groups and abs(group_percent_sum - 100) > 1e-9:
        rejected.append(RejectedPlanPart("plan", "groups", "group_percentages_must_sum_to_100"))

    if mode == "backend_random":
        allocations = dict(zip(
            (group_id for group_id, _ in declared_groups),
            _largest_remainder(target, [percentage for _, percentage in declared_groups], 100),
        ))
        pool = list(available)
        randomizer.shuffle(pool)
        for group_id, text, _percentage, delay in valid_groups:
            allocation = allocations[group_id]
            available_for_group = len(pool)
            for _ in range(min(allocation, available_for_group)):
                worker = pool.pop()
                message_id = _new_id()
                messages.append(ValidatedMessage(message_id, group_id, worker.worker_id, text, delay))
            if allocation > available_for_group:
                rejected.append(RejectedPlanPart("group", group_id, "no_available_workers"))
    else:
        allowed_ids = {worker.worker_id for worker in available}
        used_ids: set[str] = set()
        for position, row in enumerate(plan.get("individual_messages", [])):
            identifier = str(position)
            if not isinstance(row, dict):
                rejected.append(RejectedPlanPart("message", identifier, "message_not_object")); continue
            if set(row) - set(DIRECTOR_PLAN_JSON_SCHEMA["properties"]["individual_messages"]["items"]["properties"]):
                rejected.append(RejectedPlanPart("message", identifier, "unknown_schema_field")); continue
            message_id = _uuid(row.get("message_id"))
            group_id = _uuid(row.get("group_id"))
            worker_id = row.get("bot_id")
            if message_id is None or message_id in seen_message_ids:
                rejected.append(RejectedPlanPart("message", identifier, "invalid_or_duplicate_message_id")); continue
            seen_message_ids.add(message_id)
            if group_id not in {group[0] for group in valid_groups}:
                rejected.append(RejectedPlanPart("message", message_id, "unknown_group_id")); continue
            text_error = _safe_text(row.get("text"))
            delay = row.get("delay_seconds")
            if text_error:
                rejected.append(RejectedPlanPart("message", message_id, text_error)); continue
            if worker_id not in allowed_ids or worker_id in used_ids:
                rejected.append(RejectedPlanPart("message", message_id, "worker_not_available_in_snapshot")); continue
            if not isinstance(delay, int) or isinstance(delay, bool) or not plan["delay_window_seconds"]["min"] <= delay <= plan["delay_window_seconds"]["max"]:
                rejected.append(RejectedPlanPart("message", message_id, "delay_outside_window")); continue
            used_ids.add(worker_id)
            template_id = row.get("template_id")
            if template_id is not None:
                template = templates.get(str(template_id))
                if template is None:
                    rejected.append(RejectedPlanPart("message", message_id, "unknown_template_id")); continue
                template_text, template_mode = template
                message_text = str(row["text"])
                if template_mode == "exact" and message_text != template_text:
                    rejected.append(RejectedPlanPart("message", message_id, "template_exact_mismatch")); continue
                if template_mode == "placeholders":
                    if any(ph not in message_text for ph in re.findall(r"\{\w+\}", template_text)):
                        rejected.append(RejectedPlanPart("message", message_id, "template_placeholder_missing")); continue
                # "adaptable": the safe non-empty text itself is enough.
            messages.append(ValidatedMessage(message_id, group_id, worker_id, row["text"], delay))
        if len(messages) > target:
            overflow = messages[target:]
            messages = messages[:target]
            rejected.extend(RejectedPlanPart("message", item.message_id, "exceeds_reaction_count") for item in overflow)

    # Spec §8: `diverse` similarity is off/normal/strict (default normal). Chant phrases from
    # the owner dictionary (or session-approved AI phrases) are exempt from duplicate rejection.
    # Spec §8: copypasta (verbatim chat text) needs the channel toggle (default off);
    # several chat messages are never concatenated into one plan text.
    if not copypasta_allowed:
        for group_id, text, _percentage, _delay in valid_groups:
            if str(text) in chat_texts:
                rejected.append(RejectedPlanPart("group", group_id, "copypasta_disabled"))

    if similarity_mode != "off":
        seen_texts: list[tuple[str, str]] = []  # (normalized, part id)
        for group_id, text, _percentage, _delay in valid_groups:
            normalized = " ".join(str(text).lower().split())
            if normalized in allowed_duplicate_texts:
                continue
            duplicate = False
            for other, other_id in seen_texts:
                ratio = difflib.SequenceMatcher(a=normalized, b=other).ratio()
                if normalized == other or (similarity_mode == "strict" and ratio >= 0.85):
                    rejected.append(RejectedPlanPart("group", group_id, "duplicate_text" if normalized == other else "similar_text"))
                    duplicate = True
                    break
            if not duplicate:
                seen_texts.append((normalized, group_id))

    status: Literal["valid", "partial", "rejected"] = "valid" if not rejected else "partial"
    if not messages and target > 0:
        status = "rejected"
    return PlanValidationResult(plan_id, target, tuple(messages), tuple(rejected), status, snapshot)


def validate_provider_response(
    response: str, *, scope: DirectorPlanScope, workers: Sequence[WorkerSnapshot], ranges: ReactionRanges,
    repair: Callable[[str], str] | None = None, rng: random.Random | None = None,
    allowed_duplicate_texts: frozenset[str] = frozenset(), similarity_mode: str = "normal",
    templates: Mapping[str, tuple[str, str]] | None = None, chat_texts: frozenset[str] = frozenset(),
    copypasta_allowed: bool = False,
) -> PlanValidationResult:
    """Adapter boundary: parse strictly (and at most one repair), then validate exactly once."""
    return validate_plan(
        parse_provider_plan(response, repair), scope=scope, workers=workers, ranges=ranges, rng=rng,
        allowed_duplicate_texts=allowed_duplicate_texts, similarity_mode=similarity_mode,
        templates=templates, chat_texts=chat_texts, copypasta_allowed=copypasta_allowed,
    )
