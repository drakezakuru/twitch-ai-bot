"""PLAN_FEEDBACK_2908 §12.2: движки клонирования голоса.

- выбор движка клона настройкой tts_clone_engine (xtts | f5tts);
- F5TTSProvider: guard без пакета + корректный wav-байтовый вывод.
"""
from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_sample(tmp_path):
    """Фиктивный wav-семпл во временной папке теста.

    Раньше путь был захардкожен в `/tmp/opencode/`: в свежей песочнице этой
    папки нет, и все три теста падали с FileNotFoundError ещё до проверки
    самого движка.
    """
    path = tmp_path / "fake_sample.wav"
    path.write_bytes(b"RIFFfake")
    return str(path)


class _FakeF5:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def infer(self, ref_file, ref_text, gen_text, speed):
        sr = 24000
        wav = np.sin(np.linspace(0, 200 * np.pi, sr // 2)).astype(np.float32) * 0.5
        return (sr, wav)


async def test_f5_engine_selected_by_setting(tmp_db, monkeypatch, fake_sample):
    from app.database import init_db, get_db
    from app.tts_engine import F5TTSProvider, TTSEngine

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO accounts (id, nickname, token) VALUES (41, 'clonebot', 't')"
        )
        await db.execute(
            "INSERT OR REPLACE INTO tts_bot_config (account_id, enabled, provider, voice, volume, speed) "
            "VALUES (41, 1, 'xtts', 'myclone', 1.0, 1.0)"
        )
        await db.execute(
            "INSERT OR REPLACE INTO voice_clones (name, provider, voice_id, sample_path, lang) "
            "VALUES ('myclone', 'xtts', '', ?, 'ru')",
            (fake_sample,)
        )
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('tts_clone_engine', 'f5tts')"
        )
        await db.commit()
    finally:
        await db.close()

    engine = TTSEngine()
    async def fake_broadcast(**kwargs):
        pass
    monkeypatch.setattr("app.tts_engine.broadcast_tts_event", fake_broadcast)

    selected = {}
    def fake_factory(sample_path, **kwargs):
        selected["cls"] = "f5"
        f5 = F5TTSProvider.__new__(F5TTSProvider)
        return f5
    # подменяем только _get_provider частично: проверяем выбор движка через _get_provider
    import app.tts_engine as te
    monkeypatch.setattr(te, "F5TTSProvider", fake_factory)

    provider = await engine._get_provider("xtts", 41)
    assert selected.get("cls") == "f5", "tts_clone_engine=f5tts должен выбирать F5TTSProvider"
    assert provider is not None


async def test_f5_provider_synthesize_wav(tmp_db, monkeypatch, fake_sample):
    import wave
    import io as _io
    from app.tts_engine import F5TTSProvider

    p = F5TTSProvider(fake_sample)
    monkeypatch.setattr(p, "_model", _FakeF5(), raising=False)
    # _load_model должен не перезатирать уже установленную модель
    monkeypatch.setattr(p, "_load_model", lambda: None)

    audio = await p.synthesize("привет чат", "", "neutral", 1.0)
    assert audio[:4] == b"RIFF"
    with wave.open(_io.BytesIO(audio)) as w:
        assert w.getframerate() == 24000
        assert w.getnframes() > 0


async def test_f5_requires_package(tmp_db, fake_sample):
    from app.tts_engine import F5TTSProvider

    p = F5TTSProvider(fake_sample)
    if p._model is None:
        try:
            import f5_tts  # noqa: F401
            pytest.skip("f5-tts установлен — guard не проверить")
        except ImportError:
            with pytest.raises(RuntimeError, match="F5-TTS is not installed"):
                await p.synthesize("тест", "", "neutral", 1.0)
