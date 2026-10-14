"""C3 (PLAN_TODO ТРЕК 1): исправления владельца реально доезжают до промпта.

Раньше `/api/bot/corrections/learn` писал в БД и в сессию, а `context` никто
не читал — это и была причина пункта «решить, не удалять». Сейчас
`chat_analyzer` подмешивает `get_corrections_context()` в system-промпт;
тест закрепляет и формат блока, и сам факт вызова, чтобы связь не отвалилась
молча при следующей правке промпта.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def bot_intel():
    from app import routes_bot_intel

    routes_bot_intel._session_corrections.clear()
    yield routes_bot_intel
    routes_bot_intel._session_corrections.clear()


def test_context_is_empty_without_corrections(bot_intel):
    assert bot_intel.get_corrections_context(1, "demo") == ""


def test_context_is_channel_scoped(bot_intel):
    bot_intel._session_corrections[(1, "demo")] = [
        {"username": "owner", "correction": "не зови зрителей ботами",
         "original_context": "привет, боты"},
    ]
    ctx = bot_intel.get_corrections_context(1, "DEMO")
    assert "не зови зрителей ботами" in ctx
    assert "исправляет: привет, боты" in ctx
    # чужой канал и чужой аккаунт своих исправлений не получают
    assert bot_intel.get_corrections_context(1, "other") == ""
    assert bot_intel.get_corrections_context(2, "demo") == ""


def test_context_keeps_only_last_twenty(bot_intel):
    bot_intel._session_corrections[(1, "demo")] = [
        {"username": "owner", "correction": f"правка {i}", "original_context": ""}
        for i in range(30)
    ]
    ctx = bot_intel.get_corrections_context(1, "demo")
    assert "правка 29" in ctx
    assert "правка 9" not in ctx


def test_chat_analyzer_injects_corrections_block():
    """Без этого вызова C3 снова превращается в «пишем, но не читаем»."""
    src = (ROOT / "app" / "chat_analyzer.py").read_text(encoding="utf-8")
    assert "get_corrections_context" in src
    assert "corrections_block," in src, "блок не попадает в extras системного промпта"
