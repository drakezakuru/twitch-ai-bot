"""TTS Engine — озвучування відповідей бота через OBS.

Провайдери:
- Web Speech API (безкоштовно, через Browser Source)
- Piper TTS (локально, ONNX моделі)
- ElevenLabs API (хмара, висока якість)

Прогресивна деградація: ElevenLabs → Piper → Web Speech.

WebSocket подія для OBS Widget:
{
    "type": "tts",
    "account_id": 1,
    "channel": "#test",
    "text": "привіт чат",
    "emotion": "happy",
    "provider": "elevenlabs",
    "audio_b64": "...",
    "mime": "audio/mpeg"
}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import io
import os
import itertools
import heapq
import tempfile
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Protocol

from app.database import get_db

_provider_voice_name: ContextVar[str] = ContextVar("provider_voice_name", default="")

logger = logging.getLogger(__name__)

# ── Емоції → параметри голосу ─────────────────────────────────────

EMOTION_PARAMS: dict[str, dict[str, Any]] = {
    "neutral":  {"web_speech_rate": 1.0, "web_speech_pitch": 1.0, "piper_speed": 1.0, "elevenlabs_stability": 0.5},
    "angry":    {"web_speech_rate": 0.9, "web_speech_pitch": 0.8, "piper_speed": 0.9, "elevenlabs_stability": 0.3},
    "sad":      {"web_speech_rate": 0.85, "web_speech_pitch": 0.9, "piper_speed": 0.85, "elevenlabs_stability": 0.6},
    "happy":    {"web_speech_rate": 1.15, "web_speech_pitch": 1.2, "piper_speed": 1.15, "elevenlabs_stability": 0.4},
    "surprised":{"web_speech_rate": 1.2, "web_speech_pitch": 1.4, "piper_speed": 1.2, "elevenlabs_stability": 0.3},
    "fear":     {"web_speech_rate": 1.1, "web_speech_pitch": 1.1, "piper_speed": 1.1, "elevenlabs_stability": 0.4},
}


# ── Provider Protocol ──────────────────────────────────────────────

class TTSProvider(Protocol):
    async def synthesize(self, text: str, voice: str, emotion: str, speed: float) -> bytes: ...


# ── Web Speech Provider ────────────────────────────────────────────

class WebSpeechProvider:
    """Не синтезує на сервері — повертає JSON для Browser Source."""

    async def synthesize(self, text: str, voice: str, emotion: str, speed: float) -> bytes:
        params = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["neutral"])
        rate = params["web_speech_rate"] * speed
        pitch = params["web_speech_pitch"]
        return json.dumps({
            "mode": "web_speech",
            "text": text,
            "voice": voice,
            "rate": round(rate, 2),
            "pitch": round(pitch, 2),
        }).encode()


# ── Piper Provider ─────────────────────────────────────────────────

class PiperProvider:
    """Локальний TTS через piper-tts (ONNX моделі)."""

    def __init__(self, model_path: str | None = None):
        self._model_path = model_path
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from piper import PiperVoice
            self._model = PiperVoice.load(self._model_path) if self._model_path else None
        except ImportError:
            logger.warning("piper-tts не встановлено")
        except Exception as exc:
            logger.warning("Piper load failed: %s", exc)

    async def synthesize(self, text: str, voice: str, emotion: str, speed: float) -> bytes:
        self._load_model()
        if self._model is None:
            raise RuntimeError("Piper model not available")
        params = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["neutral"])
        # Piper не підтримує speed напряму — використовуємо audio_config
        wav = await asyncio.to_thread(self._model.synthesize, text)
        return wav


class OmniVoiceProvider:
    """Optional experimental local TTS/voice clone (k2-fsa/OmniVoice, Apache-2.0 code).

    Heavy PyTorch/Transformers runtime stays isolated here: the import and model load
    happen lazily inside a worker thread and never block panel startup. Absence of the
    optional package degrades to the regular Piper/Web Speech fallback chain.
    """

    # Versioned source pinning (spec: fixed revisions before any manual --ml install).
    SOURCE_REPO = "k2-fsa/OmniVoice"
    TOKENIZER_ID = "eustlb/higgs-audio-v2-tokenizer"
    # Owner decision 10.09.2026: weights license confirmed as permitted (see
    # omnivoice/LICENSE_REVIEW.md). First production use still happens on the owner's
    # device via a manual --ml install, never inside the panel sandbox.
    weights_license_confirmed = True

    def __init__(self, model_path: str | None = None):
        self._model_path = model_path
        self._model = None
        self._load_failed = False

    def _load_model(self):
        if self._model is not None or self._load_failed:
            return
        try:
            from omnivoice import OmniVoiceTTS  # isolated heavy import (torch/transformers)
            self._model = OmniVoiceTTS.from_pretrained(self._model_path) if self._model_path else OmniVoiceTTS()
        except ImportError:
            logger.warning("omnivoice не встановлено (optional --ml extra)")
            self._load_failed = True
        except Exception as exc:
            logger.warning("OmniVoice load failed: %s", exc)
            self._load_failed = True

    async def synthesize(self, text: str, voice: str, emotion: str, speed: float) -> bytes:
        self._load_model()
        if self._model is None:
            raise RuntimeError("OmniVoice model not available")
        return await asyncio.to_thread(self._model.synthesize, text, voice=voice)


class XTTSProvider:
    """Optional local zero-shot clone adapter.

    The heavy XTTS/Coqui package is imported only when this provider is used;
    installations that only use Piper or Web Speech do not need the package.
    """

    def __init__(self, sample_path: str, language: str = "ru", model_name: str = "", device: str = "cpu"):
        self.sample_path = sample_path
        self.language = language or "ru"
        self.model_name = model_name or os.getenv("XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
        self.device = device if device in {"cpu", "cuda"} else "cpu"
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from TTS.api import TTS
        except ImportError as exc:
            raise RuntimeError("XTTS is not installed; install TTS for local voice cloning") from exc
        self._model = TTS(model_name=self.model_name, progress_bar=False, gpu=self.device == "cuda")

    async def synthesize(self, text: str, voice: str, emotion: str, speed: float) -> bytes:
        if not Path(self.sample_path).is_file():
            raise RuntimeError("voice clone sample is missing")
        self._load_model()
        with tempfile.NamedTemporaryFile(suffix=".wav") as output:
            await asyncio.to_thread(
                self._model.tts_to_file,
                text=text,
                speaker_wav=self.sample_path,
                language=self.language,
                file_path=output.name,
                split_sentences=True,
            )
            return Path(output.name).read_bytes()


# ── ElevenLabs Provider ────────────────────────────────────────────

class F5TTSProvider:
    """Optional local F5-TTS zero-shot clone adapter (§12.2).

    Требует опциональный пакет ``f5-tts`` (импортируется только при
    использовании); иначе — RuntimeError с понятным сообщением (как XTTS).
    Выбор движка клона: настройка ``tts_clone_engine`` = 'xtts' | 'f5tts'.
    """

    def __init__(self, sample_path: str, language: str = "ru", model_name: str = "", device: str = "cpu"):
        self.sample_path = sample_path
        self.language = language or "ru"
        self.model_name = model_name or os.getenv("F5TTS_MODEL", "")
        self.device = device if device in {"cpu", "cuda"} else "cpu"
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return
        if not Path(self.sample_path).is_file():
            raise RuntimeError("voice clone sample is missing")
        try:
            from f5_tts.api import F5TTS
        except ImportError as exc:
            raise RuntimeError("F5-TTS is not installed; install f5-tts for local voice cloning") from exc
        kwargs = {"device": self.device}
        if self.model_name:
            kwargs["model"] = self.model_name
        self._model = F5TTS(**kwargs)

    async def synthesize(self, text: str, voice: str, emotion: str, speed: float) -> bytes:
        self._load_model()
        import numpy as np
        import wave

        def _infer() -> bytes:
            result = self._model.infer(
                ref_file=self.sample_path,
                ref_text="",
                gen_text=text,
                speed=max(0.5, min(2.0, float(speed or 1.0))),
            )
            # разные версии f5-tts возвращают (sr, wav) или (wav, sr)
            sr, wav = (result[0], result[1]) if isinstance(result[0], (int, float)) else (result[1], result[0])
            wav = np.asarray(wav, dtype=np.float32).squeeze()
            peak = float(np.max(np.abs(wav)) or 1.0)
            if peak > 1.0:
                wav = wav / peak
            pcm = (wav * 32767.0).astype(np.int16).tobytes()
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(int(sr))
                w.writeframes(pcm)
            return buf.getvalue()

        return await asyncio.to_thread(_infer)


class ElevenLabsProvider:
    """Хмарний TTS через ElevenLabs API."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def synthesize(self, text: str, voice: str, emotion: str, speed: float) -> bytes:
        import aiohttp
        params = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["neutral"])
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": params["elevenlabs_stability"],
                "similarity_boost": 0.75,
                "speed": speed,
            },
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"ElevenLabs error {resp.status}: {body}")
                return await resp.read()


