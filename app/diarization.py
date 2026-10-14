"""Лёгкая эвристическая диаризация поверх whisper-результата.

v10.4.8: «различать голоса». Twitch отдаёт ОДИН смикшированный аудиопоток,
физически разделить голос стримера / гостей / звук игры нельзя без ML
(WhisperX + pyannote.audio — отдельная история, см. ``AUDIO_DIARIZATION_MODE``).
Этот модуль реализует дешёвую эвристику:

  * Берём ``segments`` из whisper-результата (у каждого есть start/end).
  * Для каждого сегмента грузим соответствующий кусок WAV и считаем простой
    акустический «отпечаток»: RMS-энергию, спектральный центроид, ZCR.
  * Сравниваем последовательно: если отпечаток сильно отличается от
    предыдущего — это, скорее всего, другой говорящий. Иначе — тот же.
  * Кэп на N спикеров (по умолчанию 3) — после этого новые сегменты
    приклеиваются к ближайшему существующему «голосу».

Это НЕ настоящая диаризация. Она:
  + работает без HuggingFace токена и тяжёлых моделей;
  + правильно режет «монолог стримера → реклама/музыка → голос гостя»;
  + плохо различает похожие мужские голоса в одной комнате.

Для серьёзной диаризации см. ``AUDIO_DIARIZATION_MODE=whisperx``.
"""

from __future__ import annotations

import logging
import wave
from typing import Optional

logger = logging.getLogger(__name__)

# Порог Евклидова расстояния между нормализованными «отпечатками» —
# выше = «другой голос». Подобран по тестовым данным.
_DEFAULT_SPEAKER_THRESHOLD = 0.65
_MAX_SPEAKERS = 3
_MIN_SEGMENT_DURATION_SEC = 0.6  # короче — игнорируем, шум


def diarize_segments(
    wav_path: str,
    whisper_result: dict,
    *,
    max_speakers: int = _MAX_SPEAKERS,
    threshold: float = _DEFAULT_SPEAKER_THRESHOLD,
) -> list[dict]:
    """Возвращает список ``{speaker, start, end, text}`` или пустой список.

    Если нет numpy / нет сегментов / WAV не читается — возвращает пустой
    список и пишет в лог. Caller должен иметь fallback на «один спикер».
    """
    segments = (whisper_result or {}).get("segments") or []
    if not segments:
        return []

    try:
        import numpy as np
    except ImportError:
        logger.info("diarization: numpy не доступен, пропускаем диаризацию")
        return []

    try:
        samples, sample_rate = _read_wav_mono(wav_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("diarization: не удалось прочитать WAV %s: %s", wav_path, exc)
        return []
    if samples.size == 0 or sample_rate <= 0:
        return []

    fingerprints: list[tuple[int, "np.ndarray"]] = []  # (segment_idx, fp)
    cleaned: list[dict] = []
    for idx, seg in enumerate(segments):
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or 0.0)
        text = (seg.get("text") or "").strip()
        if end - start < _MIN_SEGMENT_DURATION_SEC or not text:
            continue
        fp = _compute_fingerprint(samples, sample_rate, start, end, np)
        if fp is None:
            continue
        fingerprints.append((idx, fp))
        cleaned.append({"start": start, "end": end, "text": text})

    if not fingerprints:
        return []

    # Sequential speaker assignment with cap on number of speakers.
    speaker_centroids: list["np.ndarray"] = []
    speaker_counts: list[int] = []
    assignments: list[int] = []
    for _, fp in fingerprints:
        if not speaker_centroids:
            speaker_centroids.append(fp.copy())
            speaker_counts.append(1)
            assignments.append(0)
            continue
        # Найти ближайшего существующего спикера.
        dists = [float(np.linalg.norm(fp - c)) for c in speaker_centroids]
        best_idx = int(min(range(len(dists)), key=lambda i: dists[i]))
        if dists[best_idx] <= threshold or len(speaker_centroids) >= max_speakers:
            # Тот же спикер (или достигли лимита) — обновляем центроид.
            sid = best_idx
            speaker_counts[sid] += 1
            n = speaker_counts[sid]
            speaker_centroids[sid] = speaker_centroids[sid] * (n - 1) / n + fp / n
        else:
            sid = len(speaker_centroids)
            speaker_centroids.append(fp.copy())
            speaker_counts.append(1)
        assignments.append(sid)

    for seg, sid in zip(cleaned, assignments):
        seg["speaker"] = sid
    return cleaned


