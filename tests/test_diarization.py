"""Tests for app/diarization.py — heuristic speaker separation.

Без реальных speech-сэмплов тестируем:
  * format_diarized_transcript на in-memory сегментах;
  * diarize_segments на синтетических WAV-файлах (один тон vs два тона)
    — проверяем что метки расставляются логично.

Полная точность тестируется на реальном аудио вручную (см. SKILL.md).
"""

import math
import struct
import tempfile
import wave
from pathlib import Path

import pytest

from app.diarization import diarize_segments, format_diarized_transcript


# ---------- format_diarized_transcript ---------------------------------------


def test_format_empty_segments():
    assert format_diarized_transcript([]) == ""


def test_format_single_speaker_returns_plain_text():
    segs = [
        {"speaker": 0, "start": 0.0, "end": 1.0, "text": "Привет."},
        {"speaker": 0, "start": 1.0, "end": 2.0, "text": "Как дела?"},
    ]
    out = format_diarized_transcript(segs)
    assert "[Голос" not in out
    assert "Привет." in out
    assert "Как дела?" in out


def test_format_multi_speaker_labels_each_turn():
    segs = [
        {"speaker": 0, "start": 0.0, "end": 1.0, "text": "Привет всем."},
        {"speaker": 1, "start": 1.0, "end": 2.0, "text": "Спасибо за рейд!"},
        {"speaker": 0, "start": 2.0, "end": 3.0, "text": "Продолжаем игру."},
    ]
    out = format_diarized_transcript(segs)
    assert "[Голос 1] Привет всем." in out
    assert "[Голос 2] Спасибо за рейд!" in out
    assert "[Голос 1] Продолжаем игру." in out


def test_format_consecutive_same_speaker_groups_together():
    segs = [
        {"speaker": 0, "start": 0.0, "end": 1.0, "text": "Первая фраза."},
        {"speaker": 0, "start": 1.0, "end": 2.0, "text": "Вторая фраза."},
        {"speaker": 1, "start": 2.0, "end": 3.0, "text": "Чужой голос."},
    ]
    out = format_diarized_transcript(segs)
    lines = out.split("\n")
    # Две группы (Голос 1 = 2 фразы вместе, Голос 2 = 1 фраза).
    assert len(lines) == 2
    assert "Первая фраза." in lines[0]
    assert "Вторая фраза." in lines[0]
    assert "Чужой голос." in lines[1]


# ---------- diarize_segments --------------------------------------------------


def _write_wav(path: str, samples: list[float], rate: int = 16000) -> None:
    """Записать float-сэмплы [-1,1] как 16-bit PCM mono WAV."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        clamped = [max(-1.0, min(1.0, s)) for s in samples]
        ints = [int(s * 32767) for s in clamped]
        wf.writeframes(struct.pack(f"<{len(ints)}h", *ints))


def _tone(rate: int, dur: float, freq: float, amp: float = 0.5) -> list[float]:
    n = int(rate * dur)
    return [amp * math.sin(2.0 * math.pi * freq * t / rate) for t in range(n)]


def _noise(rate: int, dur: float, amp: float = 0.05) -> list[float]:
    import random

    n = int(rate * dur)
    return [amp * (random.random() * 2 - 1) for _ in range(n)]


def test_diarize_no_segments_returns_empty():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    _write_wav(path, _tone(16000, 1.0, 220.0))
    try:
        assert diarize_segments(path, {}) == []
        assert diarize_segments(path, {"segments": []}) == []
    finally:
        Path(path).unlink(missing_ok=True)


def test_diarize_short_segments_filtered_out():
    """Сегменты < 0.6s игнорируются (шум, междометия)."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    _write_wav(path, _tone(16000, 5.0, 220.0))
    whisper_result = {
        "segments": [
            {"start": 0.0, "end": 0.3, "text": "А."},  # слишком короткий
            {"start": 0.3, "end": 0.4, "text": "Б."},  # слишком короткий
        ]
    }
    try:
        # Все сегменты отфильтрованы → пустой результат.
        assert diarize_segments(path, whisper_result) == []
    finally:
        Path(path).unlink(missing_ok=True)


