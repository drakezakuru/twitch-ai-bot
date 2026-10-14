"""v10.4.3: тесты прямых провайдеров Gemini / OpenAI / Anthropic.

Без сетевых вызовов — мокаем httpx.AsyncClient.post и проверяем что:
1. URL/headers/payload корректные для каждого провайдера;
2. Извлечение текста из ответа работает (включая edge cases);
3. _resolve() корректно подставляет per-provider дефолты и api_key override.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai_service import AccountAIOverride, AIService


# ============== fixtures ==============

@pytest.fixture()
def ai(monkeypatch):
    """Чистый AIService с env-defaults (без реальных ключей)."""
    for k in (
        "AI_PROVIDER", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    svc = AIService()
    # Заполняем ключи руками (без реального их использования)
    svc.gemini_key = "GEMINI_TEST_KEY"
    svc.openai_key = "OPENAI_TEST_KEY"
    svc.anthropic_key = "ANT_TEST_KEY"
    return svc


def _fake_response(status_code: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json = MagicMock(return_value=json_data or {})
    resp.raise_for_status = MagicMock()
    return resp


# ============== _resolve() ==============

def test_resolve_gemini_default(ai):
    ai.provider = "gemini"
    provider, chat, vision, key = ai._resolve(account_id=0)
    assert provider == "gemini"
    assert chat == "gemini-2.0-flash"
    assert vision == "gemini-2.0-flash"
    assert key == "GEMINI_TEST_KEY"


def test_resolve_openai_default(ai):
    ai.provider = "openai"
    ai.openai_chat = "gpt-4o-mini"
    provider, chat, _vision, key = ai._resolve(account_id=0)
    assert provider == "openai"
    assert chat == "gpt-4o-mini"
    assert key == "OPENAI_TEST_KEY"


def test_resolve_anthropic_default(ai):
    ai.provider = "anthropic"
    ai.anthropic_chat = "claude-3-5-haiku-latest"
    provider, chat, _vision, key = ai._resolve(account_id=0)
    assert provider == "anthropic"
    assert chat == "claude-3-5-haiku-latest"
    assert key == "ANT_TEST_KEY"


def test_resolve_per_account_override_switches_to_gemini(ai):
    """Глобально openrouter, аккаунт 7 хочет gemini со своим ключом."""
    ai.provider = "openrouter"
    ai.set_account_override(
        7,
        AccountAIOverride(
            provider="gemini",
            chat_model="gemini-1.5-pro",
            api_key="ACC7_GEMINI_KEY",
        ),
    )
    provider, chat, _vision, key = ai._resolve(account_id=7)
    assert provider == "gemini"
    assert chat == "gemini-1.5-pro"
    assert key == "ACC7_GEMINI_KEY"
    # Другой аккаунт — без override — продолжает использовать глобальный openrouter.
    provider2, _, _, _ = ai._resolve(account_id=42)
    assert provider2 == "openrouter"


def test_resolve_api_key_falls_back_to_legacy_openrouter_key(ai):
    """Если api_key пуст, но задан legacy openrouter_key — используется он."""
    ai.provider = "openrouter"
    ai.openrouter_key = ""
    ai.set_account_override(7, AccountAIOverride(openrouter_key="LEGACY_KEY"))
    _provider, _chat, _vision, key = ai._resolve(account_id=7)
    assert key == "LEGACY_KEY"


# ============== Gemini ==============

@pytest.mark.asyncio
async def test_gemini_chat_calls_correct_endpoint_and_extracts_text(ai):
    captured: dict = {}

    async def fake_post(url, **kw):
        captured["url"] = url
        captured["params"] = kw.get("params")
        captured["json"] = kw.get("json")
        return _fake_response(200, {
            "candidates": [{
                "content": {"parts": [{"text": "Привет!"}]},
            }],
        })

    ai._client.post = AsyncMock(side_effect=fake_post)
    text = await ai._gemini_chat("Hello", system="be friendly", temperature=0.3)
    assert text == "Привет!"
    assert "generativelanguage.googleapis.com" in captured["url"]
    assert "gemini-2.0-flash:generateContent" in captured["url"]
    assert captured["params"] == {"key": "GEMINI_TEST_KEY"}
    body = captured["json"]
    assert body["generationConfig"]["temperature"] == 0.3
    assert "be friendly" in body["contents"][0]["parts"][0]["text"]
    assert "Hello" in body["contents"][0]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_gemini_vision_includes_inline_data(ai):
    captured: dict = {}

    async def fake_post(url, **kw):
        captured["json"] = kw.get("json")
        return _fake_response(200, {
            "candidates": [{"content": {"parts": [{"text": "Я вижу красный квадрат"}]}}],
        })

    ai._client.post = AsyncMock(side_effect=fake_post)
    text = await ai._gemini_vision("BASE64IMG", "Что на картинке?")
    assert text == "Я вижу красный квадрат"
    parts = captured["json"]["contents"][0]["parts"]
    assert any("text" in p and p["text"] == "Что на картинке?" for p in parts)
    inline = [p for p in parts if "inline_data" in p][0]
    assert inline["inline_data"]["data"] == "BASE64IMG"
    assert inline["inline_data"]["mime_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_gemini_chat_returns_empty_on_http_error(ai):
    ai._client.post = AsyncMock(return_value=_fake_response(403, text="forbidden"))
    text = await ai._gemini_chat("x", "")
    assert text == ""


@pytest.mark.asyncio
async def test_gemini_chat_returns_empty_without_key(ai):
    ai.gemini_key = ""
    ai._client.post = AsyncMock()
    text = await ai._gemini_chat("x", "")
    assert text == ""
    ai._client.post.assert_not_awaited()


# ============== OpenAI ==============

@pytest.mark.asyncio
async def test_openai_chat_calls_correct_endpoint(ai):
    captured: dict = {}

    async def fake_post(url, **kw):
        captured["url"] = url
        captured["headers"] = kw.get("headers")
        captured["json"] = kw.get("json")
        return _fake_response(200, {
            "choices": [{"message": {"content": "Hi"}}],
        })

    ai._client.post = AsyncMock(side_effect=fake_post)
    text = await ai._openai_chat("Hello", system="ты бот", temperature=0.5)
    assert text == "Hi"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer OPENAI_TEST_KEY"
    body = captured["json"]
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.5
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == "Hello"


@pytest.mark.asyncio
async def test_openai_vision_includes_image_url(ai):
    captured: dict = {}

    async def fake_post(url, **kw):
        captured["json"] = kw.get("json")
        return _fake_response(200, {"choices": [{"message": {"content": "ok"}}]})

    ai._client.post = AsyncMock(side_effect=fake_post)
    text = await ai._openai_vision("BASE64IMG", "что тут?")
    assert text == "ok"
    content = captured["json"]["messages"][0]["content"]
    img = [c for c in content if c["type"] == "image_url"][0]
    assert img["image_url"]["url"].startswith("data:image/jpeg;base64,BASE64IMG")


@pytest.mark.asyncio
async def test_openai_chat_uses_custom_base(ai):
    """OPENAI_API_BASE даёт возможность подключиться к self-hosted vLLM/LM Studio."""
    ai.openai_base = "http://localhost:8001/v1"
    captured: dict = {}

    async def fake_post(url, **kw):
        captured["url"] = url
        return _fake_response(200, {"choices": [{"message": {"content": "ok"}}]})

    ai._client.post = AsyncMock(side_effect=fake_post)
    await ai._openai_chat("x", "")
    assert captured["url"] == "http://localhost:8001/v1/chat/completions"


# ============== Anthropic ==============

@pytest.mark.asyncio
async def test_anthropic_chat_uses_messages_endpoint(ai):
    captured: dict = {}

    async def fake_post(url, **kw):
        captured["url"] = url
        captured["headers"] = kw.get("headers")
        captured["json"] = kw.get("json")
        return _fake_response(200, {
            "content": [{"type": "text", "text": "Hi"}],
        })

    ai._client.post = AsyncMock(side_effect=fake_post)
    text = await ai._anthropic_chat("Hello", system="system-prompt")
    assert text == "Hi"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "ANT_TEST_KEY"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    body = captured["json"]
    # system промпт уходит в отдельное поле, а не в messages
    assert body["system"] == "system-prompt"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"


@pytest.mark.asyncio
async def test_anthropic_vision_attaches_image_block(ai):
    captured: dict = {}

    async def fake_post(url, **kw):
        captured["json"] = kw.get("json")
        return _fake_response(200, {"content": [{"type": "text", "text": "ok"}]})

    ai._client.post = AsyncMock(side_effect=fake_post)
    text = await ai._anthropic_vision("BASE64IMG", "что тут?")
    assert text == "ok"
    content = captured["json"]["messages"][0]["content"]
    img = [c for c in content if c["type"] == "image"][0]
    assert img["source"]["data"] == "BASE64IMG"
    assert img["source"]["media_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_anthropic_extracts_only_text_blocks(ai):
    """Anthropic может вернуть tool_use blocks вперемешку — берём только text."""
    ai._client.post = AsyncMock(return_value=_fake_response(200, {
        "content": [
            {"type": "tool_use", "name": "foo"},
            {"type": "text", "text": "part1 "},
            {"type": "text", "text": "part2"},
        ],
    }))
    text = await ai._anthropic_chat("x", "")
    assert text == "part1 part2"


# ============== Dispatch (generate_text / analyze_image) ==============

@pytest.mark.asyncio
async def test_generate_text_dispatches_to_gemini(ai):
    ai.provider = "gemini"
    ai._gemini_chat = AsyncMock(return_value="from-gemini")
    ai._openrouter_chat = AsyncMock(return_value="from-or")
    text = await ai.generate_text("hello", account_id=0)
    assert text == "from-gemini"
    ai._gemini_chat.assert_awaited_once()
    ai._openrouter_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_text_per_account_routes_anthropic(ai):
    """Глобально openrouter, у acc 7 override на anthropic."""
    ai.provider = "openrouter"
    ai.set_account_override(7, AccountAIOverride(provider="anthropic", api_key="ACC_ANT_KEY"))
    ai._anthropic_chat = AsyncMock(return_value="from-claude")
    ai._openrouter_chat = AsyncMock(return_value="from-or")
    text = await ai.generate_text("hi", account_id=7)
    assert text == "from-claude"
    # И ключ должен прокинуться в вызов:
    kwargs = ai._anthropic_chat.await_args.kwargs
    assert kwargs.get("api_key") == "ACC_ANT_KEY"


@pytest.mark.asyncio
async def test_test_connection_ok_for_gemini(ai):
    ai.provider = "gemini"
    ai._gemini_chat = AsyncMock(return_value="OK")
    result = await ai.test_connection()
    assert result["ok"] is True
    assert result["model"] == "gemini-2.0-flash"


@pytest.mark.asyncio
async def test_test_connection_fails_without_key(ai):
    ai.provider = "gemini"
    ai.gemini_key = ""
    result = await ai.test_connection()
    assert result["ok"] is False
    assert "GEMINI_API_KEY" in result["error"]


# ============== DEF-03: test_connection понимает custom:<имя> ==============

@pytest.mark.asyncio
async def test_test_connection_ok_for_named_custom_provider(ai):
    """custom:demo_provider — провайдер, на котором принят Режиссёр, обязан пинговаться."""
    ai.set_custom_providers([{
        "name": "demo_provider", "enabled": 1, "base_url": "https://api.demo_provider.example/v1",
        "api_key": "WK_KEY", "models": ["gpt-5.6-luna", "spare"], "vision_models": [],
    }])
    ai._openai_chat = AsyncMock(return_value="OK")
    result = await ai.test_connection(provider="custom:demo_provider")
    assert result["ok"] is True
    assert result["model"] == "gpt-5.6-luna", "пинг идёт первой chat-моделью провайдера"
    kwargs = ai._openai_chat.await_args.kwargs
    assert kwargs.get("base_url") == "https://api.demo_provider.example/v1"
    assert kwargs.get("api_key") == "WK_KEY"


@pytest.mark.asyncio
async def test_test_connection_reports_missing_named_provider(ai):
    result = await ai.test_connection(provider="custom:ghost")
    assert result["ok"] is False
    assert "ghost" in result["error"]
    assert "Unsupported" not in result["error"], "custom:<имя> больше не fallthrough в Unsupported"


@pytest.mark.asyncio
async def test_test_connection_reports_named_provider_without_models(ai):
    ai.set_custom_providers([{
        "name": "empty", "enabled": 1, "base_url": "https://x.example/v1",
        "api_key": "", "models": [], "vision_models": [],
    }])
    result = await ai.test_connection(provider="custom:empty")
    assert result["ok"] is False
    assert "no chat model" in result["error"]


@pytest.mark.asyncio
async def test_test_connection_named_provider_error_is_returned(ai):
    ai.set_custom_providers([{
        "name": "broken", "enabled": 1, "base_url": "https://broken.example/v1",
        "api_key": "K", "models": ["m1"], "vision_models": [],
    }])
    ai._openai_chat = AsyncMock(side_effect=RuntimeError("connect failed"))
    result = await ai.test_connection(provider="custom:broken")
    assert result["ok"] is False
    assert "connect failed" in result["error"]
