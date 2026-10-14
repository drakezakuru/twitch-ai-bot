from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app import database
from app.api_errors import install_api_error_handlers
from app.routes_tts_config import get_tts_bot_config


def _error_app() -> FastAPI:
    app = FastAPI()
    install_api_error_handlers(app)

    @app.get("/structured")
    async def structured() -> None:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_channel", "params": {"channel": "demo"}},
        )

    @app.get("/validate/{item_id}")
    async def validate(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/internal")
    async def internal() -> None:
        raise RuntimeError("private-token-and-traceback")

    @app.get("/legacy-internal")
    async def legacy_internal() -> None:
        raise HTTPException(status_code=500, detail="private_token")

    return app


@pytest.mark.asyncio
async def test_http_error_matrix_uses_stable_envelope() -> None:
    transport = ASGITransport(app=_error_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        structured = await client.get("/structured")
        validation = await client.get("/validate/not-an-int")
        missing = await client.get("/missing")

    assert structured.status_code == 400
    assert structured.json() == {
        "ok": False,
        "error": {"code": "invalid_channel", "params": {"channel": "demo"}},
    }
    assert validation.status_code == 422
    assert validation.json() == {
        "ok": False, "error": {"code": "request_invalid", "params": {}},
    }
    assert missing.status_code == 404
    assert missing.json() == {
        "ok": False, "error": {"code": "not_found", "params": {}},
    }


@pytest.mark.asyncio
async def test_internal_error_never_leaks_exception_text() -> None:
    transport = ASGITransport(app=_error_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/internal")
        legacy_response = await client.get("/legacy-internal")

    assert response.status_code == 500
    assert response.json() == {
        "ok": False, "error": {"code": "internal_error", "params": {}},
    }
    assert "private-token" not in response.text
    assert legacy_response.json() == {
        "ok": False, "error": {"code": "internal_error", "params": {}},
    }
    assert "private_token" not in legacy_response.text


@pytest_asyncio.fixture
async def _tts_schema(tmp_db):
    await database.init_db()


@pytest.mark.asyncio
async def test_empty_tts_config_returns_defaults_without_writing(_tts_schema) -> None:
    db = await database.get_db()
    try:
        await db.execute(
            "UPDATE tts_settings SET provider = 'piper', voice = 'demo', volume = 0.4, speed = 1.2 "
            "WHERE id = 1"
        )
        await db.commit()
        before = (await (await db.execute("SELECT COUNT(*) FROM tts_bot_config")).fetchone())[0]
    finally:
        await db.close()

    response = await get_tts_bot_config(77)

    db = await database.get_db()
    try:
        after = (await (await db.execute("SELECT COUNT(*) FROM tts_bot_config")).fetchone())[0]
    finally:
        await db.close()
    assert before == after == 0
    assert response == {
        "ok": True,
        "configured": False,
        "config": {
            "provider": "piper", "voice": "demo", "emotion_preset": "neutral",
            "volume": 0.4, "speed": 1.2, "enabled": 0,
            "widget_color": "#FFD700", "widget_emoji": "🎙️",
            "emoji_prefix": "", "emoji_suffix": "",
        },
    }