def format_diarized_transcript(segments: list[dict], *, max_speakers_in_label: int = 3) -> str:
    """Форматирует результат диаризации в человекочитаемый текст.

    Каждая строка: ``[Голос N] фраза``. Если все сегменты от одного спикера —
    отдаёт обычный сплошной текст без меток.
    """
    if not segments:
        return ""
    speakers = {s.get("speaker", 0) for s in segments}
    if len(speakers) <= 1:
        return " ".join(s["text"] for s in segments if s.get("text")).strip()
    lines: list[str] = []
    last_sid: Optional[int] = None
    buf: list[str] = []
    for seg in segments:
        sid = seg.get("speaker", 0)
        if sid != last_sid:
            if buf and last_sid is not None:
                lines.append(f"[Голос {last_sid + 1}] {' '.join(buf).strip()}")
                buf = []
            last_sid = sid
        buf.append(seg["text"])
    if buf and last_sid is not None:
        lines.append(f"[Голос {last_sid + 1}] {' '.join(buf).strip()}")
    return "\n".join(lines)


# --- Внутренние утилиты ------------------------------------------------------

def _read_wav_mono(path: str):
    """Читает WAV-файл (16-bit PCM mono или stereo→mono) → (samples, rate).

    Returns (samples: np.ndarray float32 in [-1, 1], rate: int).
    Бросает исключение если файл не PCM или не читается.
    """
    import numpy as np

    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        rate = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
    if sampwidth == 2:
        dtype = np.int16
        scale = 1.0 / 32768.0
    elif sampwidth == 1:
        # 8-bit PCM unsigned
        dtype = np.uint8
        scale = 1.0 / 128.0
    elif sampwidth == 4:
        dtype = np.int32
        scale = 1.0 / 2147483648.0
    else:
        raise ValueError(f"unsupported sampwidth: {sampwidth}")
    audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if sampwidth == 1:
        audio = audio - 128.0  # центрируем
    audio = audio * scale
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)
    return audio, rate


def _compute_fingerprint(samples, sample_rate: int, start: float, end: float, np):
    """Считает простой 4-мерный отпечаток сегмента.

    Возвращает np.ndarray размером (4,) или None если сегмент слишком короткий.

    Фичи (все нормированы в [0, 1] либо около):
      0. RMS-энергия (loudness)
      1. Спектральный центроид (тональная «яркость»)
      2. Zero-crossing rate (грубо: голос vs шум/музыка)
      3. Стандартное отклонение энергии (динамика — монолог vs разговор)
    """
    i0 = max(0, int(start * sample_rate))
    i1 = min(samples.size, int(end * sample_rate))
    chunk = samples[i0:i1]
    if chunk.size < int(0.2 * sample_rate):
        return None

    # 0. RMS
    rms = float(np.sqrt(np.mean(chunk * chunk) + 1e-12))

    # 1. Spectral centroid (приближённо через rfft).
    # Берём центральный кусок чтобы не платить за всю длину.
    win = chunk
    if win.size > sample_rate * 3:
        mid = win.size // 2
        half = int(sample_rate * 1.5)
        win = win[mid - half: mid + half]
    win = win - float(np.mean(win))
    spec = np.abs(np.fft.rfft(win))
    freqs = np.fft.rfftfreq(win.size, d=1.0 / sample_rate)
    spec_sum = float(np.sum(spec) + 1e-12)
    centroid = float(np.sum(freqs * spec) / spec_sum)
    # Нормализуем центроид: типичные голоса 100-4000 Hz.
    centroid_n = min(1.0, centroid / 4000.0)

    # 2. Zero-crossing rate.
    sgn = np.sign(chunk)
    zcr = float(np.mean(np.abs(np.diff(sgn))) / 2.0)

    # 3. Энергия по фреймам — стандартное отклонение.
    frame = max(1, int(0.02 * sample_rate))  # 20ms
    if chunk.size >= frame * 4:
        n_frames = chunk.size // frame
        framed = chunk[: n_frames * frame].reshape(n_frames, frame)
        per_frame_rms = np.sqrt(np.mean(framed * framed, axis=1) + 1e-12)
        # Нормализуем относительно средней.
        mean_e = float(np.mean(per_frame_rms) + 1e-9)
        dyn = float(np.std(per_frame_rms) / mean_e) if mean_e > 0 else 0.0
        dyn = min(1.0, dyn)
    else:
        dyn = 0.0

    # RMS нормализуем грубо (типичный голос: 0.02-0.3 в float32 PCM).
    rms_n = min(1.0, rms / 0.3)

    return np.array([rms_n, centroid_n, min(1.0, zcr * 10.0), dyn], dtype=np.float32)
