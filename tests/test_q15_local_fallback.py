"""Q15c (E4): локальный fallback на Ollama — выключен по умолчанию,
включается вручную per-бот («резерв: локальная Ollama»), circuit breaker
(BUG-4) остаётся.

Проверяем:
1. ``AIService`` по умолчанию имеет fallback выключенным (env не задан).
2. ``_local_fallback_for``: без override — глобальный флаг; с per-бот
   флагом — включён, даже когда глобальный выключен.
3. ``set_account_override`` не выбрасывает запись, у которой включён только
   резерв (иначе бот не смог бы включить один лишь fallback).
4. API: PUT ``ai-override`` с ``ai_local_fallback`` сохраняется и возвращается
   GET-ом; колонка ``accounts.ai_local_fallback`` создаётся миграцией.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


async def _client():
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _service(monkeypatch):
    import os
    from app.ai_service import AIService
    monkeypatch.delenv("LOCAL_FALLBACK_ENABLED", raising=False)
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    for name in [k for k in os.environ if k.startswith("OLLAMA")]:
        monkeypatch.delenv(name, raising=False)
    return AIService()


async def test_local_fallback_disabled_by_default(monkeypatch):
    svc = _service(monkeypatch)
    assert svc.local_fallback_enabled is False, "E4: fallback выключен по умолчанию"
    assert svc._local_fallback_for(0) is False
    assert svc._local_fallback_for(42) is False


async def test_per_bot_flag_enables_fallback_without_global(monkeypatch):
    from app.ai_service import AccountAIOverride
    svc = _service(monkeypatch)
    svc.set_account_override(7, AccountAIOverride(local_fallback=True))
    assert svc._local_fallback_for(7) is True, "per-бот opt-in работает без глобального"
    assert svc._local_fallback_for(8) is False, "другой бот не наследует чужой opt-in"
    # env-рубильник остаётся глобальным fallback-каналом для ботов без выбора
    svc.local_fallback_enabled = True
    assert svc._local_fallback_for(8) is True


async def test_override_with_only_fallback_flag_is_kept(monkeypatch):
    from app.ai_service import AccountAIOverride
    svc = _service(monkeypatch)
    svc.set_account_override(9, AccountAIOverride(local_fallback=True))
    assert svc.get_account_override(9) is not None, \
        "запись с одним лишь резервом не должна считаться пустой"
    svc.set_account_override(9, AccountAIOverride())
    assert svc.get_account_override(9) is None, "без всего — запись удаляется как раньше"


async def test_ai_override_roundtrip_persists_local_fallback(tmp_db, disable_auth, monkeypatch):
    from app import database
    await database.init_db()
    db = await database.get_db()
    await db.execute("INSERT INTO accounts (nickname, token) VALUES ('bot1', 'tok')")
    await db.commit()
    await db.close()

    async with await _client() as c:
        put = (await c.put("/api/accounts/1/ai-override", json={
            "ai_local_fallback": True,
        })).json()
        assert put["ok"] is True and put["ai_local_fallback"] is True
        got = (await c.get("/api/accounts/1/ai-override")).json()
        assert got["ai_local_fallback"] is True

        off = (await c.put("/api/accounts/1/ai-override", json={
            "ai_local_fallback": False,
        })).json()
        assert off["ai_local_fallback"] is False

    # колонка мигрирована в чистую тестовую БД ленивой _add_column_if_missing
    db = await database.get_db()
    cur = await db.execute("SELECT ai_local_fallback FROM accounts WHERE id = 1")
    row = await cur.fetchone()
    assert row["ai_local_fallback"] == 0
