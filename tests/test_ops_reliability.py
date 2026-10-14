"""OPS_PLAN §3 — надёжность: end-to-end сценарии fallback, crash-изоляция, watchdog.

Проверяем:
1. OpenRouter вернул пустой ответ (429/5xx как пустые) → авто-fallback на Ollama,
   событие «fallback» видно в bot_logs (панель показывает его во вкладке логов).
2. FallbackRouter: 2 подряд ошибки → cooldown → resolve() возвращает ollama;
   после успеха провайдер восстанавливается.
3. TTS-цепочка: ElevenLabs без ключа → деградация до Web Speech (OBS-событие есть).
4. TTS: ошибка синтеза провайдера → Web Speech fallback.
5. Crash-изоляция: падающая задача одного бота не убивает другие боты;
   watchdog переподнимает пропавший инстанс, живой не трогается.
"""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def _seed_account(account_id: int = 1, nickname: str = "opsbot") -> None:
    """bot_logs/tts_bot_config ссылаются на accounts (FK) — сеем бота перед тестом."""
    from app import database
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, 'oauth:x', 1) "
            "ON CONFLICT(id) DO NOTHING",
            (account_id, nickname),
        )
        await db.commit()
    finally:
        await db.close()


# ── 1. AI fallback: пустой ответ облачного провайдера → Ollama ──


async def test_ai_text_fallback_to_ollama_on_empty_response(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    await _seed_account()

    from app.ai_service import AIService
    svc = AIService()
    monkeypatch.setattr(svc, "local_fallback_enabled", True)

    async def broken_openrouter(*args, **kwargs):  # 429/5xx приходят как пустой ответ
        return ""

    async def local_ollama(*args, **kwargs):
        return "локальный ответ"

    monkeypatch.setattr(svc, "_openrouter_chat", broken_openrouter)
    monkeypatch.setattr(svc, "_ollama_chat", local_ollama)
    svc.provider = "openrouter"
    svc.ollama_chat = "llama3"

    result = await svc.generate_text("привет", system="s", account_id=1, channel="#test")
    assert result == "локальный ответ"

    # Событие fallback записано в bot_logs — видно в панели
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT category, level, message FROM bot_logs WHERE account_id = 1 AND category = 'fallback'"
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    assert row is not None
    assert row["level"] == "warning"
    assert "ollama" in row["message"].lower()


async def test_ai_vision_fallback_to_ollama(tmp_db, monkeypatch):
    from app import database
    await database.init_db()

    from app.ai_service import AIService
    from PIL import Image
    svc = AIService()
    monkeypatch.setattr(svc, "local_fallback_enabled", True)

    async def broken_vision(*args, **kwargs):
        return ""

    async def local_vision(*args, **kwargs):
        return "на кадре кот"

    monkeypatch.setattr(svc, "_openrouter_vision", broken_vision)
    monkeypatch.setattr(svc, "_ollama_vision", local_vision)
    svc.provider = "openrouter"

    img = Image.new("RGB", (8, 8), color=(10, 200, 10))
    result = await svc.analyze_image(img, "что на кадре?", account_id=1, channel="#test")
    assert result == "на кадре кот"


# ── 2. FallbackRouter: cooldown и восстановление ──


async def test_fallback_router_cooldown_and_recovery():
    from app.local_fallback import FallbackRouter, classify_error_message, classify_error_status

    assert classify_error_status(429) == "ratelimit"
    assert classify_error_status(503) == "server_error"
    assert classify_error_message("Request timeout") == "timeout"

    router = FallbackRouter(fallback_provider="ollama")
    assert router.resolve("openrouter") == "openrouter"

    # 2 подряд fallback-ошибки → cooldown → трафик уходит на Ollama
    router.record_failure("openrouter", "ratelimit")
    assert router.resolve("openrouter") == "openrouter"  # порог ещё не достигнут
    router.record_failure("openrouter", "server_error")
    assert router.resolve("openrouter") == "ollama"

    # success сбрасывает здоровье — провайдер возвращается в строй
    router.record_success("openrouter")
    assert router.resolve("openrouter") == "openrouter"

    # auth-ошибки не включают fallback (проблема не у провайдера)
    router.record_failure("gemini", "auth")
    router.record_failure("gemini", "auth")
    assert router.resolve("gemini") == "gemini"


# ── 3/4. TTS-цепочка: деградация до Web Speech ──


def _capture_broadcast(monkeypatch):
    events: list[dict] = []

    async def fake_broadcast(**kwargs):
        events.append(kwargs)

    import app.tts_engine as tts_mod
    monkeypatch.setattr(tts_mod, "broadcast_tts_event", fake_broadcast)
    return events


async def _enable_bot_tts(account_id: int, provider: str) -> None:
    from app import database
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO tts_bot_config (account_id, provider, enabled) "
            "VALUES (?, ?, 1) "
            "ON CONFLICT(account_id) DO UPDATE SET provider = excluded.provider, enabled = 1",
            (account_id, provider),
        )
        await db.commit()
    finally:
        await db.close()


