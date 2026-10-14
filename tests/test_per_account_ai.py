"""v10.4.3: тесты per-account AI override.

Проверяем что:
1. AIService._resolve() даёт глобальный конфиг для account_id без override;
2. После set_account_override — _resolve() возвращает переопределённые поля,
   а незаданные продолжают идти из глобального конфига;
3. Пустой override (все поля '') убирает запись из cache.
"""

import pytest

from app.ai_service import AccountAIOverride, AIService


@pytest.fixture()
def ai():
    svc = AIService()
    svc.provider = "openrouter"
    svc.openrouter_chat = "global/chat-model"
    svc.openrouter_vision = "global/vision-model"
    svc.openrouter_key = "GLOBAL_KEY"
    svc.ollama_chat = "global-ollama-chat"
    svc.ollama_vision = "global-ollama-vision"
    return svc


def test_resolve_uses_global_when_no_override(ai):
    provider, chat, vision, key = ai._resolve(account_id=42)
    assert provider == "openrouter"
    assert chat == "global/chat-model"
    assert vision == "global/vision-model"
    assert key == "GLOBAL_KEY"


def test_resolve_uses_account_override(ai):
    ai.set_account_override(
        7,
        AccountAIOverride(
            provider="openrouter",
            chat_model="acc7/chat-model",
            vision_model="acc7/vision-model",
            openrouter_key="ACC7_KEY",
        ),
    )
    provider, chat, vision, key = ai._resolve(account_id=7)
    assert chat == "acc7/chat-model"
    assert vision == "acc7/vision-model"
    assert key == "ACC7_KEY"

    # Другой аккаунт без override продолжает использовать глобальный.
    provider2, chat2, vision2, key2 = ai._resolve(account_id=99)
    assert chat2 == "global/chat-model"
    assert key2 == "GLOBAL_KEY"


def test_partial_override_falls_back_to_global(ai):
    """Если задан только chat_model — vision продолжает идти из глобала."""
    ai.set_account_override(
        7, AccountAIOverride(chat_model="acc7/only-chat"),
    )
    _, chat, vision, key = ai._resolve(account_id=7)
    assert chat == "acc7/only-chat"
    assert vision == "global/vision-model"
    assert key == "GLOBAL_KEY"


def test_provider_override_switches_to_ollama(ai):
    """provider=ollama в override → берётся ollama_* поля из глобала."""
    ai.set_account_override(7, AccountAIOverride(provider="ollama"))
    provider, chat, vision, _ = ai._resolve(account_id=7)
    assert provider == "ollama"
    assert chat == "global-ollama-chat"
    assert vision == "global-ollama-vision"


def test_empty_override_clears_cache(ai):
    ai.set_account_override(7, AccountAIOverride(chat_model="acc7/x"))
    assert ai.get_account_override(7) is not None
    ai.set_account_override(7, AccountAIOverride())  # все поля пустые
    assert ai.get_account_override(7) is None


def test_none_override_clears_cache(ai):
    ai.set_account_override(7, AccountAIOverride(chat_model="acc7/x"))
    ai.set_account_override(7, None)
    assert ai.get_account_override(7) is None


def test_account_id_zero_is_noop(ai):
    """account_id=0 — глобальные вызовы, override на 0 не должен сохраняться."""
    ai.set_account_override(0, AccountAIOverride(chat_model="should-be-ignored"))
    assert ai.get_account_override(0) is None
    _, chat, _, _ = ai._resolve(account_id=0)
    assert chat == "global/chat-model"
