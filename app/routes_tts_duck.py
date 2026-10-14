"""v13 §3 TTS duck-settings — вынесено из app/routes.py (P5-сплит, PLAN.md).

Декорирует ОБЩИЙ router из app.routes; импортируется ВНИЗУ routes.py.
_ensure_duck_settings реэкспортируется обратно в app.routes (её импортируют tests
и app/server.py hook).
"""
from fastapi import Request

from app.database import get_db
import os

from fastapi import HTTPException, Response

from app.database import get_db, get_setting
from app.routes import router  # noqa: E402


# ====================================================================
# v13 §3 WIDGETS_PLAN: налаштування авто-мовчання TTS (duck_start).
# ====================================================================
#
# Глобальна таблиця ``tts_duck_settings`` (event_kind, enabled, duration_ms).
# Створюється ліниво при першому GET через ``_ensure_duck_settings``.
# Hook в on_eventsub_event (app/server.py) викликає widget_bus.duck_start
# для кожного типу події, який enabled=1 і duration_ms > 0.


async def _ensure_duck_settings(db) -> list[dict]:
    """Створює таблицю tts_duck_settings (idempotent) і повертає всі рядки.

    Дефолтні значення: subscribe=8000, cheer=8000, raid=10000, redemption=6000,
    follow=0 (вимкнено).
    """
    await db.execute("""
        CREATE TABLE IF NOT EXISTS tts_duck_settings (
            event_kind TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            duration_ms INTEGER DEFAULT 8000
        )
    """)
    for kind, ms in (
        ("subscribe", 8000),
        ("cheer", 8000),
        ("raid", 10000),
        ("redemption", 6000),
        ("follow", 0),
        ("streamer_speech", 2000),
    ):
        await db.execute(
            "INSERT OR IGNORE INTO tts_duck_settings (event_kind, enabled, duration_ms) "
            "VALUES (?, 1, ?)",
            (kind, ms),
        )
    await db.commit()
    cur = await db.execute("SELECT event_kind, enabled, duration_ms FROM tts_duck_settings ORDER BY event_kind")
    return [dict(r) for r in await cur.fetchall()]


@router.get("/api/tts/duck-settings")
async def get_tts_duck_settings() -> dict:
    """Повертає список подій з enabled/duration_ms та загальні параметри ducking."""
    db = await get_db()
    try:
        rows = await _ensure_duck_settings(db)
        from app.database import get_setting
        vol = await get_setting("tts_duck_volume_percent", "15")
        rec = await get_setting("tts_duck_recovery_ms", "1200")
        try:
            vol_val = int(vol) if vol is not None else 15
        except (ValueError, TypeError):
            vol_val = 15
        try:
            rec_val = int(rec) if rec is not None else 1200
        except (ValueError, TypeError):
            rec_val = 1200
        return {
            "ok": True,
            "settings": rows,
            "streamer_duck_volume": vol_val,
            "streamer_duck_recovery_ms": rec_val,
        }
    finally:
        await db.close()


@router.put("/api/tts/duck-settings")
async def update_tts_duck_settings(request: Request) -> dict:
    """Оновлює enabled/duration_ms для кожного event_kind та загальні параметри."""
    body = await request.json()
    rows = body.get("settings") or []
    if not isinstance(rows, list):
        return {"ok": False, "error": "settings must be a list"}
    db = await get_db()
    try:
        # Переконуємось, що таблиця існує (lazy create), інакше INSERT не спрацює.
        await _ensure_duck_settings(db)
        for r in rows:
            kind = str(r.get("event_kind") or "").strip()
            if not kind:
                continue
            try:
                enabled = 1 if int(r.get("enabled", 0)) else 0
            except (TypeError, ValueError):
                enabled = 0
            try:
                duration = max(0, min(60000, int(r.get("duration_ms") or 0)))
            except (TypeError, ValueError):
                duration = 0
            await db.execute(
                "UPDATE tts_duck_settings SET enabled = ?, duration_ms = ? WHERE event_kind = ?",
                (enabled, duration, kind),
            )
        await db.commit()

        from app.database import set_setting
        if "streamer_duck_volume" in body:
            try:
                vol_int = max(0, min(100, int(body["streamer_duck_volume"])))
                await set_setting("tts_duck_volume_percent", str(vol_int))
            except (ValueError, TypeError):
                pass
        if "streamer_duck_recovery_ms" in body:
            try:
                rec_int = max(100, min(10000, int(body["streamer_duck_recovery_ms"])))
                await set_setting("tts_duck_recovery_ms", str(rec_int))
            except (ValueError, TypeError):
                pass

        updated = await _ensure_duck_settings(db)
        from app.database import get_setting
        vol_cur = await get_setting("tts_duck_volume_percent", "15")
        rec_cur = await get_setting("tts_duck_recovery_ms", "1200")
        return {
            "ok": True,
            "settings": updated,
            "streamer_duck_volume": int(vol_cur or 15),
            "streamer_duck_recovery_ms": int(rec_cur or 1200),
        }
    finally:
        await db.close()


