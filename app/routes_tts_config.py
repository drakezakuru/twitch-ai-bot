"""tts_config — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from fastapi import Request

from app.database import get_db
import os
from app.routes import router  # noqa: E402


# ===================== v11: TTS CONFIG =====================

_TTS_BOT_DEFAULTS = {
    "provider": "",
    "voice": "",
    "emotion_preset": "neutral",
    "volume": 1.0,
    "speed": 1.0,
    "enabled": 0,
    "widget_color": "#FFD700",
    "widget_emoji": "🎙️",
    "emoji_prefix": "",
    "emoji_suffix": "",
}

@router.get("/api/tts/config")
async def get_tts_global_config():
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM tts_settings WHERE id = 1")
        row = await cur.fetchone()
        config = dict(row) if row else {}
        cur = await db.execute("SELECT value FROM settings WHERE key = 'tts_elevenlabs_api_key'")
        key_row = await cur.fetchone()
        config["elevenlabs_key_set"] = bool(key_row and key_row["value"]) or bool(os.getenv("ELEVENLABS_API_KEY", "").strip())
        for setting_key, config_key in (("tts_xtts_model", "xtts_model"), ("tts_xtts_device", "xtts_device")):
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (setting_key,))
            row = await cur.fetchone()
            config[config_key] = row["value"] if row else ""
        return {"ok": True, "config": config}
    finally:
        await db.close()


@router.put("/api/tts/config")
async def update_tts_global_config(request: Request):
    body = await request.json()
    provider = str(body.get("provider", "web_speech")).strip().lower()
    if provider not in {"web_speech", "piper", "elevenlabs"}:
        return {"ok": False, "error": "unsupported TTS provider"}
    try:
        speed = max(0.25, min(4.0, float(body.get("speed", 1.0))))
        volume = max(0.0, min(1.0, float(body.get("volume", 1.0))))
    except (TypeError, ValueError):
        return {"ok": False, "error": "speed and volume must be numbers"}
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tts_settings (id, provider, voice, speed, volume, updated_at) "
            "VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, voice=excluded.voice, "
            "speed=excluded.speed, volume=excluded.volume, updated_at=CURRENT_TIMESTAMP",
            (
                provider,
                body.get("voice", ""),
                speed,
                volume,
            ),
        )
        await db.commit()
        if body.get("elevenlabs_api_key"):
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('tts_elevenlabs_api_key', ?)",
                (str(body["elevenlabs_api_key"]).strip(),),
            )
            await db.commit()
        for field, setting_key in (("xtts_model", "tts_xtts_model"), ("xtts_device", "tts_xtts_device")):
            if field in body:
                value = str(body[field] or "").strip()
                if field == "xtts_device" and value not in {"cpu", "cuda"}:
                    value = "cpu"
                await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (setting_key, value))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.get("/api/accounts/{account_id}/tts-config")
async def get_tts_bot_config(account_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM tts_bot_config WHERE account_id = ?", (account_id,)
        )
        row = await cur.fetchone()
        if row:
            return {"ok": True, "configured": True, "config": dict(row)}
        config = dict(_TTS_BOT_DEFAULTS)
        global_row = await (await db.execute(
            "SELECT provider, voice, volume, speed FROM tts_settings WHERE id = 1"
        )).fetchone()
        if global_row:
            config.update(dict(global_row))
        else:
            config["provider"] = "web_speech"
        return {"ok": True, "configured": False, "config": config}
    finally:
        await db.close()


@router.put("/api/accounts/{account_id}/tts-config")
async def update_tts_bot_config(account_id: int, request: Request):
    body = await request.json()
    db = await get_db()
    try:
        # v12: додаємо speed в per-bot TTS конфіг
        await db.execute(
            "INSERT INTO tts_bot_config (account_id, provider, voice, emotion_preset, volume, speed, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET provider=excluded.provider, voice=excluded.voice, "
            "emotion_preset=excluded.emotion_preset, volume=excluded.volume, speed=excluded.speed, enabled=excluded.enabled",
            (
                account_id,
                body.get("provider", ""),
                body.get("voice", ""),
                body.get("emotion_preset", "neutral"),
                body.get("volume", 1.0),
                body.get("speed", 1.0),
                body.get("enabled", 0),
            ),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.get("/api/accounts/{account_id}/tts-last")
async def tts_last_status(account_id: int) -> dict:
    """§7.1 §12.1: статус последнего TTS-синтеза бота (+ причина ошибки)."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT level, message, details, created_at FROM bot_logs "
            "WHERE account_id = ? AND category = 'tts' ORDER BY id DESC LIMIT 1",
            (account_id,),
        )
        row = await cur.fetchone()
        if not row:
            return {"ok": True, "has": False}
        import json as _json
        try:
            details = _json.loads(row["details"] or "{}")
        except Exception:
            details = {}
        return {"ok": True, "has": True, "level": row["level"], "message": row["message"],
                "details": details, "created_at": row["created_at"]}
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/tts-test")
async def tts_test_speak(account_id: int, data: dict) -> dict:
    """§7.1 §12.1: TTS test — озвучка текста голосом ЭТОГО бота (per-bot конфиг).

    Звук идёт в OBS TTS-оверлей (broadcast), как обычная озвучка бота."""
    text = str(data.get("text") or "").strip()[:300]
    if not text:
        return {"error": "text_required"}
    channel = str(data.get("channel") or "").strip().lower().lstrip("#")
    if not channel:
        return {"error": "channel_required"}
    from app.tts_engine import get_tts_engine
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT channel_name FROM channels WHERE account_id = ? "
            "AND lower(ltrim(channel_name,'#')) = ? AND enabled = 1 LIMIT 1",
            (account_id, channel))
        row = await cur.fetchone()
    finally:
        await db.close()
    if not row:
        return {"error": "scope_not_found"}
    channel = str(row["channel_name"] or "").strip().lower().lstrip("#")
    try:
        await get_tts_engine().speak(account_id, channel, text)
        return {"ok": True, "channel": channel}
    except Exception as exc:
        return {"error": str(exc)[:200]}
