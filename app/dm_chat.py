"""Panel conversation routed through the bot's public Twitch channel.

The legacy Whisper/vision helpers remain available for compatibility while Q9 is
open, but the W2 UI and ``dm_send`` contract accept text only.  Both the owner's
message and the generated answer are posted by the connected bot to Twitch; the
answer can additionally be published to the OBS TTS overlay.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends

from app.database import get_db
from app.security import auth_dependency

logger = logging.getLogger("twitchbot")

router = APIRouter(dependencies=[Depends(auth_dependency)])

# (account_id) -> [{role: user|bot, text, ts, kind: text|voice|photo}]
_DM_HISTORY: dict[int, list[dict]] = {}
_DM_HISTORY_MAX = 200
_DM_KEY_PREFIX = "dm:"


def _history_key(account_id: int) -> str:
    return f"{_DM_KEY_PREFIX}{int(account_id)}"


def dm_history(account_id: int) -> list[dict]:
    return _DM_HISTORY.get(int(account_id), [])


def _push(account_id: int, entry: dict) -> None:
    hist = _DM_HISTORY.setdefault(int(account_id), [])
    hist.append(entry)
    if len(hist) > _DM_HISTORY_MAX:
        del hist[:-_DM_HISTORY_MAX]


async def _analyze_image_bytes(account_id: int, data: bytes, note: str) -> str:
    """Картинка от владельца → vision-модель бота (как кадр стрима)."""
    from app.ai_service import AIService
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    ai = AIService()
    prompt = (
        "Владелец бота прислал тебе картинку в личном разговоре (не со стрима). "
        "Опиши коротко, что на ней, и учти это в ответе. " + (note or "")
    )
    return await ai.analyze_image(img, prompt, account_id=account_id, channel="dm")


_whisper_model = None
_whisper_lock = None


def _get_whisper_lock():
    global _whisper_lock
    if _whisper_lock is None:
        import asyncio
        _whisper_lock = asyncio.Lock()
    return _whisper_lock


def _load_whisper_model():
    """Тот же openai-whisper, что для стрима (app/stream_vision.py)."""
    try:
        import whisper  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("openai-whisper не установлен: %s", exc)
        return None
    try:
        import os as _os
        return whisper.load_model(_os.getenv("WHISPER_MODEL_SIZE", "base") or "base")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Whisper model load failed: %s", exc)
        return None


async def _transcribe_audio(data: bytes) -> str:
    """Голос владельца → текст через локальный Whisper (CPU; 5-10 сек записи ≈ несколько секунд)."""
    import asyncio
    import tempfile
    import os as _os

    global _whisper_model
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        async with _get_whisper_lock():
            if _whisper_model is None:
                _whisper_model = await asyncio.to_thread(_load_whisper_model)
        if _whisper_model is None:
            raise RuntimeError("whisper_not_installed")

        def _run():
            res = _whisper_model.transcribe(tmp_path, fp16=False)
            return (res.get("text") or "").strip() if isinstance(res, dict) else ""

        return await asyncio.to_thread(_run)
    finally:
        if tmp_path:
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass


async def _tts_speak(account_id: int, text: str) -> str:
    """Озвучка ответа (если у бота включён TTS). Возвращает audio b64 или ''.

    Использует тот же per-bot конфиг и провайдеров, что OBS-озвучка
    (tts_engine._get_tts_config + synthesize), но возвращает байты вместо
    отправки в виджет."""
    try:
        from app.tts_engine import get_tts_engine
        engine = get_tts_engine()
        cfg = await engine._get_tts_config(account_id)
        if not cfg.get("enabled", 0):
            return ""
        provider_name = cfg.get("provider") or "web_speech"
        provider = await engine._get_provider(provider_name, account_id)
        if provider is None:
            return ""
        audio = await provider.synthesize(
            text, cfg.get("voice") or "", cfg.get("emotion_preset") or "neutral",
            float(cfg.get("speed") or 1.0),
        )
        return base64.b64encode(audio).decode("ascii") if audio else ""
    except Exception as exc:
        logger.debug("dm tts error #%s: %s", account_id, exc)
        return ""


@router.post("/api/accounts/{account_id}/dm")
async def dm_send(account_id: int, data: dict[str, Any]) -> dict:
    """Post panel text and the bot answer to a connected Twitch channel."""
    from app.chat_prompt_blocks import ChatPromptBlocksMixin
    from app.server import ai_service, bot_manager, chat_analyzer

    text = str(data.get("text") or "").strip()
    channel = str(data.get("channel") or "").strip().lower().lstrip("#")
    if not text:
        return {"ok": False, "error": "empty_input"}
    if not channel:
        return {"ok": False, "error": "channel_required"}

    db = await get_db()
    try:
        cur = await db.execute("SELECT id, nickname FROM accounts WHERE id = ?", (account_id,))
        acc = await cur.fetchone()
        ch_cur = await db.execute(
            "SELECT enabled FROM channels WHERE account_id = ? AND channel_name = ?",
            (account_id, channel),
        )
        configured_channel = await ch_cur.fetchone()
    finally:
        await db.close()
    if not acc:
        return {"ok": False, "error": "not_found"}
    if not configured_channel or not configured_channel["enabled"]:
        return {"ok": False, "error": "channel_not_configured"}
    nickname = acc["nickname"]

    sent = await bot_manager.send_message_detailed(account_id, channel, text)
    if not sent.get("ok"):
        return {
            "ok": False,
            "error": str(sent.get("reason") or "twitch_send_failed"),
            "detail": str(sent.get("error") or "")[:200],
        }
    _push(account_id, {"role": "user", "username": "owner", "text": text,
                       "ts": time.time(), "kind": "twitch", "channel": channel})

    system = ""
    try:
        system = await ChatPromptBlocksMixin()._load_persona_block(account_id, channel)  # type: ignore[arg-type]
    except Exception as exc:
        logger.debug("panel chat persona block #%s: %s", account_id, exc)
    if not system:
        system = (
            f"Ты — Twitch-бот {nickname}. Отвечай в публичном чате канала "
            "коротко и живо, сохраняя свой характер."
        )
    history = "\n".join(
        f"[{'бот' if m['role'] == 'bot' else 'владелец'}] {m['text']}"
        for m in dm_history(account_id)[-20:-1]
        if m.get("channel") == channel
    )
    if history:
        system += "\n\nНедавний разговор в панели:\n" + history

    reply = (await ai_service.generate_text(
        text, system=system, account_id=account_id, channel=channel,
    ) or "").strip()
    if not reply:
        return {"ok": False, "error": "ai_empty", "message_sent": True}

    reply_sent = await bot_manager.send_message_detailed(account_id, channel, reply)
    if not reply_sent.get("ok"):
        return {
            "ok": False, "error": str(reply_sent.get("reason") or "twitch_reply_failed"),
            "detail": str(reply_sent.get("error") or "")[:200], "message_sent": True,
        }
    _push(account_id, {"role": "bot", "username": nickname, "text": reply,
                       "ts": time.time(), "kind": "twitch", "channel": channel})
    try:
        from app.user_memory import add_message_history
        await add_message_history(account_id, channel, "owner", text, is_bot=False)
        await add_message_history(account_id, channel, nickname, reply, is_bot=True)
    except Exception as exc:
        logger.debug("panel chat memory #%s: %s", account_id, exc)

    spoken = False
    if bool(data.get("speak_reply")) and await chat_analyzer._tts_should_speak(account_id, channel):
        try:
            from app.tts_engine import get_tts_engine
            await get_tts_engine().speak(account_id, channel, reply)
            spoken = True
        except Exception as exc:
            logger.debug("panel chat TTS #%s: %s", account_id, exc)
    return {"ok": True, "reply": reply, "channel": channel, "spoken": spoken}


@router.get("/api/accounts/{account_id}/dm/history")
async def dm_history_route(account_id: int) -> dict:
    return {"ok": True, "messages": dm_history(account_id)}


@router.post("/api/accounts/{account_id}/dm/reset")
async def dm_reset(account_id: int) -> dict:
    _DM_HISTORY.pop(int(account_id), None)
    return {"ok": True}


@router.post("/api/dm/transcribe")
async def dm_transcribe(data: dict[str, Any]) -> dict:
    """Голос → текст без отправки боту (для чекбокса «сначала послушать»)."""
    if not data.get("audio_b64"):
        return {"ok": False, "error": "empty_input"}
    try:
        raw = base64.b64decode(str(data["audio_b64"]).split(",")[-1])
        heard = await _transcribe_audio(raw)
        return {"ok": True, "text": heard}
    except Exception as exc:
        return {"ok": False, "error": "transcribe_error", "detail": str(exc)[:200]}
