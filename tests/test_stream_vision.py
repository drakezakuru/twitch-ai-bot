"""Тесты StreamVisionManager без внешних CLI.

Не дёргают streamlink/ffmpeg/whisper — проверяют сам менеджер: что start()
эмитит правильные ai_log события когда инструменты не установлены, что
is_running корректно отслеживает состояние, и что stop_all() корректно
останавливает все задачи.
"""
from __future__ import annotations

import asyncio

import pytest

from app.stream_vision import StreamVisionManager, StreamVisionConfig


@pytest.fixture(autouse=True)
def _reset_streamlink_module_state():
    """Сбрасываем module-level кэш streamlink между тестами."""
    import app.stream_vision as _sv
    _sv._reset_streamlink_cache()
    yield
    _sv._reset_streamlink_cache()


class _FakeAI:
    """Заглушка ai_service.analyze_image / transcribe_audio — чтобы не уйти в сеть."""

    async def analyze_image(self, *a, **kw):
        return "test description"


@pytest.mark.asyncio
async def test_start_without_streamlink_logs_error(monkeypatch):
    """Если streamlink/ffmpeg недоступны и автоустановка не сработала —
    start() должен сообщить об этом в ai_log.
    """
    captured: list[tuple[str, str]] = []

    async def cb(event, detail, account_id, channel):
        captured.append((event, detail))

    # Подменяем shutil.which, чтобы вернуть None для streamlink/ffmpeg
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)

    # v10.4.8: стабим автоустановку — реальный pip в тестах не нужен.
    async def _fake_ensure():
        return False, "streamlink не установлен — pip install streamlink"

    monkeypatch.setattr(
        "app.stream_vision._ensure_streamlink_available", _fake_ensure
    )

    mgr = StreamVisionManager(_FakeAI(), log_cb=cb)
    ok = await mgr.start(account_id=1, channel="testchannel")
    assert ok is False
    assert any("streamlink" in d for _, d in captured), captured


@pytest.mark.asyncio
async def test_start_autoinstalls_streamlink(monkeypatch):
    """v10.4.8: если streamlink нет в PATH, но автоустановка через pip
    проходит — start() не должен падать на этой проверке.
    """
    captured: list[tuple[str, str]] = []

    async def cb(event, detail, account_id, channel):
        captured.append((event, detail))

    # _ensure_streamlink_available "автоустановил" streamlink и вернул True.
    async def _fake_ensure():
        return True, ""

    monkeypatch.setattr(
        "app.stream_vision._ensure_streamlink_available", _fake_ensure
    )
    # ffmpeg притворяется доступным, чтобы start() прошёл проверки.
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    mgr = StreamVisionManager(_FakeAI(), log_cb=cb)
    ok = await mgr.start(account_id=1, channel="testchannel")
    assert ok is True
    # Никаких stream_error про streamlink в логах быть не должно.
    assert not any(
        event == "stream_error" and "streamlink" in detail
        for event, detail in captured
    ), captured
    # Останавливаем фоновый цикл — он начнёт дергать реальный streamlink/ffmpeg.
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_ensure_streamlink_available_skips_when_present(monkeypatch):
    """Если streamlink уже в PATH — функция не должна звать pip."""
    import shutil
    import app.stream_vision as sv

    # streamlink "на PATH" — _get_streamlink_invocation вернёт "streamlink"
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/streamlink" if name == "streamlink" else None)

    called: list[bool] = []

    async def _fail_subprocess(*a, **kw):
        called.append(True)
        raise AssertionError("pip не должен вызываться, streamlink уже на PATH")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail_subprocess)

    ok, msg = await sv._ensure_streamlink_available()
    assert ok is True
    assert msg == ""
    assert not called


@pytest.mark.asyncio
async def test_ensure_streamlink_uses_python_module_when_cli_not_on_path(monkeypatch):
    """v10.4.8: если streamlink_cli импортируется, но `streamlink` CLI
    не на PATH — используем `python -m streamlink_cli`.
    """
    import shutil
    import app.stream_vision as sv

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(sv, "_can_import_streamlink_cli", lambda: True)

    inv = sv._get_streamlink_invocation()
    assert inv is not None
    assert "streamlink_cli" in inv
    assert "-m streamlink_cli" in inv


