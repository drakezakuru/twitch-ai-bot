"""AI-BUDGET (AB-1..AB-3): переключатели внимания бота.

AB-1: attention_vision / attention_hearing / attention_chat_ai — источники
платного AI, выключенный источник = 0 запросов модели (AB-3).
AB-2: сырой лог чата пишется в chat_log независимо от переключателей.

Затрагиваемые подсистемы (не дубли, а гейты):
  * vision/hearing — StreamVisionManager._capture_frame / _capture_audio;
  * chat-AI — ChatAnalyzer._generate_and_send (единственная точка
    self.ai.generate_text для чат-ответов);
  * beep-конвейер — BeepPipeline.start отказом attention_hearing_disabled.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

from app.chat_analyzer import ChatAnalyzer
from app.stream_vision import StreamVisionManager


class _RecordingAI:
    """Фейковый AI: запоминает каждый вызов платной модели."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def generate_text(self, *args, **kwargs):
        self.calls.append(("generate_text", args, kwargs))
        return "ответ"

    async def analyze_image(self, *args, **kwargs):
        self.calls.append(("analyze_image", args, kwargs))
        return ""


async def _no_send(*args, **kwargs):
    return True


def _new_analyzer() -> tuple[ChatAnalyzer, _RecordingAI]:
    ai = _RecordingAI()
    return ChatAnalyzer(ai=ai, send_fn=_no_send), ai


# ─────────────── AB-1: дефолты — все источники включены ───────────────

async def test_attention_defaults_all_enabled():
    a, _ = _new_analyzer()
    s = a.get_settings(1)
    assert s["attention_vision"] is True
    assert s["attention_hearing"] is True
    assert s["attention_chat_ai"] is True


async def test_attention_settings_roundtrip_via_update():
    a, _ = _new_analyzer()
    a.update_settings(1, {"attention_vision": False, "attention_chat_ai": False})
    s = a.get_settings(1)
    assert s["attention_vision"] is False
    assert s["attention_hearing"] is True
    assert s["attention_chat_ai"] is False


# ─────────────── AB-3: чат-AI выключен → 0 запросов модели ───────────────

async def test_chat_ai_off_blocks_generation():
    a, ai = _new_analyzer()
    a.update_settings(1, {"attention_chat_ai": False})
    await a._generate_and_send(1, "chan", "botnick", "viewer", "привет", is_mention=False)
    await a._generate_and_send(1, "chan", "botnick", "viewer", "@botnick как дела", is_mention=True)
    assert ai.calls == []


async def test_chat_ai_on_still_generates():
    a, ai = _new_analyzer()
    # Внимание включено (дефолт) — модель вызывается (сработка триггера не требуется:
    # проверяем только что гейт не срезает путь генерации до AI).
    await a._generate_and_send(1, "chan", "botnick", "viewer", "привет", is_mention=False)
    assert any(c[0] == "generate_text" for c in ai.calls)


# ─────────────── AB-2: сырой лог чата не зависит от переключателей ───────────────

async def test_raw_chat_log_written_with_chat_ai_off():
    """log_message пишет chat_log всегда — выключенный чат-AI не мешает."""
    from app.database import get_db, init_db
    from app.server import log_message

    await init_db()
    a, _ = _new_analyzer()
    a.update_settings(1, {"attention_chat_ai": False})

    await log_message(1, "chan", "viewer", "сырое сообщение", is_bot=False)

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT author, message FROM chat_log WHERE account_id = 1 AND channel = 'chan'"
        )
        rows = await cur.fetchall()
    finally:
        await db.close()
    assert len(rows) == 1
    assert rows[0]["message"] == "сырое сообщение"


# ─────────────── AB-3: vision/hearing гейты в StreamVisionManager ───────────────

def _manager() -> StreamVisionManager:
    return StreamVisionManager(
        ai_service=_RecordingAI(), log_cb=None, chat_cb=None,
        cfg=None, token_provider=None,
    )


async def test_vision_off_skips_frame_and_model():
    m = _manager()
    m._attention_enabled = lambda acc, source: source != "vision"  # vision вимкнено

    async def _fail_grab(*a, **kw):
        raise AssertionError("_grab_frame не должен вызываться при выключенном vision")

    m._grab_frame = _fail_grab
    await m._capture_frame(1, "chan")  # не качает кадр и не дёргает модель
    assert isinstance(m.ai, _RecordingAI) and m.ai.calls == []


