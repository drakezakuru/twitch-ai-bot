"""Тесты smart-routing в AIService."""

from __future__ import annotations

import pytest

from app.ai_service import AIService


@pytest.fixture
def svc(monkeypatch):
    # Сбросим env, чтобы AIService собирался с известными дефолтами.
    for v in (
        "AI_PROVIDER", "OPENROUTER_API_KEY", "OPENROUTER_CHAT_MODEL",
        "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "OLLAMA_HOST",
    ):
        monkeypatch.delenv(v, raising=False)
    s = AIService()
    yield s


class TestClassifyComplexity:
    def test_short_prompt_simple(self, svc):
        assert svc._classify_complexity("привет", "") == "simple"

    def test_long_prompt_complex(self, svc):
        long_prompt = "a" * 700
        assert svc._classify_complexity(long_prompt, "") == "complex"

    def test_complex_via_system_blocks(self, svc):
        # Несколько [блоков] в system → complex.
        system = "[Контекст] x\n[Память] y\n[Few-shot] z\n[Persona] q"
        assert svc._classify_complexity("ok", system) == "complex"

    def test_threshold_configurable(self, svc):
        svc.smart_routing_complexity_threshold = 100
        assert svc._classify_complexity("x" * 50, "") == "simple"
        assert svc._classify_complexity("x" * 150, "") == "complex"


class TestApplySmartRouting:
    def test_disabled_passthrough(self, svc):
        svc.smart_routing_enabled = False
        svc.smart_routing_simple_provider = "ollama"
        svc.smart_routing_simple_model = "llama3"
        out = svc._apply_smart_routing("anthropic", "claude-sonnet", "key", "simple")
        # Когда routing выключен — ничего не меняется.
        assert out == ("anthropic", "claude-sonnet", "key")

    def test_simple_routes_to_ollama(self, svc):
        svc.smart_routing_enabled = True
        svc.ollama_host = "http://localhost:11434"
        svc.smart_routing_simple_provider = "ollama"
        svc.smart_routing_simple_model = "llama3:8b"
        provider, model, key = svc._apply_smart_routing("anthropic", "claude-sonnet", "anth-key", "simple")
        assert provider == "ollama"
        assert model == "llama3:8b"
        assert key == ""  # ollama не требует ключ

    def test_complex_routes_to_anthropic(self, svc):
        svc.smart_routing_enabled = True
        svc.anthropic_key = "anth-key"
        svc.smart_routing_complex_provider = "anthropic"
        svc.smart_routing_complex_model = "claude-3-5-sonnet-latest"
        provider, model, key = svc._apply_smart_routing("ollama", "llama3", "", "complex")
        assert provider == "anthropic"
        assert model == "claude-3-5-sonnet-latest"
        assert key == "anth-key"

    def test_only_model_override_keeps_provider(self, svc):
        svc.smart_routing_enabled = True
        svc.smart_routing_simple_provider = ""
        svc.smart_routing_simple_model = "gpt-3.5"
        provider, model, key = svc._apply_smart_routing("openai", "gpt-4o", "k", "simple")
        # Провайдер тот же, но модель из override.
        assert provider == "openai"
        assert model == "gpt-3.5"
        assert key == "k"

    def test_invalid_provider_ignored(self, svc):
        svc.smart_routing_enabled = True
        svc.smart_routing_simple_provider = "totally-fake-provider"
        svc.smart_routing_simple_model = "x"
        provider, model, key = svc._apply_smart_routing("openai", "gpt-4o", "k", "simple")
        # Невалидный provider игнорируется, но модель применяется.
        assert provider == "openai"
        assert model == "x"
        assert key == "k"

    def test_unknown_complexity_passthrough(self, svc):
        svc.smart_routing_enabled = True
        svc.smart_routing_simple_provider = "ollama"
        provider, model, key = svc._apply_smart_routing("openai", "gpt-4o", "k", "auto")
        assert provider == "openai"
        assert model == "gpt-4o"
        assert key == "k"


class TestConfigIntegration:
    def test_update_config_sets_routing(self, svc):
        result = svc.update_config(
            {
                "smart_routing_enabled": True,
                "smart_routing_complexity_threshold": 250,
                "smart_routing_simple_provider": "ollama",
                "smart_routing_simple_model": "llama3",
                "smart_routing_complex_provider": "anthropic",
                "smart_routing_complex_model": "claude-3-5-haiku-latest",
            }
        )
        assert result["smart_routing_enabled"] is True
        assert result["smart_routing_complexity_threshold"] == 250
        assert result["smart_routing_simple_provider"] == "ollama"
        assert result["smart_routing_complex_model"] == "claude-3-5-haiku-latest"

    def test_threshold_clamps_minimum(self, svc):
        svc.update_config({"smart_routing_complexity_threshold": 1})
        # Минимальный clamp = 50.
        assert svc.smart_routing_complexity_threshold == 50

    def test_get_config_has_routing_fields(self, svc):
        cfg = svc.get_config()
        for k in (
            "smart_routing_enabled",
            "smart_routing_complexity_threshold",
            "smart_routing_simple_provider",
            "smart_routing_simple_model",
            "smart_routing_complex_provider",
            "smart_routing_complex_model",
        ):
            assert k in cfg