def test_diarize_single_tone_all_one_speaker():
    """Один и тот же тон по всему файлу → один спикер."""
    rate = 16000
    samples = _tone(rate, 6.0, 220.0)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    _write_wav(path, samples, rate=rate)
    whisper_result = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Раз два три."},
            {"start": 2.0, "end": 4.0, "text": "Четыре пять шесть."},
            {"start": 4.0, "end": 6.0, "text": "Семь восемь девять."},
        ]
    }
    try:
        result = diarize_segments(path, whisper_result)
        assert len(result) == 3
        # Все сегменты должны быть приписаны одному спикеру.
        speakers = {seg["speaker"] for seg in result}
        assert len(speakers) == 1
    finally:
        Path(path).unlink(missing_ok=True)


def test_diarize_two_distinct_tones_at_least_two_speakers():
    """Разный тон + ZCR + энергия в разных сегментах → ≥2 спикера."""
    rate = 16000
    # Сегмент 1: низкий тон, тихий
    seg_a = _tone(rate, 2.0, 150.0, amp=0.3)
    # Сегмент 2: высокий тон, громкий
    seg_b = _tone(rate, 2.0, 1200.0, amp=0.8)
    # Сегмент 3: снова низкий тон
    seg_c = _tone(rate, 2.0, 150.0, amp=0.3)
    samples = seg_a + seg_b + seg_c
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    _write_wav(path, samples, rate=rate)
    whisper_result = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Стример говорит."},
            {"start": 2.0, "end": 4.0, "text": "Гость отвечает."},
            {"start": 4.0, "end": 6.0, "text": "Стример снова."},
        ]
    }
    try:
        result = diarize_segments(path, whisper_result, threshold=0.3)
        assert len(result) == 3
        speakers = [seg["speaker"] for seg in result]
        # Должно быть как минимум 2 разных спикера.
        assert len(set(speakers)) >= 2
        # 2-й сегмент (высокий+громкий) должен быть отличен от 1-го (низкий+тихий).
        assert speakers[1] != speakers[0]
    finally:
        Path(path).unlink(missing_ok=True)


def test_diarize_caps_at_max_speakers():
    """С max_speakers=2 не может быть >2 уникальных спикеров."""
    rate = 16000
    # 4 разных по характеристикам сегмента
    seg_a = _tone(rate, 1.5, 150.0, amp=0.3)
    seg_b = _tone(rate, 1.5, 1200.0, amp=0.8)
    seg_c = _noise(rate, 1.5, amp=0.5)
    seg_d = _tone(rate, 1.5, 600.0, amp=0.6)
    samples = seg_a + seg_b + seg_c + seg_d
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    _write_wav(path, samples, rate=rate)
    whisper_result = {
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "Один."},
            {"start": 1.5, "end": 3.0, "text": "Два."},
            {"start": 3.0, "end": 4.5, "text": "Три."},
            {"start": 4.5, "end": 6.0, "text": "Четыре."},
        ]
    }
    try:
        result = diarize_segments(path, whisper_result, max_speakers=2, threshold=0.1)
        speakers = {seg["speaker"] for seg in result}
        assert len(speakers) <= 2
    finally:
        Path(path).unlink(missing_ok=True)


def test_diarize_bad_wav_returns_empty_gracefully():
    """Битый WAV → пустой результат, без эксепшнов."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
        f.write(b"\x00" * 1000)  # not a valid wav
    whisper_result = {
        "segments": [{"start": 0.0, "end": 1.0, "text": "test"}],
    }
    try:
        assert diarize_segments(path, whisper_result) == []
    finally:
        Path(path).unlink(missing_ok=True)