async def test_tts_elevenlabs_without_key_degrades_to_web_speech(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    await _seed_account()
    await _enable_bot_tts(1, "elevenlabs")

    from app.tts_engine import TTSEngine
    engine = TTSEngine()
    events = _capture_broadcast(monkeypatch)

    await engine.speak(1, "#test", "привет чат")
    assert events, "OBS-событие должно быть отправлено даже без ElevenLabs"
    assert events[0]["provider"] == "web_speech"
    assert events[0]["text"] == "привет чат"


async def test_tts_provider_error_falls_back_to_web_speech(tmp_db, monkeypatch):
    from app import database
    await database.init_db()
    await _seed_account()
    await _enable_bot_tts(1, "piper")

    from app.tts_engine import TTSEngine
    engine = TTSEngine()
    events = _capture_broadcast(monkeypatch)

    class BrokenProvider:
        async def synthesize(self, *args, **kwargs):
            raise RuntimeError("Piper model not available")

    async def broken_provider(name, account_id):
        return BrokenProvider()

    monkeypatch.setattr(engine, "_get_provider", broken_provider)

    await engine.speak(1, "#test", "привет чат")
    assert events, "после ошибки синтеза должен быть Web Speech fallback"
    assert events[-1]["provider"] == "web_speech"


async def test_tts_queue_overload_cancels_stale(tmp_db, monkeypatch):
    """§3: при переполнении очереди (100) старые тикеты отменяются, а не копятся."""
    from app import database
    await database.init_db()
    await _seed_account()
    await _enable_bot_tts(1, "web_speech")

    import app.tts_engine as tts_mod
    engine = tts_mod.TTSEngine()

    slow = asyncio.Event()

    class SlowProvider:
        async def synthesize(self, *args, **kwargs):
            await slow.wait()
            return b"x"

    async def always_slow(name, account_id):
        return SlowProvider()

    monkeypatch.setattr(engine, "_get_provider", always_slow)

    tasks = [asyncio.create_task(engine.speak(1, "#t", f"msg {i}")) for i in range(105)]
    # §3: pending (очередь + семафор) ограничен — перегруз отменяет новые запросы.
    # Ждём, пока все 105 дойдут до постановки в очередь (DB-операции серийные).
    for _ in range(100):
        await asyncio.sleep(0.1)
        async with engine._queue_lock:
            if engine._pending >= 100:
                break
    async with engine._queue_lock:
        assert engine._pending <= 100
    # Перегруз отменяет лишние speak() досрочно: они завершились, НЕ дождавшись
    # синтеза (провайдер всё ещё заблокирован slow-событием).
    finished_early = [t for t in tasks if t.done() and not t.exception()]
    assert finished_early, "лишние тикеты должны отменяться при перегрузе"
    assert not slow.is_set()
    slow.set()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


# ── 5. Crash-изоляция и watchdog ──


class _FakeBot:
    def __init__(self, inst, behavior):
        self._inst = inst
        self._behavior = behavior

    async def start(self):
        if self._behavior == "crash":
            raise RuntimeError("соединение упало")
        self._inst.connected = True
        self._inst.state = "online"
        await asyncio.sleep(3600)

    async def close(self):
        pass


def _patch_create_bot(monkeypatch, behaviors: dict[int, str]):
    from app.bot_manager import TwitchBotManager

    def fake_create_bot(self, instance):
        return _FakeBot(instance, behaviors.get(instance.account_id, "ok"))

    monkeypatch.setattr(TwitchBotManager, "_create_bot", fake_create_bot)


async def test_crash_isolation_dead_task_does_not_kill_other_bots(tmp_db, monkeypatch):
    """Задача бота №1 падает с исключением → №2 продолжает работать.

    run_bot() перехватывает исключение и уходит в reconnect-backoff, поэтому
    крах одного бота не распространяется на процесс и другие боты.
    """
    from app.bot_manager import TwitchBotManager
    _patch_create_bot(monkeypatch, {1: "crash", 2: "ok"})

    manager = TwitchBotManager()
    ok1 = await manager.start_bot(1, "crashbot", "oauth:x", ["a"])
    ok2 = await manager.start_bot(2, "healthybot", "oauth:x", ["b"])
    assert ok1 and ok2

    task1 = manager._bots[1].task
    task2 = manager._bots[2].task

    await asyncio.sleep(2.4)  # первый крах → retry=1 → sleep(2s) внутри run_bot

    assert not task1.done(), "задача упавшего бота должна жить (reconnect-loop)"
    assert manager._bots[1].reconnect_count >= 1
    assert manager._bots[2].connected, "здоровый бот не должен пострадать"
    assert not task2.done()

    await manager.stop_all()
    assert manager._bots == {}


async def test_watchdog_restores_missing_instance_only(tmp_db, monkeypatch):
    """Watchdog: пропавший инстанс переподнимается, живой не перезапускается."""
    from app.bot_manager import TwitchBotManager
    _patch_create_bot(monkeypatch, {2: "ok"})

    manager = TwitchBotManager()
    await manager.start_bot(2, "healthybot", "oauth:x", ["b"])
    task2_before = manager._bots[2].task

    # Бот 1 «желает» работать, но инстанса нет (например, процесс упал между
    # start_bot и регистрацией) — watchdog должен его поднять.
    manager.set_desired(1, {"nickname": "lostbot", "token": "oauth:x", "channels": ["a"], "proxy": ""})
    manager.set_desired(2, {"nickname": "healthybot", "token": "oauth:x", "channels": ["b"], "proxy": ""})

    wd = asyncio.create_task(manager.watchdog_loop(interval=0.05))
    await asyncio.sleep(0.4)
    wd.cancel()
    await asyncio.gather(wd, return_exceptions=True)

    assert 1 in manager._bots, "watchdog должен переподнять пропавшего бота"
    assert manager._bots[2].task is task2_before, "живого бота трогать нельзя"

    await manager.stop_all()