# ── TTS Engine ─────────────────────────────────────────────────────

class TTSEngine:
    """Головний TTS Engine — маршрутизація між провайдерами + fallback."""

    def __init__(self):
        self._providers: dict[str, Any] = {}
        self._synthesis_limit = asyncio.Semaphore(2)
        self._queue: list[tuple[int, int, asyncio.Future]] = []
        self._queue_seq = itertools.count()
        self._queue_lock = asyncio.Lock()
        # OPS_PLAN §3: считаем ВСЕХ ожидающих озвучку (очередь + семафор).
        # Без этого очередь мгновенно «самоопустошается» (каждый ждущий сам
        # снимает свой тикет, когда он головной) и лимит len(_queue)>=100
        # никогда не срабатывает — перегруз не ловился.
        self._pending = 0
        self._init_providers()

    def _init_providers(self):
        self._providers["web_speech"] = WebSpeechProvider()
        # Piper та ElevenLabs ініціалізуються при потребі
        self._providers["piper"] = PiperProvider()
        self._providers["omnivoice"] = OmniVoiceProvider()  # optional, lazy, license-gated
        # ElevenLabs ключ береться з БД/настройок

    async def _get_tts_config(self, account_id: int) -> dict[str, Any]:
        """Отримує TTS конфіг для бота (per-bot override або глобальний).

        §6 PLAN_FEEDBACK_2908: строка бота з порожнім провайдером = «наслідувати
        глобальний» — раніше такий бот фолбекав на глобальний конфіг БЕЗ enabled
        і TTS мовчав назавжди. Тепер непорожні поля бота перемагають, порожні —
        беруться з глобальних, enabled — завжди з рядка бота (opt-in)."""
        db = await get_db()
        try:
            # Спочатку per-bot
            cur = await db.execute(
                "SELECT * FROM tts_bot_config WHERE account_id = ?", (account_id,)
            )
            bot_cfg = await cur.fetchone()
            if bot_cfg and bot_cfg["provider"]:
                return dict(bot_cfg)

            # Глобальний
            cur = await db.execute("SELECT * FROM tts_settings WHERE id = 1")
            global_cfg = await cur.fetchone()

            if bot_cfg:
                bot = dict(bot_cfg)
                if global_cfg:
                    merged = dict(global_cfg)
                    for key in ("provider", "voice", "emotion_preset", "volume", "speed"):
                        if bot.get(key) not in (None, ""):
                            merged[key] = bot[key]
                    merged["enabled"] = bot.get("enabled", 0)
                    return merged
                return bot
            return dict(global_cfg) if global_cfg else {"provider": "web_speech", "enabled": 0}
        finally:
            await db.close()

    async def speak(
        self,
        account_id: int,
        channel: str,
        text: str,
        emotion: str = "neutral",
        speaker: str = "",
        speaker_kind: str = "bot",
        display_text: str = "",
        provider_override: str = "",
        voice_override: str = "",
    ) -> None:
        """Синтезує та відправляє TTS подію в OBS через WebSocket.

        P6 PLAN.md: ``speaker`` — хто говорить (нік редиктора для TTS за бали
        канала, пусто = ім'я бота), ``speaker_kind`` — 'bot' | 'viewer',
        ``display_text`` — текст для оверлея без голосового префікса
        («Говорить Nick:»), пусто = той самий ``text``."""
        cfg = await self._get_tts_config(account_id)
        try:
            from app.server import ai_service
            if ai_service.offline_mode:
                cfg = {**cfg, "provider": "piper"}
        except Exception:
            pass
        if not cfg.get("enabled", 0):
            return

        # §8 WIDGETS_PLAN: емодзі-обгортка TTS-повідомлень.
        # Візуальна частина (overlay) бачить обгорнутий текст, у синтез
        # йде той самий обгорнутий текст — більшість TTS-двигунів просто
        # пропускають emoji, тому ризику "озвучки емодзі" немає.
        try:
            prefix = (cfg.get("emoji_prefix") or "").strip()
            suffix = (cfg.get("emoji_suffix") or "").strip()
            if prefix or suffix:
                text = f"{prefix} {text} {suffix}".strip() if prefix or suffix else text
        except Exception:
            pass

        # §1 WIDGETS_PLAN: авто-мовчання TTS при донатах/сабах/рейдах.
        # Якщо активне «hard_mute» вікно (наприклад, donate/subscribe) — TTS
        # не озвучуємо взагалі. Для м'якого duck — чекаємо залишок вікна
        # (макс. 5с) і продовжуємо; якщо перевищили — пропускаємо.
        try:
            from app.widget_bus import is_ducked, is_hard_muted, remaining_ms, request_pause_media
            if is_hard_muted(channel):
                logger.debug("TTS skipped: hard_mute active for account %d", account_id)
                return
            wait_ms = remaining_ms(channel)
            if wait_ms > 0 and wait_ms <= 5000:
                logger.debug("TTS delayed %dms by active duck (account %d)", wait_ms, account_id)
                await asyncio.sleep(wait_ms / 1000.0)
        except Exception as exc:
            logger.debug("widget_bus check failed (non-fatal): %s", exc)

        # §4 WIDGETS_PLAN: під час озвучки TTS просимо медіа-віджети поставити
        # відео/аудіо на паузу. resume_media буде вислано в finally.
        pause_sent = False
        try:
            from app.widget_bus import request_pause_media as _rpm
            await _rpm(source="tts", channel=channel, reason="tts_speak")
            pause_sent = True
        except Exception as exc:
            logger.debug("pause_media failed (non-fatal): %s", exc)

        try:
            provider_name = provider_override or cfg.get("provider", "web_speech")
            voice = voice_override or cfg.get("voice", "")
            speed = cfg.get("speed", 1.0)
            volume = cfg.get("volume", 1.0)

            token = _provider_voice_name.set(voice)
            try:
                provider = await self._get_provider(provider_name, account_id)
            finally:
                _provider_voice_name.reset(token)
            if provider is None:
                logger.warning("TTS provider '%s' not available for account %d", provider_name, account_id)
                # §7.1 §12.1: причина видна в статусе TTS бота (панель)
                try:
                    from app.bot_logs import log_per_bot
                    await log_per_bot(account_id, channel, "tts",
                                      f"TTS: провайдер '{provider_name}' недоступен",
                                      level="warning", details={"provider": provider_name})
                except Exception:
                    pass
                if provider_name == "web_speech":
                    return
                # A missing cloud/local provider must still produce an OBS event.
                provider_name = "web_speech"
                provider = self._providers["web_speech"]

            # v11: логування TTS
            try:
                from app.bot_logs import log_per_bot
                await log_per_bot(account_id, channel, "tts",
                                f"TTS ({provider_name}): {text[:100]}",
                                details={"provider": provider_name, "emotion": emotion, "voice": voice})
            except Exception:
                pass
            priority = 0 if cfg.get("priority") in ("streamer", "high", 1, True) else 10
            ticket = asyncio.get_running_loop().create_future()
            # §3 OPS_PLAN: перегруз — отменяем НОВЫЙ запрос, хвост не копим.
            async with self._queue_lock:
                if self._pending >= 100:
                    logger.warning("TTS queue overload (%d pending) — запрос отменён (account %d)",
                                   self._pending, account_id)
                    return
                self._pending += 1
                heapq.heappush(self._queue, (priority, next(self._queue_seq), ticket))
            try:
                while True:
                    if ticket.cancelled():
                        return
                    async with self._queue_lock:
                        while self._queue and self._queue[0][2].cancelled():
                            heapq.heappop(self._queue)
                        if self._queue and self._queue[0][2] is ticket:
                            heapq.heappop(self._queue)
                            ticket.set_result(True)
                            break
                    await asyncio.sleep(0.01)
                async with self._synthesis_limit:
                    audio_bytes = await provider.synthesize(text, voice, emotion, speed)
            finally:
                async with self._queue_lock:
                    self._pending -= 1
            audio_b64 = base64.b64encode(audio_bytes).decode()
            mime = "audio/mpeg" if provider_name == "elevenlabs" else "audio/wav"

            # WebSocket broadcast
            await broadcast_tts_event(
                channel=channel,
                account_id=account_id,
                text=text,
                emotion=emotion,
                audio_b64=audio_b64,
                mime=mime,
                provider=provider_name,
                volume=volume,
                speaker=speaker,
                speaker_kind=speaker_kind,
                display_text=display_text,
            )
        except Exception as exc:
            logger.warning("TTS synthesis failed for account %d: %s", account_id, exc)
            # §7.1 §12.1: статус последнего синтеза + причина ошибки (панель)
            try:
                from app.bot_logs import log_per_bot
                await log_per_bot(account_id, channel, "tts",
                                  f"TTS error ({provider_name}): {exc}",
                                  level="error", details={"error": str(exc)[:300]})
            except Exception:
                pass
            # Fallback to web_speech
            try:
                provider_name_now = cfg.get("provider", "web_speech")
            except Exception:
                provider_name_now = "web_speech"
            if provider_name_now != "web_speech":
                try:
                    fb = WebSpeechProvider()
                    audio_bytes = await fb.synthesize(text, voice, emotion, speed)
                    audio_b64 = base64.b64encode(audio_bytes).decode()
                    await broadcast_tts_event(
                        channel=channel,
                        account_id=account_id,
                        text=text,
                        emotion=emotion,
                        audio_b64=audio_b64,
                        mime="application/json",
                        provider="web_speech",
                        volume=cfg.get("volume", 1.0),
                        speaker=speaker,
                        speaker_kind=speaker_kind,
                        display_text=display_text,
                    )
                except Exception as fb_exc:
                    logger.warning("TTS fallback also failed: %s", fb_exc)
        finally:
            if pause_sent:
                try:
                    from app.widget_bus import request_resume_media as _rrm
                    await _rrm(source="tts", channel=channel, reason="tts_done")
                except Exception as exc:
                    logger.debug("resume_media failed (non-fatal): %s", exc)

    async def _get_provider(self, name: str, account_id: int) -> TTSProvider | None:
        if name == "web_speech":
            return self._providers.get("web_speech")
        elif name in ("piper", "xtts"):
            db = await get_db()
            try:
                requested_voice = _provider_voice_name.get() or (await self._get_tts_config(account_id)).get("voice") or ""
                cur = await db.execute(
                    "SELECT provider, sample_path, config_path FROM voice_clones WHERE provider=? AND (voice_id=? OR name=?) ORDER BY CASE WHEN voice_id=? THEN 0 ELSE 1 END LIMIT 1",
                    (name, requested_voice, requested_voice, requested_voice),
                )
                clone = await cur.fetchone()
                cur = await db.execute("SELECT key, value FROM settings WHERE key IN ('tts_xtts_model', 'tts_xtts_device', 'tts_clone_engine')")
                runtime = {row["key"]: row["value"] for row in await cur.fetchall()}
            finally:
                await db.close()
            if clone and clone["provider"] == "xtts" and clone["sample_path"]:
                if (runtime.get("tts_clone_engine") or "xtts") == "f5tts":
                    return F5TTSProvider(clone["sample_path"],
                                         model_name=runtime.get("tts_xtts_model", ""),
                                         device=runtime.get("tts_xtts_device", "cpu"))
                return XTTSProvider(clone["sample_path"], model_name=runtime.get("tts_xtts_model", ""), device=runtime.get("tts_xtts_device", "cpu"))
            if clone and clone["provider"] == "piper" and clone["config_path"]:
                return PiperProvider(clone["config_path"].removesuffix(".onnx.json") + ".onnx")
            if name == "piper":
                # Piper models uploaded through the panel are file-backed and
                # do not need a row in voice_clones.
                from app.voice_clone import find_voice_model
                model = find_voice_model(_provider_voice_name.get() or (await self._get_tts_config(account_id)).get("voice") or "")
                return PiperProvider(model.onnx_path) if model else self._providers.get("piper")
            return self._providers.get("piper")
        elif name == "elevenlabs":
            db = await get_db()
            try:
                cur = await db.execute("SELECT value FROM settings WHERE key IN ('tts_elevenlabs_api_key', 'elevenlabs_api_key') ORDER BY key LIMIT 1")
                row = await cur.fetchone()
            finally:
                await db.close()
            from app.security import decrypt_token
            key = decrypt_token(row["value"]) if row else ""
            key = key or os.getenv("ELEVENLABS_API_KEY", "")
            return ElevenLabsProvider(key) if key else None
        return None


