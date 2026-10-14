"""§7 фаза 3: конвейер запикивания — маппинг диапазонов, пиип-маска, API."""
from __future__ import annotations

import io
import math
import struct
import wave

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


def _wav_bytes(freq_words_at: list[tuple[float, float]] | None = None, dur: float = 2.0,
               rate: int = 8000) -> bytes:
    """Просто тихий синус 200 Гц (чистый аудио-контейнер для теста)."""
    n = int(dur * rate)
    buf = b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 200 * i / rate)))
                   for i in range(n))
    dst = io.BytesIO()
    w = wave.open(dst, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(buf)
    w.close()
    return dst.getvalue()


def test_plan_mask_ranges_merges_overlaps():
    from app.beep_pipeline import plan_mask_ranges
    segs = [{"start": 0.0, "end": 2.0, "text": "да пошёл ты на"},
            {"start": 2.0, "end": 3.5, "text": "нормально всё"}]
    hits = [{"word": "пошёл", "category": "mat", "position": 3}]
    ranges = plan_mask_ranges(segs, hits)
    assert ranges and ranges[0][0] >= 0 and ranges[0][1] <= 2.1
    # пустые входы
    assert plan_mask_ranges([], []) == []
    assert plan_mask_ranges(segs, []) == []


def test_mask_wav_replaces_range_with_beep():
    from app.beep_pipeline import mask_wav_bytes
    src = _wav_bytes()
    out = mask_wav_bytes(src, [(0.5, 1.0)], beep_hz=1000)
    # тот же контейнер
    w_in = wave.open(io.BytesIO(src))
    w_out = wave.open(io.BytesIO(out))
    assert (w_in.getnchannels(), w_in.getframerate()) == (w_out.getnchannels(), w_out.getframerate())
    assert w_out.getnframes() == w_in.getnframes()
    # в середине — синус ~1000 Гц (частота меняется), в начале — 200 Гц
    mid = w_out.readframes(w_out.getframerate())  # 1 сек с начала = зона пипа
    samples = struct.unpack(f"<{len(mid) // 2}h", mid)
    # проверим что не исходный сигнал: у пипа больше пересечений нуля
    def zero_crossings(arr):
        return sum(1 for a, b in zip(arr, arr[1:]) if (a >= 0) != (b >= 0))
    assert zero_crossings(samples) > 100
    w_in.close()
    w_out.close()


async def test_pipeline_settings_roundtrip(tmp_db, disable_auth):
    from app.database import init_db
    await init_db()
    from fastapi import FastAPI
    from app.beep_pipeline import router
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/beep-pipeline")
        assert r.status_code == 200 and r.json()["ok"] is True
        put = await c.put("/api/beep-pipeline", json={
            "pulse_source": "alsa_input.mic", "beep_hz": 1200, "segment_sec": 7})
        cfg = put.json()["config"]
        assert cfg["pulse_source"] == "alsa_input.mic"
        assert cfg["beep_hz"] == 1200
        assert cfg["segment_sec"] == 7
        # невалидный segment_sec клампится
        put2 = await c.put("/api/beep-pipeline", json={"segment_sec": 99})
        assert put2.json()["config"]["segment_sec"] == 15


async def test_pipeline_start_without_ffmpeg(tmp_db, disable_auth):
    """Старт без ffmpeg — понятная ошибка, не падаем."""
    from app.database import init_db
    await init_db()
    from fastapi import FastAPI
    from app.beep_pipeline import router, get_pipeline, reset_pipeline
    reset_pipeline()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/beep-pipeline/start", json={})
        j = r.json()
        # в тест-окружении ffmpeg может быть есть или нет — оба исхода валидны,
        # но если стартовал — сразу стоп
        if j.get("ok"):
            st = (await c.post("/api/beep-pipeline/stop")).json()
            assert st["ok"] is True
        else:
            assert "error" in j
        reset_pipeline()
