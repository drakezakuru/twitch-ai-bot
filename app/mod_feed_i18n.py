"""Display-only metadata. Never derive localization keys from event text/action."""
from __future__ import annotations

TOOLS = (
    "timeout", "warn", "clear", "slow_on", "slow_off", "emote_on", "emote_off",
    "unique_on", "unique_off", "category", "ai_category", "title", "slow",
    "follower", "emote_only", "unique",
)
VOICE_COMMANDS = (
    "countdown.start", "countdown.pause", "countdown.reset", "countdown.add_time",
    "sub_goal.reset", "sub_goal.increment", "sub_goal.set", "now_playing.clear",
    "now_playing.set", "lower_third.show", "lower_third.hide", "goals.add_percent",
    "goals.reset",
)
CAPTION_PARAMS = {
    "mod-feed.caption.rule": {}, "mod-feed.caption.applied": {}, "mod-feed.caption.decision_required": {},
    "mod-feed.caption.moderation": {"category": str},
    "mod-feed.caption.category_severity": {"category": str, "severity": int},
    "mod-feed.caption.timeout_proposal": {"minutes": int, "category": str},
    "mod-feed.caption.hotkey_timeout": {}, "mod-feed.caption.failed": {}, "mod-feed.caption.hotkey_warn": {},
    "mod-feed.caption.hotkey_clear": {}, "mod-feed.caption.hotkey_applied": {"tool": TOOLS},
    "mod-feed.caption.timeout": {"minutes": int},
    "mod-feed.caption.stream_category": {"value": str, "result": ("pending", "done", "failed", "scope_failed")},
    "mod-feed.caption.stream_title": {"value": str, "result": ("pending", "done", "failed", "scope_failed")},
    "mod-feed.caption.stream_enable": {"tool": TOOLS, "result": ("pending", "done", "failed", "scope_failed")},
    "mod-feed.caption.stream_disable": {"tool": TOOLS, "result": ("pending", "done", "failed", "scope_failed")},
    **{f"mod-feed.caption.tool.{tool}": {} for tool in TOOLS},
    **{f"mod-feed.caption.voice.{command}": {} for command in VOICE_COMMANDS},
}


def caption(key: str, **params) -> dict:
    return {"key": key, "params": params}


def sanitize_localization(value) -> dict:
    """Allow only known field/key/scalar params; discard malformed descriptors."""
    if not isinstance(value, dict):
        return {}
    clean = {}
    for field in ("text", "action"):
        descriptor = value.get(field)
        if not isinstance(descriptor, dict):
            continue
        key = descriptor.get("key")
        if not isinstance(key, str) or key not in CAPTION_PARAMS:
            continue
        params = descriptor.get("params", {})
        if not isinstance(params, dict):
            continue
        safe = {}
        for name, kind in CAPTION_PARAMS[key].items():
            item = params.get(name)
            if kind is str and isinstance(item, str) and len(item) <= 200:
                safe[name] = item
            elif kind is int and type(item) is int and abs(item) <= 1_000_000_000:
                safe[name] = item
            elif isinstance(kind, tuple) and isinstance(item, str) and item in kind:
                safe[name] = item
            else:
                break
        else:
            clean[field] = caption(key, **safe)
    return clean


def stream_localization(tool: str, params: dict, result: str) -> dict:
    if tool in ("category", "ai_category"):
        text = caption("mod-feed.caption.stream_category", value=str(params.get("game_name", "?")), result=result)
    elif tool == "title":
        text = caption("mod-feed.caption.stream_title", value=str(params.get("title") or "")[:60], result=result)
    else:
        text = caption("mod-feed.caption.stream_enable" if params.get("enabled", True) else "mod-feed.caption.stream_disable",
                       tool=tool, result=result)
    return {"text": text, "action": caption(f"mod-feed.caption.tool.{tool}")}