# ── Singleton ──────────────────────────────────────────────────────

_tts_engine: TTSEngine | None = None


def get_tts_engine() -> TTSEngine:
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = TTSEngine()
    return _tts_engine


# ── WebSocket broadcast ───────────────────────────────────────────

async def broadcast_tts_event(
    channel: str,
    account_id: int,
    text: str,
    emotion: str,
    audio_b64: str,
    mime: str,
    provider: str,
    volume: float = 1.0,
    speaker: str = "",
    speaker_kind: str = "bot",
    display_text: str = "",
) -> None:
    """Надсилає TTS подію через WebSocket для OBS Widget.

    P6 PLAN.md: додає в подію ``speaker`` (хто говорить), ``speaker_kind``
    ('bot'|'viewer') та ``speaker_emoji`` (іконка джерела). Порожній
    ``speaker`` = ім'я бота з accounts; без БД — fallback на channel."""
    if not speaker:
        try:
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT nickname FROM accounts WHERE id = ?", (account_id,)
                )
                row = await cur.fetchone()
            finally:
                await db.close()
            if row and row["nickname"]:
                speaker = row["nickname"]
        except Exception:
            pass
    emoji = ""
    if speaker_kind == "viewer":
        emoji = "📣"
    else:
        try:
            cfg = await self_config_emoji(account_id)
            emoji = cfg or "🎙️"
        except Exception:
            emoji = "🎙️"
    try:
        from app.server import broadcast_log
        await broadcast_log({
            "type": "tts",
            "account_id": account_id,
            "channel": channel,
            "text": text,
            "emotion": emotion,
            "audio_b64": audio_b64,
            "mime": mime,
            "provider": provider,
            "volume": volume,
            "speaker": speaker,
            "speaker_kind": speaker_kind,
            "speaker_emoji": emoji,
            "display_text": display_text or "",
        })
    except Exception as exc:
        logger.warning("broadcast_tts_event failed: %s", exc)


async def self_config_emoji(account_id: int) -> str:
    """widget_emoji з tts_bot_config (fallback '') для оверлея TTS-чату."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT widget_emoji FROM tts_bot_config WHERE account_id = ?",
            (account_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    return (row["widget_emoji"] or "").strip() if row else ""


__all__ = [
    "TTSEngine",
    "get_tts_engine",
    "broadcast_tts_event",
    "EMOTION_PARAMS",
    "WebSpeechProvider",
    "PiperProvider",
    "ElevenLabsProvider",
]
