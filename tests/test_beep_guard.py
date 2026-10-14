"""§S2 Запикивание: тесты beep_guard — детектор запретных слов."""
from __future__ import annotations

import pytest

from app import beep_guard


# ── Чистые функции (без БД) ─────────────────────────────────────


def test_check_transcript_clean():
    """Чистый текст не триггерит."""
    result = beep_guard.check_transcript("привет как дела всё хорошо")
    assert result == []


def test_check_transcript_dirty():
    """Текст с матом находит слово, позицию, категорию."""
    stem = list(beep_guard.DEFAULT_BAD_WORDS.keys())[0]
    category = beep_guard.DEFAULT_BAD_WORDS[stem]
    text = f"ой а что такое {stem}垢"
    result = beep_guard.check_transcript(text, sensitivity="strict")
    assert len(result) >= 1
    match = result[0]
    assert match["word"] == stem
    assert match["category"] == category
    assert "position" in match


def test_check_transcript_custom_words():
    """Кастомные слова через параметр check_transcript."""
    result = beep_guard.check_transcript(
        "абсолютно чистое предложение",
        custom_words={"чистое": "test_cat"},
        sensitivity="loose",
    )
    found = [m for m in result if m["word"] == "чистое"]
    assert len(found) == 1


def test_check_transcript_loose_vs_strict():
    """Sensitivity loose ловит только целые слова."""
    stem = list(beep_guard.DEFAULT_BAD_WORDS.keys())[0]
    r1 = beep_guard.check_transcript(stem, sensitivity="loose")
    r2 = beep_guard.check_transcript(stem, sensitivity="strict")
    assert len(r1) >= 1
    assert len(r2) >= 1


# ── С БД ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_schema_runs(tmp_db):
    """ensure_schema() не падает на tmp_db."""
    await beep_guard.ensure_schema()


@pytest.mark.asyncio
async def test_settings_roundtrip(tmp_db):
    """get_settings / update_settings сохраняют и читают настройки."""
    await beep_guard.ensure_schema()
    settings = await beep_guard.get_settings("test_acc")
    assert settings["enabled"] is True
    assert settings["sensitivity"] == "normal"

    await beep_guard.update_settings("test_acc", sensitivity="strict", enabled=False)
    updated = await beep_guard.get_settings("test_acc")
    assert updated["sensitivity"] == "strict"
    assert updated["enabled"] is False


@pytest.mark.asyncio
async def test_emit_alert(tmp_db, monkeypatch):
    """emit_alert шлёт событие через widget_bus."""
    await beep_guard.ensure_schema()
    alerts = []

    class FakeWidgetBus:
        @staticmethod
        async def broadcast_log(payload):
            alerts.append(payload)
        @staticmethod
        async def duck_start(**kw):
            pass
        @staticmethod
        async def duck_end(**kw):
            pass

    monkeypatch.setattr(beep_guard, "widget_bus", FakeWidgetBus())
    await beep_guard.emit_alert("acc1", "#test", "тест")
    assert len(alerts) == 1
    assert alerts[0]["type"] == "beep_guard"
    assert alerts[0]["kind"] == "beep_detected"
    assert alerts[0]["word"] == "тест"


@pytest.mark.asyncio
async def test_emit_alert_uses_real_widget_bus_contract(tmp_db, monkeypatch):
    from app import widget_bus
    events = []

    async def capture(kind, **payload):
        events.append((kind, payload))

    widget_bus._active_ducks.clear()
    monkeypatch.setattr(widget_bus, "_broadcast_bus", capture)
    monkeypatch.setattr(beep_guard, "widget_bus", widget_bus)

    await beep_guard.emit_alert("acc1", "#test", "тест")

    assert [kind for kind, _ in events] == ["duck_start", "duck_end"]
    assert events[0][1]["source"] == "beep"
    assert events[0][1]["reason"] == "beep:#test"
    assert widget_bus.is_ducked() is None


@pytest.mark.asyncio
async def test_on_stream_audio_result(tmp_db, monkeypatch):
    """on_stream_audio_result детектит мат в транскрипте."""
    await beep_guard.ensure_schema()
    alerts = []
    log_calls = []

    class FakeWidgetBus:
        @staticmethod
        async def broadcast_log(payload):
            alerts.append(payload)
        @staticmethod
        async def duck_start(**kw):
            pass
        @staticmethod
        async def duck_end(**kw):
            pass

    async def fake_log_per_bot(aid, ch, cat, msg, **kw):
        log_calls.append((aid, ch, cat, msg))

    monkeypatch.setattr(beep_guard, "widget_bus", FakeWidgetBus())
    monkeypatch.setattr(beep_guard, "log_per_bot", fake_log_per_bot)

    stem = list(beep_guard.DEFAULT_BAD_WORDS.keys())[0]
    hits = await beep_guard.on_stream_audio_result("acc1", "#test", f"тут слово {stem}垢")
    assert len(hits) >= 1
    assert len(alerts) >= 1
    assert alerts[0]["kind"] == "beep_detected"
    assert len(log_calls) >= 1
    assert log_calls[0][2] == "beep_event"