async def test_vision_on_proceeds_to_grab():
    m = _manager()
    grabbed: list[str] = []

    async def _grab(channel):
        grabbed.append(channel)
        return None  # «стрим оффлайн» — дальше функция спокойно выйдет

    m._grab_frame = _grab
    await m._capture_frame(1, "chan")
    assert grabbed == ["chan"]


async def test_hearing_off_skips_audio_capture():
    m = _manager()
    m._attention_enabled = lambda acc, source: source != "hearing"  # слух вимкнено

    async def _fail_grab(*a, **kw):
        raise AssertionError("_grab_audio не должен вызываться при выключенном слухе")

    m._grab_audio = _fail_grab
    await m._capture_audio(1, "chan")
    assert m.ai.calls == []


async def test_hearing_on_proceeds_to_grab():
    m = _manager()
    grabbed: list[str] = []

    async def _grab(channel, duration=None):
        grabbed.append(channel)
        return ""  # «нет аудио» — дальше функция спокойно выйдет

    m._grab_audio = _grab
    await m._capture_audio(1, "chan")
    assert grabbed == ["chan"]


async def test_attention_gate_without_panel_defaults_enabled():
    """Без панели/анализатора (тесты, standalone) источник считается включённым."""
    m = _manager()

    class _Broken:
        def __getattr__(self, name):
            raise RuntimeError("server not ready")

    import sys
    had_server = "app.server" in sys.modules
    saved_attr = getattr(sys.modules.get("app.server"), "chat_analyzer", None) if had_server else None
    if not had_server:
        sys.modules["app.server"] = type(sys)("app.server")
    sys.modules["app.server"].chat_analyzer = _Broken()
    try:
        assert m._attention_enabled(1, "vision") is True
        assert m._attention_enabled(1, "hearing") is True
    finally:
        if had_server:
            sys.modules["app.server"].chat_analyzer = saved_attr
        else:
            del sys.modules["app.server"]


# ─────────────── AB-3: beep-конвейер не стартует при выключенном слухе ───────────────

async def test_beep_start_refused_when_hearing_off(tmp_db, disable_auth):
    from app.database import init_db
    from app.beep_pipeline import BeepPipeline

    await init_db()
    a, _ = _new_analyzer()
    a.update_settings(7, {"attention_hearing": False})

    import app.server as server_mod
    saved = getattr(server_mod, "chat_analyzer", None)
    server_mod.chat_analyzer = a
    try:
        result = await BeepPipeline().start({"account_id": 7, "enabled": True})
    finally:
        server_mod.chat_analyzer = saved
    assert result["ok"] is False
    assert result["error"] == "attention_hearing_disabled"


async def test_beep_start_allowed_when_hearing_on(tmp_db, disable_auth):
    """Слух включён — гейт пропускает дальше (упадёт на отсутствии ffmpeg в песочнице,
    но НЕ на attention_hearing_disabled)."""
    from app.database import init_db
    from app.beep_pipeline import BeepPipeline

    await init_db()
    a, _ = _new_analyzer()
    a.update_settings(7, {"attention_hearing": True})

    import app.server as server_mod
    saved = getattr(server_mod, "chat_analyzer", None)
    server_mod.chat_analyzer = a
    try:
        result = await BeepPipeline().start({"account_id": 7, "enabled": True})
    finally:
        server_mod.chat_analyzer = saved
    assert result.get("error") != "attention_hearing_disabled"


# ─────────────── API: переключатели доступны через analyzer settings ───────────────

async def test_attention_via_analyzer_api(tmp_db, disable_auth):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import init_db
    from app.routes import router

    await init_db()
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.put(
            "/api/accounts/1/analyzer",
            json={"attention_vision": False, "attention_hearing": False, "attention_chat_ai": False},
        )
        assert resp.status_code == 200
        data = (await c.get("/api/accounts/1/analyzer")).json()
        assert data["attention_vision"] is False
        assert data["attention_hearing"] is False
        assert data["attention_chat_ai"] is False
