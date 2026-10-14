"""PROMPT-BASE (PB-1…PB-3): общая база запреток и декор исходящих сообщений.

PB-1: единый список запреток/правил для всех ботов (settings-kv prompt_base).
PB-2: порядок сборки system prompt — база → персона/личный промпт; при
конфликте содержания личный промпт сильнее, база — жёсткий минимум.
PB-3: эмодзи-префикс/суффикс применяет панель при отправке (0 токенов).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

from app.chat_analyzer import ChatAnalyzer
from app.bot_manager import TwitchBotManager


class _RecordingAI:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_text(self, *args, **kwargs):
        self.calls.append(kwargs)
        return "ответ"

    async def analyze_image(self, *args, **kwargs):
        return ""


async def _no_send(*args, **kwargs):
    return True


def _new_analyzer() -> tuple[ChatAnalyzer, _RecordingAI]:
    ai = _RecordingAI()
    return ChatAnalyzer(ai=ai, send_fn=_no_send), ai


# ─────────────── PB-3: декор исходящих сообщений ───────────────

def _manager() -> TwitchBotManager:
    return TwitchBotManager.__new__(TwitchBotManager)  # декор не использует состояние __init__


async def test_decor_applies_prefix_and_suffix():
    from app.chat_analyzer import ChatAnalyzer as _CA
    a = _CA.__new__(_CA)
    a._settings = {1: {"outgoing_emoji_prefix": "🔥", "outgoing_emoji_suffix": "😄"}}
    m = _manager()

    import app.server as server_mod
    saved = getattr(server_mod, "chat_analyzer", None)
    server_mod.chat_analyzer = a
    try:
        out = await m._decorate_outgoing(1, "привет чат")
    finally:
        server_mod.chat_analyzer = saved
    assert out == "🔥 привет чат 😄"


async def test_decor_skips_commands_and_empty():
    from app.chat_analyzer import ChatAnalyzer as _CA
    a = _CA.__new__(_CA)
    a._settings = {1: {"outgoing_emoji_prefix": "🔥", "outgoing_emoji_suffix": "😄"}}
    m = _manager()

    import app.server as server_mod
    saved = getattr(server_mod, "chat_analyzer", None)
    server_mod.chat_analyzer = a
    try:
        assert await m._decorate_outgoing(1, "!np test") == "!np test"  # команда
        assert await m._decorate_outgoing(1, "") == ""                  # пусто
        # идемпотентность: не наращиваем повторно
        assert await m._decorate_outgoing(1, "🔥 уже с декором 😄") == "🔥 уже с декором 😄"
    finally:
        server_mod.chat_analyzer = saved


async def test_decor_noop_by_default():
    from app.chat_analyzer import ChatAnalyzer as _CA
    a = _CA.__new__(_CA)
    a._settings = {1: {}}  # пустые настройки — дефолт, поведение не меняется
    m = _manager()

    import app.server as server_mod
    saved = getattr(server_mod, "chat_analyzer", None)
    server_mod.chat_analyzer = a
    try:
        assert await m._decorate_outgoing(1, "как есть") == "как есть"
    finally:
        server_mod.chat_analyzer = saved


async def test_decor_defaults_in_analyzer_settings():
    a, _ = _new_analyzer()
    s = a.get_settings(1)
    assert s["outgoing_emoji_prefix"] == ""
    assert s["outgoing_emoji_suffix"] == ""


# ─────────────── PB-1 / Q18: запретные темы per-канал + пресет ───────────────

async def test_prompt_base_block_empty_by_default(tmp_db):
    from app.database import init_db
    await init_db()
    a, _ = _new_analyzer()
    # Q18: «пусто по умолчанию» больше не существует — канал без своего списка
    # наследует базовый пресет Twitch (DEC-OWNER-004)
    block = await a._load_prompt_base_block()
    assert block.startswith("ОБЯЗАТЕЛЬНАЯ БАЗА ПРАВИЛ")
    assert "базовый пресет Twitch" in block


async def test_prompt_base_block_formats_rules(tmp_db):
    from app.database import init_db, set_setting
    await init_db()
    await set_setting("prompt_base", "Не употреблять мат\n\n# комментарий\nНе обсуждать политику\n")
    a, _ = _new_analyzer()
    block = await a._load_prompt_base_block()
    assert block.startswith("ОБЯЗАТЕЛЬНАЯ БАЗА ПРАВИЛ")
    assert "- Не употреблять мат" in block
    assert "- Не обсуждать политику" in block
    assert "комментарий" not in block


# ─────────────── PB-2: порядок сборки — база ПЕРЕД личным промптом ───────────────

async def test_prompt_base_prepended_before_personal(tmp_db):
    from app.database import init_db
    await init_db()
    a, ai = _new_analyzer()
    a.update_settings(1, {"system_prompt": "Ты — весёлый болтун."})
    a._load_prompt_base_block = async_lambda("ОБЯЗАТЕЛЬНАЯ БАЗА ПРАВИЛ:\n- Не ругаться")

    await a._generate_and_send(1, "chan", "botnick", "viewer", "привет", is_mention=False)

    assert ai.calls, "AI должен быть вызван"
    system = ai.calls[0].get("system") or ""
    base_pos = system.find("ОБЯЗАТЕЛЬНАЯ БАЗА ПРАВИЛ")
    personal_pos = system.find("Ты — весёлый болтун.")
    assert base_pos != -1 and personal_pos != -1
    assert base_pos < personal_pos, "база должна идти раньше личного промпта"


class async_lambda:
    """Заглушка async-метода с фиксированным результатом."""

    def __init__(self, value: str) -> None:
        self._value = value

    async def __call__(self, *args, **kwargs) -> str:
        return self._value


# ─────────────── API: GET/PUT /api/prompt-base ───────────────

async def test_prompt_base_api_roundtrip(tmp_db, disable_auth):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import init_db
    from app.routes import router

    await init_db()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        put = await c.put("/api/prompt-base", json={"text": "Не ругаться\nНе спамить"})
        assert put.status_code == 200 and put.json()["ok"] is True
        assert put.json()["rules"] == 2

        got = (await c.get("/api/prompt-base")).json()
        assert got["ok"] is True
        assert got["text"] == "Не ругаться\nНе спамить"


async def test_prompt_base_api_rejects_oversize(tmp_db, disable_auth):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import init_db
    from app.routes import router

    await init_db()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        put = await c.put("/api/prompt-base", json={"text": "x" * 9000})
        assert put.json()["ok"] is False
        assert put.json()["error"] == "too_long"
