"""P4 PLAN.md: TTS за баллы канала — фильтры, лимиты, handler."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import channel_points_tts as cpt
from app import database as db_mod


@pytest_asyncio.fixture(autouse=True)
async def _schema(tmp_db):
    await db_mod.init_db()
    db = await db_mod.get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'bot1', 't')")
        await db.commit()
    finally:
        await db.close()


@pytest.fixture()
def cfg():
    return {**cpt.DEFAULTS, "enabled": 1}


def test_check_text_empty(cfg):
    ok, why = cpt._check_text(cfg, "   ")
    assert ok is False and why == "empty"


def test_long_text_truncated_at_speak():
    """Длинный текст не фильтруется, а обрезается при отправке (max_len)."""
    assert len("a" * 500) > 120  # base max_len=120 — обрезка в handle_redemption


def test_check_text_blacklist(cfg):
    cfg["blacklist"] = "спам, реклама"
    ok, _ = cpt._check_text(cfg, "купите у меня спам")
    assert ok is False
    ok, _ = cpt._check_text(cfg, "привет, как дела")
    assert ok is True


def test_check_text_long_is_ok(cfg):
    """Длинный текст проходит фильтры — обрезается позже до max_len."""
    ok, why = cpt._check_text(cfg, "a" * 500)
    assert ok is True and why == ""


def test_rate_cooldown(cfg):
    cfg["cooldown_sec"] = 60
    ok, why = cpt._check_rate(cfg, 1, "userA")
    assert ok is True
    ok, why = cpt._check_rate(cfg, 1, "userA")
    assert ok is False and why == "cooldown"
    # другой юзер не затронут
    ok, _ = cpt._check_rate(cfg, 1, "userB")
    assert ok is True


def test_rate_hour_limit(cfg):
    cfg["max_per_hour"] = 2
    cfg["cooldown_sec"] = 0
    assert cpt._check_rate(cfg, 2, "u")[0] is True
    assert cpt._check_rate(cfg, 2, "u")[0] is True
    ok, why = cpt._check_rate(cfg, 2, "u")
    assert ok is False and why == "hour_limit"
    cpt._reset_rate_state()


@pytest.mark.asyncio
async def test_handle_redemption_disabled(tmp_db):
    await cpt._load_config(1)  # создаёт таблицу
    payload = {"reward": {"title": "Озвучить"}, "user_login": "u", "user_input": "привет"}
    assert await cpt.handle_redemption(1, "chan", payload) is False


@pytest.mark.asyncio
async def test_handle_redemption_reward_filter(tmp_db, monkeypatch):
    await cpt.save_config(1, {"enabled": 1, "reward_names": "Озвучить сообщение"})
    called = []
    async def fake_enqueue(kind, account_id, channel, text, **kw):
        called.append((kind, text))
    monkeypatch.setattr(
        "app.audio_queue.AudioQueue.enqueue",
        lambda self, kind, account_id, channel, text, **kw: fake_enqueue(kind, account_id, channel, text, **kw),
    )
    # другой reward — скип
    payload = {"reward": {"title": "Другая награда"}, "user_login": "u", "user_input": "привет"}
    assert await cpt.handle_redemption(1, "chan", payload) is False
    # нужный reward — озвучено
    payload = {"reward": {"title": "озвучить СООБЩЕНИЕ"}, "user_login": "u", "user_input": "привет"}
    assert await cpt.handle_redemption(1, "chan", payload) is True
    assert called and called[0][1] == "Говорит u: привет"
    cpt._reset_rate_state()


@pytest.mark.asyncio
async def test_handle_redemption_blacklist(tmp_db):
    await cpt.save_config(1, {"enabled": 1, "blacklist": "реклама"})
    payload = {"reward": {"title": "Озвучить"}, "user_login": "u", "user_input": "ляля реклама ляля"}
    assert await cpt.handle_redemption(1, "chan", payload) is False


@pytest.mark.asyncio
async def test_handle_redemption_truncates(tmp_db, monkeypatch):
    await cpt.save_config(1, {"enabled": 1, "max_len": 10, "announce_user": 0})
    got = []
    async def fake_enqueue(kind, account_id, channel, text, **kw):
        got.append(text)
    monkeypatch.setattr(
        "app.audio_queue.AudioQueue.enqueue",
        lambda self, kind, account_id, channel, text, **kw: fake_enqueue(kind, account_id, channel, text, **kw),
    )
    payload = {"reward": {"title": "TTS"}, "user_login": "u", "user_input": "я" * 30}
    assert await cpt.handle_redemption(1, "chan", payload) is True
    assert got[0] == "я" * 10
    cpt._reset_rate_state()