@pytest.mark.asyncio
async def test_ensure_streamlink_returns_cached_error_on_retry(monkeypatch):
    """Если автоустановка упала с конкретной ошибкой — на повторе должны
    вернуть ту же подробную ошибку, а не generic-сообщение.
    """
    import shutil
    import app.stream_vision as sv

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(sv, "_can_import_streamlink_cli", lambda: False)

    calls: list[list[str]] = []

    async def _fake_pip(args):
        calls.append(list(args))
        return 1, "ERROR: externally-managed-environment\nPEP 668: blah blah"

    monkeypatch.setattr(sv, "_run_pip_install", _fake_pip)

    ok1, msg1 = await sv._ensure_streamlink_available()
    assert ok1 is False
    assert "externally-managed-environment" in msg1
    assert "--user" in msg1 or "--break-system-packages" in msg1

    # Повторный вызов — pip больше не дёргается, но сообщение то же.
    calls_before = len(calls)
    ok2, msg2 = await sv._ensure_streamlink_available()
    assert ok2 is False
    assert msg2 == msg1
    assert len(calls) == calls_before  # pip не вызывался повторно


@pytest.mark.asyncio
async def test_is_running_state(monkeypatch):
    """is_running корректно отражает наличие/состояние фоновой задачи."""
    mgr = StreamVisionManager(_FakeAI())
    assert mgr.is_running(1, "ch") is False
    # Запускаем долгоживущую заглушку — is_running должно стать True
    task = asyncio.ensure_future(asyncio.sleep(60))
    mgr._tasks[(1, "ch")] = task
    assert mgr.is_running(1, "ch") is True
    # stop_all() корректно завершает задачи
    await mgr.stop_all()
    assert mgr.is_running(1, "ch") is False


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("FRAME_INTERVAL", "10")
    monkeypatch.setenv("AUDIO_INTERVAL", "20")
    monkeypatch.setenv("STREAM_QUALITY", "720p")
    cfg = StreamVisionConfig.from_env()
    assert cfg.frame_interval == 10
    assert cfg.audio_interval == 20
    assert cfg.quality == "720p"


def test_default_config_is_safe(monkeypatch):
    """Без переменных окружения — разумные дефолты, ничего не падает."""
    monkeypatch.delenv("FRAME_INTERVAL", raising=False)
    monkeypatch.delenv("AUDIO_INTERVAL", raising=False)
    monkeypatch.delenv("STREAM_QUALITY", raising=False)
    cfg = StreamVisionConfig.from_env()
    assert cfg.frame_interval > 0
    assert cfg.audio_interval > 0
    assert cfg.quality


# v10.4.8: Тесты для diarization + whisperx fallback.

def test_diarize_safe_off_returns_empty():
    """В режиме off — _diarize_safe сразу возвращает пустую строку (caller
    использует обычный whisper-text как fallback).
    """
    mgr = StreamVisionManager(_FakeAI())
    mgr.cfg.audio_diarization_mode = "off"
    out = mgr._diarize_safe("dummy.wav", {"segments": [{"start": 0, "end": 1, "text": "a"}]})
    assert out == ""


def test_diarize_safe_whisperx_falls_back_to_heuristic_when_not_installed(monkeypatch):
    """Режим whisperx + whisperx не установлен → fallback на heuristic.

    _diarize_whisperx() поднимает RuntimeError, _diarize_safe ловит и
    переключается на heuristic. Heuristic-функция замокана.
    """
    mgr = StreamVisionManager(_FakeAI())
    mgr.cfg.audio_diarization_mode = "whisperx"

    # heuristic diarize_segments → один сегмент с одним speaker
    monkeypatch.setattr(
        "app.stream_vision.diarize_segments",
        lambda *a, **kw: [{"speaker": 0, "start": 0.0, "end": 1.0, "text": "ok"}],
    )
    monkeypatch.setattr(
        "app.stream_vision.format_diarized_transcript",
        lambda segs, **kw: "ok",
    )

    # _diarize_whisperx → симулируем что whisperx не установлен
    def _explode(*args, **kwargs):
        raise RuntimeError("whisperx не установлен")
    monkeypatch.setattr(mgr, "_diarize_whisperx", _explode)

    out = mgr._diarize_safe("dummy.wav", {"segments": [{"start": 0, "end": 1, "text": "ok"}]})
    assert out == "ok"


def test_resolve_hf_token_reads_env(monkeypatch):
    """Если БД пуста и в окружении HUGGINGFACE_TOKEN — _resolve_hf_token его берёт."""
    mgr = StreamVisionManager(_FakeAI())
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_test_token")
    monkeypatch.delenv("HF_TOKEN", raising=False)

    # БД get_setting вернёт пустую строку (нет токена) → fallback на env.
    async def _empty_setting(key, default=""):
        return ""
    monkeypatch.setattr("app.database.get_setting", _empty_setting)

    tok = mgr._resolve_hf_token()
    assert tok == "hf_test_token"


def test_resolve_hf_token_empty_when_nothing_set(monkeypatch):
    """Если ни БД, ни env — токен пустой."""
    mgr = StreamVisionManager(_FakeAI())
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    async def _empty_setting(key, default=""):
        return ""
    monkeypatch.setattr("app.database.get_setting", _empty_setting)

    tok = mgr._resolve_hf_token()
    assert tok == ""
