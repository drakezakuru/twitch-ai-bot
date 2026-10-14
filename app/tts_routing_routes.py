"""Read-only TTS routing map for the settings panel."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends

from app.bot_roles import load_role_config
from app.database import get_db
from app.security import auth_dependency

router = APIRouter(
    prefix="/api/tts/routing-map",
    tags=["tts-routing"],
    dependencies=[Depends(auth_dependency)],
)

_AUDIO_CONSUMERS = ("tts-raw", "tts-bot", "chat-reader")
_DISPLAY_CONSUMERS = ("tts-chat-overlay",)


def _channel(value: Any) -> str:
    return str(value or "").strip().lower().lstrip("#")


def _resolved_config(bot: dict[str, Any], global_cfg: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    inherited = not bool(bot.get("provider"))
    if not inherited:
        return dict(bot), False
    merged = dict(global_cfg)
    for key in ("provider", "voice", "emotion_preset", "volume", "speed"):
        if bot.get(key) not in (None, ""):
            merged[key] = bot[key]
    merged["enabled"] = bot.get("enabled", 0)
    return merged, True


def _voice(
    provider: str,
    voice_id: str,
    labels: dict[tuple[str, str], tuple[str, str]],
    *,
    inherited: bool,
) -> dict[str, Any]:
    provider = str(provider or "web_speech")
    voice_id = str(voice_id or "")
    if not voice_id:
        label, resolution = "Provider default", "provider_default"
    elif (provider, voice_id) in labels:
        label, resolution = labels[(provider, voice_id)]
    elif provider == "web_speech":
        label, resolution = voice_id, "browser_voice_unverified"
    else:
        label, resolution = voice_id, "unknown_id"
    return {
        "provider": provider,
        "id": voice_id,
        "label": label,
        "resolution": resolution,
        "inherited": inherited,
    }


def _output() -> dict[str, Any]:
    return {
        "delivery": "shared_websocket_broadcast",
        "status": "unverified",
        "audio_consumers": list(_AUDIO_CONSUMERS),
        "display_consumers": list(_DISPLAY_CONSUMERS),
        "warning": "The server does not track which OBS Browser Sources are currently active.",
    }


async def build_tts_routing_map() -> dict[str, Any]:
    db = await get_db()
    try:
        from app.channel_points_tts import ensure_schema

        await ensure_schema(db)
        accounts = await (await db.execute(
            "SELECT id, nickname, bot_role, role_config_json FROM accounts "
            "WHERE enabled = 1 ORDER BY id"
        )).fetchall()
        channels = await (await db.execute(
            "SELECT account_id, channel_name FROM channels WHERE enabled = 1 ORDER BY id"
        )).fetchall()
        bots = await (await db.execute("SELECT * FROM tts_bot_config")).fetchall()
        global_row = await (await db.execute("SELECT * FROM tts_settings WHERE id = 1")).fetchone()
        attention = await (await db.execute(
            "SELECT account_id, tts_reply_percent FROM bot_attention_config"
        )).fetchall()
        overrides = await (await db.execute(
            "SELECT account_id, channel, overrides_json FROM channel_overrides WHERE enabled = 1"
        )).fetchall()
        rewards = await (await db.execute(
            "SELECT * FROM channel_points_tts_config"
        )).fetchall()
        presets = await (await db.execute(
            "SELECT provider, voice_id, label FROM tts_voice_presets"
        )).fetchall()
        clones = await (await db.execute(
            "SELECT provider, voice_id, name FROM voice_clones WHERE voice_id != ''"
        )).fetchall()
    finally:
        await db.close()

    global_cfg = dict(global_row) if global_row else {"provider": "web_speech", "voice": ""}
    bot_by_account = {int(row["account_id"]): dict(row) for row in bots}
    pct_by_account = {int(row["account_id"]): int(row["tts_reply_percent"] or 0) for row in attention}
    reward_by_account = {int(row["account_id"]): dict(row) for row in rewards}
    labels = {(row["provider"], row["voice_id"]): (row["label"], "preset") for row in presets}
    labels.update({(row["provider"], row["voice_id"]): (row["name"], "clone") for row in clones})
    mute_by_scope: dict[tuple[int, str], bool] = {}
    for row in overrides:
        try:
            data = json.loads(row["overrides_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            data = {}
        mute_by_scope[(int(row["account_id"]), _channel(row["channel"]))] = bool(data.get("tts_mute"))

    channels_by_account: dict[int, list[str]] = {}
    for row in channels:
        normalized = _channel(row["channel_name"])
        if normalized and normalized not in channels_by_account.setdefault(int(row["account_id"]), []):
            channels_by_account[int(row["account_id"])].append(normalized)

    rows: list[dict[str, Any]] = []
    for account_row in accounts:
        account = dict(account_row)
        account_id = int(account["id"])
        reward = reward_by_account.get(account_id, {})
        account_channels = list(channels_by_account.get(account_id, []))
        reward_channel = _channel(reward.get("channel"))
        if reward_channel and reward_channel not in account_channels:
            account_channels.append(reward_channel)
        bot = bot_by_account.get(account_id, {})
        resolved, inherited = _resolved_config(bot, global_cfg)
        bot_voice = _voice(resolved.get("provider", ""), resolved.get("voice", ""), labels, inherited=inherited)
        role = str(account.get("bot_role") or "chatter")
        role_cfg = load_role_config(account.get("role_config_json"), role)
        source = "voice_companion_reply" if role == "voice_companion" else "bot_reply"

        for channel in account_channels:
            muted = mute_by_scope.get((account_id, channel), False)
            percent = pct_by_account.get(account_id, 100)
            base = {
                "account": {"id": account_id, "nickname": account["nickname"]},
                "channel": channel,
                "obs_output": _output(),
            }
            rows.append({
                **base,
                "source": source,
                "policy": {
                    "enabled": bool(bot.get("enabled")) and not muted and percent > 0,
                    "tts_enabled": bool(bot.get("enabled")),
                    "reply_percent": percent,
                    "channel_muted": muted,
                    "role": role,
                },
                "voice": bot_voice,
            })
            if role == "moderator":
                rows.append({
                    **base,
                    "source": "moderation_announcement",
                    "policy": {"enabled": bool(bot.get("enabled")) and bool(role_cfg.get("tts_announce")),
                               "tts_enabled": bool(bot.get("enabled")),
                               "tts_announce": bool(role_cfg.get("tts_announce"))},
                    "voice": bot_voice,
                })
            for audience_source in ("twitch_moderator_message", "ordinary_chat"):
                rows.append({
                    **base,
                    "source": audience_source,
                    "policy": {"enabled": False, "reason": "not_automatically_spoken"},
                    "voice": None,
                })
            reward_voice_id = str(reward.get("voice") or "")
            reward_inherited = not bool(reward_voice_id)
            rows.append({
                **base,
                "source": "channel_points_reward",
                "policy": {
                    "enabled": bool(reward.get("enabled")) and (not reward_channel or reward_channel == channel),
                    "reward_names": str(reward.get("reward_names") or ""),
                    "storage": "legacy_per_account",
                    "configured_channel": reward_channel,
                },
                "voice": _voice(
                    resolved.get("provider", ""), reward_voice_id or resolved.get("voice", ""), labels,
                    inherited=reward_inherited,
                ),
            })

    return {"ok": True, "rows": rows, "obs_telemetry": "unavailable"}


@router.get("")
async def get_tts_routing_map() -> dict[str, Any]:
    return await build_tts_routing_map()
