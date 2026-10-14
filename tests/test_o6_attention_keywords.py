"""О6 PLAN.md (§9 ОСТАТОК): «Когда бот отвечает» — ключевые слова + пояснение задержки.

Переименование заголовка, тумблер упоминаний, «не перебивать стримера» уже
были (§7.1 §9). Новое: reply_to_keywords + reply_keywords (тумблер + список),
pass-through сквозь шум и режим внимания, пояснение задержки в UI.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest
from httpx import AsyncClient, ASGITransport


def _msg(author: str, text: str) -> dict:
    return {"author": author, "text": text, "ts": "2026-08-31 12:00:00"}


def test_keywords_pass_through_noise_and_mode():
    """Сообщение с ключевым словом проходит сквозь шум и streamer_only."""
    from app.attention_filter import AttentionFilter
    af = AttentionFilter()
    batch = [
        _msg("streamer1", "+1"),               # шум от стримера
        _msg("streamer1", "когда розыгрыш?"),  # шум + ключевое слово
        _msg("viewer1", "привет"),             # обычное от зрителя
    ]
    cfg = {
        "attention_mode": "streamer_only",
        "ignore_noise": 1,
        "reply_to_keywords": 1,
        "reply_keywords": "розыгрыш",
    }
    out = af.apply_filter(batch, cfg, None, "streamer1")
    texts = [m["text"] for m in out]
    assert "когда розыгрыш?" in texts   # ключевое слово пробило шум и режим
    assert "+1" not in texts            # обычный шум отфильтрован
    assert "привет" not in texts        # режим streamer_only работает


def test_keywords_disabled_no_passthrough():
    """Тумблер выкл → старое поведение: ключевое слово не спасает зрителя в streamer_only."""
    from app.attention_filter import AttentionFilter
    af = AttentionFilter()
    batch = [_msg("viewer1", "когда розыгрыш?")]
    cfg = {
        "attention_mode": "streamer_only",
        "ignore_noise": 1,
        "reply_to_keywords": 0,
        "reply_keywords": "розыгрыш",
    }
    out = af.apply_filter(batch, cfg, None, "streamer1")
    assert out == []


def test_keywords_custom_mode_passthrough():
    """custom-режим: ключевое слово проходит и для не-включённых юзеров."""
    from app.attention_filter import AttentionFilter
    af = AttentionFilter()
    batch = [_msg("random_user", "а будет розыгрыш?")]
    cfg = {
        "attention_mode": "custom",
        "ignore_noise": 0,
        "reply_to_keywords": 1,
        "reply_keywords": "розыгрыш",
    }
    out = af.apply_filter(batch, cfg, {"enabled_user"}, "streamer1")
    assert len(out) == 1


@pytest.mark.asyncio
async def test_attention_config_roundtrip_keywords(tmp_db, disable_auth):
    """PUT/GET attention-config сохраняет и возвращает ключевые слова."""
    from app.database import init_db, get_db
    await init_db()
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (1, 'b1', 't')")
        await db.commit()
    finally:
        await db.close()
    from fastapi import FastAPI
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/accounts/1/attention-config")
        assert r.status_code == 200
        assert r.json()["config"]["reply_to_keywords"] == 0  # дефолт без регресса

        put = await c.put("/api/accounts/1/attention-config", json={
            "reply_to_keywords": 1,
            "reply_keywords": "вопрос, помоги",
        })
        assert put.status_code == 200 and put.json()["ok"] is True

        r2 = await c.get("/api/accounts/1/attention-config")
        cfg = r2.json()["config"]
        assert cfg["reply_to_keywords"] == 1
        assert cfg["reply_keywords"] == "вопрос, помоги"
        # старые поля не потерялись
        assert cfg["reply_to_mentions"] == 1
        assert cfg["attention_mode"] == "everyone"


def test_ui_has_keywords_markup_and_translations():
    """UI: controls and delay hint remain translated in ru/en/ua."""
    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "partials" / "bots.html").read_text()
    assert 'id="botReplyKeywords"' in tpl
    assert 'id="botReplyKeywordsList"' in tpl
    assert 'data-i18n="attention.delay_hint"' in tpl
    js = (root / "static" / "app" / "15_feedback_2908.js").read_text()
    for key in ("attention.reply_keywords", "attention.keywords", "attention.delay_hint"):
        assert js.count(f"'{key}'") >= 3


def test_attention_panel_runtime_behavior():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for panel behavior tests")
    subprocess.run(
        [node, "--test", "tests/attention_config_ui.test.js"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )
