"""Explicit Director provider calls use HTTP fakes, never a live service."""

import json

import httpx
import pytest

from app.ai_service import AIService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    ["openrouter", "ollama", "gemini", "openai", "anthropic", "custom", "custom:named"],
)
async def test_explicit_provider_preserves_model_budget_and_no_credential_fallback(
    provider,
):
    ai = AIService()
    await ai._client.aclose()
    ai.openrouter_key = ai.gemini_key = ai.openai_key = ai.anthropic_key = (
        "fake-owner-key"
    )
    ai.custom_base_url = "http://custom.invalid/v1"
    ai.custom_api_key = ""
    ai.set_custom_providers(
        [
            {
                "name": "named",
                "base_url": "http://named.invalid/v1",
                "api_key": "",
                "models": ["other-default"],
                "enabled": 1,
            }
        ]
    )
    calls = []

    def handle(request):
        calls.append(request)
        payload = json.loads(request.content)
        if provider == "gemini":
            assert "/models/chosen-model:" in str(request.url)
            assert payload["generationConfig"] == {
                "maxOutputTokens": 900,
                "temperature": 0.2,
            }
            body = {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
        elif provider == "ollama":
            assert payload["model"] == "chosen-model"
            assert payload["options"] == {"num_predict": 900, "temperature": 0.2}
            body = {"response": "OK"}
        else:
            assert payload["model"] == "chosen-model" and payload["max_tokens"] == 900
            assert payload["temperature"] == 0.2
            body = (
                {"content": [{"type": "text", "text": "OK"}]}
                if provider == "anthropic"
                else {"choices": [{"message": {"content": "OK"}}]}
            )
        if provider.startswith("custom"):
            assert "authorization" not in request.headers
            assert request.url.host == (
                "named.invalid" if ":" in provider else "custom.invalid"
            )
        return httpx.Response(200, json=body)

    ai._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        result = await ai.generate_text_with(
            provider,
            "chosen-model",
            "synthetic request",
            "immutable safety",
            temperature=0.2,
            max_tokens=900,
        )
        assert result == {"ok": True, "error": "", "response": "OK"}
        assert len(calls) == 1
    finally:
        await ai.close()


@pytest.mark.asyncio
async def test_custom_failure_never_tries_cloud_or_another_model():
    ai = AIService()
    await ai._client.aclose()
    ai.custom_base_url = "http://custom.invalid/v1"
    ai.custom_api_key = ""
    ai.openai_key = "fake-owner-key"
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "custom.invalid"
        assert "authorization" not in request.headers
        return httpx.Response(503, text="unavailable")

    ai._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        assert not (await ai.generate_text_with("custom", "chosen-model", "synthetic"))[
            "ok"
        ]
        assert len(calls) == 1
    finally:
        await ai.close()
