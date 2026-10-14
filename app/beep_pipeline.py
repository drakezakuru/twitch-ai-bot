"""§7 фаза 3 (PLAN_CURRENT): автоматическое запикивание — полный конвейер.

Поток (решение владельца 31.08 — делать без ручной проверки звука):

  микрофон/источник Pulse → ffmpeg (сегменты по 5 с) → whisper-транскрипт
  → beep_guard.check_transcript → диапазоны мата → пиип (синус beep_hz)
  → воспроизведение всего звука в виртуальный sink → OBS (monitor sink).

Честные ограничения:
  * пип отстаёт от эфира на ~5-10 с (буфер 5 с + обработка) — включите
    задержку трансляции в OBS;
  * whisper не установлен → конвейер работает как PASS-THROUGH (звук идёт
    в sink без пипов, в логе предупреждение);
  * требует Linux/Pulse (PipeWire совместим): pactl + ffmpeg;
  * это обработка ПОТОКА через панель, не уже ушедшего эфира.

Настройки: settings-таблица, ключ ``beep_pipeline`` (JSON).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.security import auth_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/beep-pipeline", tags=["beep-pipeline"],
                   dependencies=[Depends(auth_dependency)])

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "pulse_source": "default",      # что слушать (pactl list short sources)
    "sink_name": "bot_beep_out",    # виртуальный sink → OBS берёт его monitor
    "beep_hz": 1000,
    "segment_sec": 5,
    "whisper_model": "base",
    "language": "ru",
    "account_id": "",               # для beep_events (чья статистика)
    "channel": "",
}


# ── Настройки (settings kv) ─────────────────────────────────────────────

async def get_config() -> dict:
    from app.database import get_setting
    try:
        raw = await get_setting("beep_pipeline", "")
        cfg = dict(DEFAULTS)
        if raw:
            cfg.update(json.loads(raw))
        return cfg
    except Exception as exc:
        logger.debug("beep_pipeline cfg load: %s", exc)
        return dict(DEFAULTS)


async def save_config(data: dict) -> dict:
    from app.database import get_db
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (data or {}).items() if k in DEFAULTS})
    cfg["enabled"] = 1 if cfg["enabled"] in (1, True, "1", "true") else 0
    cfg["segment_sec"] = max(2, min(15, int(cfg["segment_sec"] or 5)))
    cfg["beep_hz"] = max(300, min(4000, int(cfg["beep_hz"] or 1000)))
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('beep_pipeline', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(cfg, ensure_ascii=False),))
        await db.commit()
    finally:
        await db.close()
    return cfg


# ── Чистые функции (тестируемые) ────────────────────────────────────────

def plan_mask_ranges(segments: list[dict], hits: list[dict]) -> list[tuple[float, float]]:
    """Сопоставляет найденные слова с временными диапазонами whisper-сегментов.

    segments: [{start: float, end: float, text: str}] (whisper).
    hits: [{word, category, position}] — position это индекс В normalized
    транскрипте beep_guard; здесь сравниваем по подстроке слова в тексте
    сегмента (регистронезависимо, по основам).
    Возвращает [(start, end)] — диапазоны в секундах.
    """
    ranges: list[tuple[float, float]] = []
    for seg in segments:
        text = (seg.get("text") or "").lower()
        seg_start = float(seg.get("start") or 0.0)
        seg_end = float(seg.get("end") or seg_start)
        dur = max(0.2, seg_end - seg_start)
        for hit in hits:
            word = (hit.get("word") or "").strip().lower()
            if not word:
                continue
            # основа слова (beep_guard нормализует) — ищем вхождение основы
            stem = word[: max(4, len(word) - 2)]
            idx = text.find(stem)
            if idx == -1:
                continue
            # доля символа → время внутри сегмента, с небольшим запасом
            frac = idx / max(1, len(text))
            t0 = seg_start + frac * dur
            ranges.append((t0, t0 + min(1.2, dur * 0.5)))
    # склеиваем пересечения
    ranges.sort()
    merged: list[tuple[float, float]] = []
    for a, b in ranges:
        if merged and a <= merged[-1][1] + 0.05:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def mask_wav_bytes(wav_bytes: bytes, ranges: list[tuple[float, float]], beep_hz: int = 1000) -> bytes:
    """Заменяет указанные диапазоны (сек) синус-пиипом той же амплитуды RMS.

    Формат: PCM 16-bit (любые каналы/частота из исходника).
    """
    import io as _io
    src = wave.open(_io.BytesIO(wav_bytes), "rb")
    params = src.getparams()
    nchannels, sampwidth, framerate, nframes = params.nchannels, params.sampwidth, params.framerate, params.nframes
    raw = src.readframes(nframes)
    src.close()
    if sampwidth != 2 or not ranges:
        return wav_bytes

    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    rms = 0
    step = max(1, len(samples) // 50000)
    acc = cnt = 0
    for i in range(0, len(samples), step):
        acc += samples[i] * samples[i]
        cnt += 1
    rms = int(math.sqrt(acc / max(1, cnt))) or 1200
    amp = min(30000, max(600, int(rms * 1.2)))

    out = list(samples)
    for t0, t1 in ranges:
        i0 = max(0, int(t0 * framerate) * nchannels)
        i1 = min(len(out), int(t1 * framerate) * nchannels)
        fade = max(1, framerate // 200)
        length = max(1, i1 - i0)
        for n, i in enumerate(range(i0, i1)):
            env = 1.0
            if n < fade:
                env = n / fade
            if (length - n) < fade:
                env = min(env, (length - n) / fade)
            t = n / framerate
            out[i] = int(amp * env * math.sin(2 * math.pi * beep_hz * t))
    raw_out = struct.pack(f"<{len(out)}h", *out)
    dst = _io.BytesIO()
    w = wave.open(dst, "wb")
    w.setnchannels(nchannels)
    w.setsampwidth(2)
    w.setframerate(framerate)
    w.writeframes(raw_out)
    w.close()
    return dst.getvalue()


# ── Менеджер конвейера (singleton) ──────────────────────────────────────

class BeepPipeline:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.worker: asyncio.Task | None = None
        self.running = False
        self.chunks_done = 0
        self.beeps = 0
        self.errors: list[str] = []
        self._processed: set[str] = set()
        self._whisper = None
        self._whisper_failed = False
        self._tmpdir = ""
        self.cfg: dict[str, Any] = {}

    # ── pulse helpers ──
    def _cmd(self, *args: str) -> tuple[int, str]:
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=10)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except Exception as exc:
            return 1, str(exc)

    def ensure_sink(self, sink_name: str) -> tuple[bool, str]:
        rc, out = self._cmd("pactl", "list", "short", "sinks")
        if rc != 0:
            return False, f"pactl недоступен: {out[:120]}"
        if any(sink_name in line for line in out.splitlines()):
            return True, "sink уже есть"
        rc2, out2 = self._cmd("pactl", "load-module", "module-virtual-sink", f"sink_name={sink_name}")
        if rc2 != 0:
            return False, f"load-module: {out2[:160]}"
        return True, f"sink {sink_name} создан"

    def _load_whisper(self):
        try:
            import whisper  # type: ignore
            return whisper.load_model(self.cfg.get("whisper_model") or "base")
        except Exception as exc:
            self._whisper_failed = True
            if not self.errors or "whisper" not in self.errors[-1]:
                self.errors.append(f"whisper недоступен: {exc}; pass-through")
            return None

    def _transcribe_sync(self, path: str) -> tuple[str, list[dict]]:
        if self._whisper is None:
            self._whisper = self._load_whisper()
        if self._whisper is None:
            return "", []
        try:
            res = self._whisper.transcribe(path, language=self.cfg.get("language") or None, fp16=False)
            text = (res.get("text") or "")
            segs = [{"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")}
                    for s in (res.get("segments") or []) if isinstance(s, dict)]
            return text, segs
        except Exception as exc:
            self.errors.append(f"transcribe: {exc}")
            return "", []

    async def _worker(self) -> None:
        from app.beep_guard import check_transcript
        from app.beep_guard import get_settings as beep_guard_settings
        loop = asyncio.get_running_loop()
        seg_sec = self.cfg.get("segment_sec") or 5
        # BUG-6: воркер обязан применять настройки beep-фильтра из БД
        # (beep_settings: enabled/sensitivity/custom_words/channels) — раньше
        # они игнорировались и фильтр работал только на дефолтном словаре.
        guard_cfg: dict[str, Any] = {}
        guard_loaded_at = 0.0
        guard_off_logged = False
        while self.running:
            try:
                now = loop.time()
                if now - guard_loaded_at > 60.0:
                    guard_loaded_at = now
                    try:
                        guard_cfg = await beep_guard_settings(str(self.cfg.get("account_id") or "0"))
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("beep_guard settings load: %s", exc)
                        guard_cfg = {}
                chunks = sorted(Path(self._tmpdir).glob("chunk_*.wav"))
                fresh = [c for c in chunks if c.name not in self._processed and c.stat().st_size > 44]
                # берём только завершённые (не самый свежий, если он ещё пишется)
                if len(fresh) < 1:
                    await asyncio.sleep(0.5)
                    continue
                target = fresh[0]
                self._processed.add(target.name)
                wav = target.read_bytes()
                text, segs = await loop.run_in_executor(None, self._transcribe_sync, str(target))
                hits: list[dict] = []
                if text:
                    channels_flag = guard_cfg.get("channels") or {}
                    channel = (self.cfg.get("channel") or "").lstrip("#").lower()
                    channel_on = channels_flag.get(channel, channels_flag.get(f"#{channel}", True))
                    if not guard_cfg.get("enabled", True) or not channel_on:
                        if not guard_off_logged:
                            guard_off_logged = True
                            self.errors.append("beep-фильтр выключен в настройках (beep_settings) — pass-through")
                    else:
                        hits = check_transcript(
                            text,
                            custom_words=guard_cfg.get("custom_words") or None,
                            sensitivity=guard_cfg.get("sensitivity") or "normal",
                        )
                ranges = plan_mask_ranges(segs, hits) if hits else []
                out = mask_wav_bytes(wav, ranges, int(self.cfg.get("beep_hz") or 1000)) if ranges else wav
                self.chunks_done += 1
                self.beeps += len(ranges)
                if hits:
                    try:
                        from app.beep_guard import on_stream_audio_result
                        await on_stream_audio_result(
                            str(self.cfg.get("account_id") or "0"),
                            self.cfg.get("channel") or "",
                            text)
                    except Exception as exc:
                        logger.debug("beep_pipeline event: %s", exc)
                # плейбек в sink (реальное время, ffmpeg сам pacing'ует)
                env = {**os.environ, "PULSE_SINK": self.cfg.get("sink_name") or "bot_beep_out"}
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-loglevel", "error", "-i", "pipe:0",
                    "-f", "pulse", "pipe:1",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL, env=env)
                try:
                    await proc.communicate(out)
                    await asyncio.sleep(max(0.0, seg_sec - 1.0))  # темп ≈ реальному времени
                except Exception:
                    pass
            except Exception as exc:
                self.errors.append(f"worker: {exc}")
                await asyncio.sleep(1.0)

    def _cleanup_tmp(self) -> None:
        try:
            for old in Path(self._tmpdir).glob("chunk_*.wav"):
                old.unlink(missing_ok=True)
        except Exception:
            pass

    async def start(self, cfg: dict) -> dict:
        if self.running:
            return {"ok": False, "error": "already_running"}
        # AI-BUDGET AB-3: «Стрим слух» выключен у бота-владельца конвейера —
        # старт честным отказом (конвейер не пипает и не транскрибирует).
        # Если account_id не привязан — конвейер глобальный, гейт не применяется.
        acc = cfg.get("account_id")
        if acc:
            try:
                from app.server import chat_analyzer
                if not chat_analyzer.get_settings(int(acc)).get("attention_hearing", True):
                    return {"ok": False, "error": "attention_hearing_disabled"}
            except Exception as exc:  # noqa: BLE001
                logger.debug("beep_pipeline attention gate: %s", exc)
        cfg = await save_config({**cfg, "enabled": True})
        self.cfg = cfg
        if shutil.which("ffmpeg") is None:
            self.errors.append("ffmpeg не найден")
            return {"ok": False, "error": "no_ffmpeg"}
        ok, msg = self.ensure_sink(cfg.get("sink_name") or "bot_beep_out")
        self.errors.append(msg)
        if not ok:
            return {"ok": False, "error": msg}
        self._tmpdir = tempfile.mkdtemp(prefix="beep_pipe_")
        self._cleanup_tmp()
        self._processed = set()
        self.chunks_done = self.beeps = 0
        src = cfg.get("pulse_source") or "default"
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-f", "pulse", "-i", src,
             "-ac", "1", "-ar", "16000",
             "-f", "segment", "-segment_time", str(cfg.get("segment_sec") or 5),
             "-reset_timestamps", "1", str(Path(self._tmpdir) / "chunk_%04d.wav")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.running = True
        self.worker = asyncio.create_task(self._worker())
        logger.info("beep_pipeline: запущен (source=%s sink=%s)", src, cfg.get("sink_name"))
        return {"ok": True, "status": await self.status()}

    async def stop(self) -> dict:
        self.running = False
        if self.cfg:
            await save_config({**self.cfg, "enabled": False})
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            self.proc = None
        if self.worker:
            self.worker.cancel()
            self.worker = None
        self._cleanup_tmp()
        logger.info("beep_pipeline: остановлен")
        return {"ok": True}

    async def status(self) -> dict:
        # BUG-6: честный статус whisper — «unknown» пока первый сегмент не
        # обработан, чтобы панель не заявляла pass-through раньше времени.
        if self._whisper is not None:
            whisper_state = "ready"
        elif getattr(self, "_whisper_failed", False):
            whisper_state = "unavailable"
        else:
            whisper_state = "unknown"
        return {
            "running": self.running,
            "chunks_done": self.chunks_done,
            "beeps": self.beeps,
            "errors_tail": self.errors[-5:],
            "has_whisper": self._whisper is not None,
            "whisper_state": whisper_state,
            "tmpdir": self._tmpdir,
        }


# ── Singleton ───────────────────────────────────────────────────────────

_pipeline: BeepPipeline | None = None


def get_pipeline() -> BeepPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = BeepPipeline()
    return _pipeline


def reset_pipeline() -> None:
    global _pipeline
    _pipeline = None


# ── HTTP ────────────────────────────────────────────────────────────────

@router.get("")
async def api_status() -> dict:
    return {"ok": True, "config": await get_config(), "status": await get_pipeline().status()}


@router.put("")
async def api_save(request: Request) -> dict:
    data = await request.json() or {}
    return {"ok": True, "config": await save_config(data)}


@router.post("/start")
async def api_start(request: Request) -> dict:
    data = await request.json() or {}
    return await get_pipeline().start(data)


@router.post("/stop")
async def api_stop() -> dict:
    return await get_pipeline().stop()