@router.get("/api/tts/voices")
async def list_tts_voices():
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM tts_voice_presets ORDER BY provider, label")
        rows = await cur.fetchall()
        return {"ok": True, "voices": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.post("/api/accounts/{account_id}/tts-preview")
async def tts_preview(account_id: int, request: Request) -> dict:
    """Предпрослушивание голоса бота в браузере без необходимости OBS.

    Возвращает аудио (base64) для серверных синтезаторов (Piper, ElevenLabs, XTTS)
    или JSON инструкцию для Web Speech API браузера.
    """
    import base64
    from app.tts_engine import get_tts_engine, EMOTION_PARAMS, _provider_voice_name

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    text = str(body.get("text") or "Привет! Это проверка голоса бота.").strip()[:300]
    provider_name = str(body.get("provider") or "").strip().lower()
    voice = str(body.get("voice") or "").strip()
    emotion = str(body.get("emotion_preset") or body.get("emotion") or "neutral").strip()
    try:
        speed = max(0.25, min(4.0, float(body.get("speed", 1.0))))
        volume = max(0.0, min(1.0, float(body.get("volume", 1.0))))
    except (TypeError, ValueError):
        speed, volume = 1.0, 1.0

    engine = get_tts_engine()

    # Если провайдер не передан явно — берём текущий конфиг бота / глобальный
    if not provider_name:
        cfg = await engine._get_tts_config(account_id)
        provider_name = (cfg.get("provider") or "web_speech").strip().lower()
        if not voice:
            voice = str(cfg.get("voice") or "").strip()
        if not emotion:
            emotion = str(cfg.get("emotion_preset") or "neutral").strip()

    if provider_name == "web_speech":
        params = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["neutral"])
        rate = round(params["web_speech_rate"] * speed, 2)
        pitch = round(params["web_speech_pitch"], 2)
        return {
            "ok": True,
            "mode": "web_speech",
            "text": text,
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
            "volume": volume,
        }

    token = _provider_voice_name.set(voice)
    try:
        provider = await engine._get_provider(provider_name, account_id)
    finally:
        _provider_voice_name.reset(token)

    if provider is None:
        return {"ok": False, "error": f"Провайдер '{provider_name}' недоступен на сервере"}

    try:
        audio_bytes = await provider.synthesize(text, voice, emotion, speed)
        mime = "audio/mpeg" if provider_name == "elevenlabs" else "audio/wav"
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        return {
            "ok": True,
            "mode": "audio",
            "mime": mime,
            "audio_b64": audio_b64,
            "volume": volume,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/api/accounts/{account_id}/tts-test-obs")
async def tts_test_obs(account_id: int, request: Request) -> dict:
    """Отправляет тестовое TTS-событие в подключённые OBS Browser Source оверлеи."""
    import base64
    from app.tts_engine import get_tts_engine, _provider_voice_name, broadcast_tts_event
    from app.database import get_db

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    text = str(body.get("text") or "Тест звука в OBS: проверка голоса бота.").strip()[:300]
    provider_name = str(body.get("provider") or "").strip().lower()
    voice = str(body.get("voice") or "").strip()
    emotion = str(body.get("emotion_preset") or body.get("emotion") or "neutral").strip()
    channel = str(body.get("channel") or "").strip().lower().lstrip("#")

    try:
        speed = max(0.25, min(4.0, float(body.get("speed", 1.0))))
        volume = max(0.0, min(1.0, float(body.get("volume", 1.0))))
    except (TypeError, ValueError):
        speed, volume = 1.0, 1.0

    engine = get_tts_engine()

    db = await get_db()
    nickname = f"Bot #{account_id}"
    try:
        cur = await db.execute("SELECT nickname FROM accounts WHERE id = ?", (account_id,))
        row = await cur.fetchone()
        if row:
            nickname = row["nickname"] or nickname
        if not channel:
            c_cur = await db.execute("SELECT channel_name FROM channels WHERE account_id = ? AND enabled = 1 LIMIT 1", (account_id,))
            c_row = await c_cur.fetchone()
            if c_row:
                channel = str(c_row["channel_name"] or "").strip().lower().lstrip("#")
    finally:
        await db.close()

    if not provider_name:
        cfg = await engine._get_tts_config(account_id)
        provider_name = (cfg.get("provider") or "web_speech").strip().lower()
        if not voice:
            voice = str(cfg.get("voice") or "").strip()
        if not emotion:
            emotion = str(cfg.get("emotion_preset") or "neutral").strip()

    audio_b64 = ""
    mime = ""
    if provider_name != "web_speech":
        token = _provider_voice_name.set(voice)
        try:
            provider = await engine._get_provider(provider_name, account_id)
        finally:
            _provider_voice_name.reset(token)

        if provider is not None:
            try:
                audio_bytes = await provider.synthesize(text, voice, emotion, speed)
                mime = "audio/mpeg" if provider_name == "elevenlabs" else "audio/wav"
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
            except Exception as exc:
                return {"ok": False, "error": f"Ошибка синтеза: {exc}"}

    await broadcast_tts_event(
        account_id=account_id,
        channel=channel,
        text=text,
        emotion=emotion,
        audio_b64=audio_b64,
        mime=mime,
        provider=provider_name,
        volume=volume,
        speaker=nickname,
        speaker_kind="bot",
        display_text=f"🔊 [OBS Test] {text}",
    )
    return {
        "ok": True,
        "broadcasted": True,
        "speaker": nickname,
        "provider": provider_name,
        "channel": channel,
        "text": text,
    }


# ===================== v10.5: TEMPORARY TTS MUTE (CINEMATIC MUTE) =====================

@router.post("/api/tts/mute")
async def api_tts_mute(request: Request) -> dict:
    from app.tts_mute_state import set_tts_mute
    channel = ""
    minutes = 5.0
    try:
        body = await request.json()
        if isinstance(body, dict):
            channel = str(body.get("channel") or "")
            minutes = float(body.get("minutes") or 5.0)
    except Exception:
        pass
    if not channel and "channel" in request.query_params:
        channel = request.query_params.get("channel", "")
    if "minutes" in request.query_params:
        try:
            minutes = float(request.query_params.get("minutes", 5.0))
        except (ValueError, TypeError):
            pass
    return set_tts_mute(channel=channel, minutes=minutes)


@router.post("/api/tts/unmute")
async def api_tts_unmute(request: Request) -> dict:
    from app.tts_mute_state import clear_tts_mute
    channel = ""
    try:
        body = await request.json()
        if isinstance(body, dict):
            channel = str(body.get("channel") or "")
    except Exception:
        pass
    if not channel and "channel" in request.query_params:
        channel = request.query_params.get("channel", "")
    return clear_tts_mute(channel=channel)


@router.get("/api/tts/mute/status")
async def api_tts_mute_status(channel: str = "") -> dict:
    from app.tts_mute_state import get_tts_mute_status
    return get_tts_mute_status(channel=channel)
