"""Local, read-only catalog of registered TTS voices for owner controls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.security import auth_dependency

router = APIRouter(
    prefix="/api/tts/voice-catalog",
    tags=["tts-voice-catalog"],
    dependencies=[Depends(auth_dependency)],
)

_LABELS = {
    "piper": {"ru": "Piper", "en": "Piper", "ua": "Piper"},
    "xtts": {"ru": "Локальный XTTS", "en": "Local XTTS", "ua": "Локальний XTTS"},
    "f5": {"ru": "Локальный F5-TTS", "en": "Local F5-TTS", "ua": "Локальний F5-TTS"},
    "elevenlabs": {"ru": "Разрешённый ElevenLabs", "en": "Allowed ElevenLabs", "ua": "Дозволений ElevenLabs"},
}
_LICENSES = {
    "piper": {"id": "model-card-required", "ru": "Лицензия указана в model card конкретного голоса.", "en": "Check this voice's model card for its license.", "ua": "Перевірте ліцензію в model card цього голосу."},
    "xtts": {"id": "owner-rights-required", "ru": "Локальная модель владельца: используйте только при наличии прав и согласия.", "en": "Owner-provided local model: use only with rights and consent.", "ua": "Локальна модель власника: використовуйте лише за наявності прав і згоди."},
    "f5": {"id": "owner-rights-required", "ru": "Локальная модель владельца: используйте только при наличии прав и согласия.", "en": "Owner-provided local model: use only with rights and consent.", "ua": "Локальна модель власника: використовуйте лише за наявності прав і згоди."},
    "elevenlabs": {"id": "elevenlabs-library-terms", "ru": "Только запись, разрешённая владельцем; действуют условия Voice Library и аккаунта ElevenLabs.", "en": "Only an owner-approved record; ElevenLabs account and Voice Library terms apply.", "ua": "Лише запис, дозволений власником; діють умови Voice Library та акаунта ElevenLabs."},
}


def _entry(
    provider: str, voice_id: str, label: str, language: str, *, installed: bool, engine: str = ""
) -> dict[str, Any]:
    kind = engine if engine in _LABELS else provider if provider in _LABELS else "xtts"
    return {
        "key": f"{provider}:{voice_id}",
        "provider": provider,
        "voice_id": voice_id,
        "label": label,
        "labels": {lang: f"{_LABELS[kind][lang]}: {label}" for lang in ("ru", "en", "ua")},
        "language": language or "",
        "installed": installed,
        "engine": engine or provider,
        "license": _LICENSES[kind],
    }


async def list_voice_catalog(query: str = "") -> list[dict[str, Any]]:
    """Read registry/local files only; never enumerate a production provider."""
    db = await get_db()
    try:
        presets = await (await db.execute(
            "SELECT provider, voice_id, label, lang FROM tts_voice_presets "
            "WHERE provider IN ('piper', 'elevenlabs') ORDER BY provider, label"
        )).fetchall()
        clones = await (await db.execute(
            "SELECT provider, voice_id, name, lang FROM voice_clones "
            "WHERE status = 'ready' AND provider IN ('piper', 'xtts', 'elevenlabs') "
            "AND voice_id != '' ORDER BY name"
        )).fetchall()
        engine_row = await (await db.execute(
            "SELECT value FROM settings WHERE key = 'tts_clone_engine'"
        )).fetchone()
    finally:
        await db.close()

    clone_engine = str(engine_row["value"] if engine_row else "xtts").lower()
    entries = [_entry(str(row["provider"]), str(row["voice_id"]), str(row["label"]), str(row["lang"]), installed=True)
               for row in presets]
    for row in clones:
        provider = str(row["provider"])
        engine = ""
        if provider == "xtts" and clone_engine == "f5tts":
            engine = "f5"
        entries.append(_entry(provider, str(row["voice_id"]), str(row["name"]), str(row["lang"]), installed=True, engine=engine))

    # Uploaded Piper models are local files, not cloud/provider inventory.
    from app.voice_clone import list_voice_models
    for model in list_voice_models():
        entries.append(_entry("piper", model.name, model.name, model.language, installed=model.exists()))

    unique = {entry["key"]: entry for entry in entries}
    needle = str(query or "").strip().lower()
    result = sorted(unique.values(), key=lambda entry: (entry["provider"], entry["label"].lower()))
    if needle:
        result = [entry for entry in result if needle in " ".join((entry["provider"], entry["voice_id"], entry["label"], entry["language"])).lower()]
    return result


@router.get("")
async def api_list_voice_catalog(query: str = Query("", max_length=100)) -> dict[str, Any]:
    return {"ok": True, "voices": await list_voice_catalog(query)}
