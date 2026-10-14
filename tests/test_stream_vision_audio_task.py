"""DEF-01a: аудио-захват живёт в отдельной задаче — кадры не ждут Whisper.

Раньше ``StreamVisionManager._loop`` делал ``await _capture_audio(...)`` прямо
в цикле: Whisper на CPU занимает 45–90 с, и всё это время стояли кадры и
следующий тик аудио. Теперь аудио — отдельная задача per (account, channel)
с back-pressure: тик пропускается, пока предыдущая аудио-задача в полёте.

Тесты не дёргают streamlink/ffmpeg/whisper: ``_capture_frame`` и
``_capture_audio`` подменяются управляемыми фейками, цикл гоняется
на коротких интервалах (1 с, пол сна цикла 0.5 с).
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest

from app.stream_vision import StreamVisionConfig, StreamVisionManager


class _FakeAI:
    async def analyze_image(self, *a, **kw):
        return "test description"


def _make_manager() -> StreamVisionManager:
    cfg = StreamVisionConfig(
        frame_interval=1,
        frame_interval_min=1,
        frame_interval_max=1,
        audio_interval=1,
        save_frames=False,
    )
    return StreamVisionManager(_FakeAI(), cfg=cfg)


@pytest.mark.asyncio
async def test_audio_capture_does_not_block_frames():
    """Пока первая аудио-задача «транскрибирует» (висит на гейте), кадры капают дальше."""
    mgr = _make_manager()
    release = asyncio.Event()
    audio_started = asyncio.Event()
    frames: list[float] = []

    async def fake_frame(acc, ch):
        frames.append(asyncio.get_event_loop().time())

    async def fake_audio(acc, ch):
        audio_started.set()
        await release.wait()

    mgr._capture_frame = fake_frame
    mgr._capture_audio = fake_audio

    loop_task = asyncio.create_task(mgr._loop(1, "chan"))
    try:
        await asyncio.wait_for(audio_started.wait(), timeout=10)
        frames_before = len(frames)
        await asyncio.sleep(2.5)  # ~2.5 интервала: без DEF-01a кадры стояли бы
        assert len(frames) - frames_before >= 2, "кадры должны продолжаться, пока Whisper «думает»"
        assert not loop_task.done(), "цикл не должен падать/завершаться"
    finally:
        release.set()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
        # Отмена цикла дочищает аудио-задачу (handler CancelledError).
        audio_task = mgr._audio_inflight.get((1, "chan"))
        assert audio_task is None or audio_task.done()


@pytest.mark.asyncio
async def test_audio_backpressure_skips_tick_while_inflight():
    """Whisper дольше audio_interval → busy-тик пропускается, задачи не копятся."""
    mgr = _make_manager()
    release = asyncio.Event()
    audio_started = asyncio.Event()
    audio_calls = 0

    async def fake_frame(acc, ch):
        return

    async def fake_audio(acc, ch):
        nonlocal audio_calls
        audio_calls += 1
        if audio_calls == 1:
            audio_started.set()
            await release.wait()

    mgr._capture_frame = fake_frame
    mgr._capture_audio = fake_audio

    loop_task = asyncio.create_task(mgr._loop(1, "chan"))
    try:
        await asyncio.wait_for(audio_started.wait(), timeout=10)
        await asyncio.sleep(2.5)  # ~2.5 аудио-интервала при audio_interval=1
        assert audio_calls == 1, "пока первая аудио-задача в полёте, новых запускать нельзя"
        inflight = mgr._audio_inflight.get((1, "chan"))
        assert inflight is not None and not inflight.done()
    finally:
        release.set()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task


@pytest.mark.asyncio
async def test_stop_cancels_audio_inflight():
    """stop() отменяет аудио-задачу в полёте, даже если цикла уже нет."""
    mgr = _make_manager()
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_audio():
        started.set()
        await release.wait()

    audio_task = asyncio.create_task(gated_audio())
    mgr._audio_inflight[(1, "chan")] = audio_task
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        await asyncio.wait_for(mgr.stop(1, "chan"), timeout=10)
        assert audio_task.done(), "stop() должен отменить аудио-задачу"
        assert (1, "chan") not in mgr._audio_inflight
    finally:
        release.set()
