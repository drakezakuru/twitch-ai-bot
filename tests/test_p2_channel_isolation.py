"""PLAN §2.1 + §9e: per-channel overrides в runtime и история настроения стримера.

Проверяем:
1. channel_overrides реально применяются: POST /api/accounts/{id}/channel-overrides
   с новыми ключами (auto_chat/silent_mode/cooldown/context_source_*/tts_mute)
   → ChatAnalyzer._merged_settings отдаёт слитые настройки; база не мутирует.
2. Ключи вне allowlist не применяются; disabled override не применяется.
3. invalidate_channel_overrides сбрасывает кэш.
4. §9e: StreamerMoodTracker.snapshot() содержит history — только переходы label.
"""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _seed_account(account_id: int) -> None:
    from app import database
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO accounts (id, nickname, token, enabled) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(id) DO NOTHING",
            (account_id, f"bot{account_id}", "oauth:x"),
        )
        await db.commit()
    finally:
        await db.close()


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _analyzer():
    from app.chat_analyzer import ChatAnalyzer
    from app.ai_service import AIService
    return ChatAnalyzer(ai=AIService(), send_fn=lambda *a, **kw: None)


async def test_channel_override_merge_runtime(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    await _seed_account(5)
    async with await _client() as c:
        put = (await c.put("/api/accounts/5/channel-overrides", json={
            "channel": "MergeChan",
            "enabled": True,
            "overrides": {
                "auto_chat": False, "silent_mode": True, "cooldown": 45,
                "context_source_chat": False, "context_source_stream": True,
                "tts_mute": True, "humor_level": 80,
                "evil_unknown_key": 123,
            },
        })).json()
        assert put["ok"] is True

        ana = await _analyzer()
        base = ana.get_settings(5)
        base_cooldown = base["cooldown"]
        merged = await ana._merged_settings(5, "mergechan", base)

        assert merged["auto_chat"] is False
        assert merged["silent_mode"] is True
        assert merged["cooldown"] == 45
        assert merged["context_source_chat"] is False
        assert merged["context_source_stream"] is True
        assert merged["tts_mute"] is True
        assert merged["humor_level"] == 80
        # ключ вне allowlist не применяется
        assert "evil_unknown_key" not in merged
        # база не мутирована
        assert ana.get_settings(5)["cooldown"] == base_cooldown

        # disabled override не применяется
        await c.put("/api/accounts/5/channel-overrides", json={
            "channel": "mergechan", "enabled": False,
            "overrides": {"cooldown": 300},
        })
        ana.invalidate_channel_overrides(5, "mergechan")
        merged2 = await ana._merged_settings(5, "mergechan", ana.get_settings(5))
        assert merged2["cooldown"] == base_cooldown


async def test_channel_override_cache_invalidation(tmp_db, disable_auth):
    from app import database
    await database.init_db()
    await _seed_account(6)
    ana = await _analyzer()
    async with await _client() as c:
        await c.put("/api/accounts/6/channel-overrides", json={
            "channel": "cachechan", "enabled": True, "overrides": {"cooldown": 33},
        })
        merged = await ana._merged_settings(6, "cachechan", ana.get_settings(6))
        assert merged["cooldown"] == 33

        # Обновление + инвалидация кэша (PUT инвалидирует кэш рантайм-инстанса) → сразу видно
        await c.put("/api/accounts/6/channel-overrides", json={
            "channel": "cachechan", "enabled": True, "overrides": {"cooldown": 77},
        })
        ana.invalidate_channel_overrides(6, "cachechan")
        merged2 = await ana._merged_settings(6, "cachechan", ana.get_settings(6))
        assert merged2["cooldown"] == 77


# test_streamer_mood_snapshot_history удалён: бэкенд `app/streamer_mood.py`
# намеренно вырезан коммитом adec202 («remove dead streamer mood and pacing
# backends»), тест остался висеть и падал с ModuleNotFoundError. Возвращать
# его можно только вместе с самим модулем.