@router.post("/api/tts/duck-test")
async def test_tts_duck(request: Request) -> dict:
    """Тестовий запуск ducking на кілька секунд."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    duration = int(body.get("duration_ms") or 3000)
    channel = str(body.get("channel") or "").strip().lower()
    try:
        from app.widget_bus import duck_start
        await duck_start(source="test_duck", channel=channel, reason="manual_test", duration_ms=duration)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "duration_ms": duration}


@router.get("/api/voice-clones")
async def list_voice_clones():
    db = await get_db()
    try:
        cur = await db.execute("SELECT id, name, provider, voice_id, lang, sample_path, status, created_at FROM voice_clones ORDER BY name")
        rows = await cur.fetchall()
        return {"ok": True, "clones": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.post("/api/voice-clones")
async def create_voice_clone(payload: dict):
    """Register a local sample or an external provider voice.

    Actual XTTS/Coqui/F5/ElevenLabs synthesis is performed by the configured
    TTS adapter; this endpoint keeps the clone lifecycle provider-aware.
    """
    import base64
    from app.voice_clone import save_clone_sample

    name = str(payload.get("name") or "").strip()
    provider = str(payload.get("provider") or "xtts").strip().lower()
    # Existing databases constrain provider values; XTTS is the local adapter
    # umbrella and can be configured to use Coqui/F5-TTS in the runtime.
    if provider not in {"xtts", "elevenlabs", "piper", "external", "playht"}:
        return {"ok": False, "error": "unsupported clone provider"}
    if not name:
        return {"ok": False, "error": "name is required"}
    sample_path = ""
    sample_b64 = str(payload.get("sample_b64") or "").strip()
    if sample_b64:
        try:
            raw = base64.b64decode(sample_b64, validate=True)
            sample_path = save_clone_sample(name, raw, str(payload.get("sample_ext") or ".wav"))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    voice_id = str(payload.get("voice_id") or "")
    if provider == "elevenlabs" and sample_path:
        api_key = await get_setting("tts_elevenlabs_api_key", "") or os.getenv("ELEVENLABS_API_KEY", "")
        if not api_key:
            return {"ok": False, "error": "ElevenLabs API key is not configured in Settings"}
        try:
            import httpx
            with open(sample_path, "rb") as sample:
                async with httpx.AsyncClient(timeout=90) as client:
                    response = await client.post(
                        "https://api.elevenlabs.io/v1/voices/add",
                        headers={"xi-api-key": api_key},
                        data={"name": name, "description": "Voice clone created from the control panel"},
                        files={"files": (os.path.basename(sample_path), sample, "audio/wav")},
                    )
            if response.status_code >= 400:
                return {"ok": False, "error": f"ElevenLabs error {response.status_code}: {response.text[:300]}"}
            voice_id = response.json().get("voice_id", "")
            if not voice_id:
                return {"ok": False, "error": "ElevenLabs did not return a voice_id"}
        except Exception as exc:
            return {"ok": False, "error": f"ElevenLabs connection failed: {exc}"}
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO voice_clones (name, provider, voice_id, external_api_url, sample_path, lang, status, uploaded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ready', ?)",
            (name, provider, voice_id, str(payload.get("external_api_url") or ""),
             sample_path, str(payload.get("lang") or "ru"), str(payload.get("uploaded_by") or "panel")),
        )
        await db.commit()
        cur = await db.execute("SELECT id, name, provider, voice_id, lang, sample_path, status, created_at FROM voice_clones WHERE name = ?", (name,))
        return {"ok": True, "clone": dict(await cur.fetchone())}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        await db.close()


@router.delete("/api/voice-clones/{clone_id}")
async def delete_voice_clone(clone_id: int):
    db = await get_db()
    try:
        cur = await db.execute("DELETE FROM voice_clones WHERE id = ?", (clone_id,))
        await db.commit()
        return {"ok": cur.rowcount > 0}
    finally:
        await db.close()


@router.post("/api/voice-clones/{clone_id}/preview")
async def preview_voice_clone(clone_id: int, payload: dict):
    """Synthesize a short preview using the selected clone provider."""
    text = str(payload.get("text") or "Привет, чат!").strip()[:500]
    if not text:
        return {"ok": False, "error": "text is required"}
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM voice_clones WHERE id = ?", (clone_id,))
        clone = await cur.fetchone()
        if not clone:
            raise HTTPException(status_code=404, detail="voice clone not found")
        provider_name = clone["provider"]
        from app.tts_engine import ElevenLabsProvider, PiperProvider, WebSpeechProvider, XTTSProvider
        if provider_name == "elevenlabs":
            cur = await db.execute("SELECT value FROM settings WHERE key IN ('tts_elevenlabs_api_key', 'elevenlabs_api_key') ORDER BY key LIMIT 1")
            key_row = await cur.fetchone()
            from app.security import decrypt_token
            key = decrypt_token(key_row["value"]) if key_row else ""
            key = key or os.getenv("ELEVENLABS_API_KEY", "")
            if not key:
                return {"ok": False, "error": "ElevenLabs API key is not configured"}
            provider = ElevenLabsProvider(key)
            mime = "audio/mpeg"
        elif provider_name == "xtts":
            # §12.2: движок клона выбирается настройкой tts_clone_engine
            engine_row = await db.execute("SELECT value FROM settings WHERE key = 'tts_clone_engine'")
            engine = ((await engine_row.fetchone()) or {"value": "xtts"})["value"]
            if engine == "f5tts":
                from app.tts_engine import F5TTSProvider
                provider = F5TTSProvider(clone["sample_path"], clone["lang"])
            else:
                provider = XTTSProvider(clone["sample_path"], clone["lang"])
            mime = "audio/wav"
        elif provider_name == "piper":
            from app.voice_clone import find_voice_model
            model = find_voice_model(clone["voice_id"] or clone["name"])
            provider = PiperProvider(model.onnx_path if model else clone["sample_path"])
            mime = "audio/wav"
        else:
            provider = WebSpeechProvider()
            mime = "application/json"
        audio = await provider.synthesize(text, clone["voice_id"] or clone["name"], "neutral", 1.0)
        return Response(content=audio, media_type=mime, headers={"X-Voice-Clone": clone["name"]})
    finally:
        await db.close()
