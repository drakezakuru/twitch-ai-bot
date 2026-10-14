"""Tests for v10.4.7 Wave 4.4 — local fallback (Ollama backup)."""

from app.local_fallback import (
    FallbackRouter,
    ProviderHealth,
    classify_error_message,
    classify_error_status,
    is_fallback_worthy,
)


def test_classify_status_codes():
    assert classify_error_status(429) == "ratelimit"
    assert classify_error_status(500) == "server_error"
    assert classify_error_status(503) == "server_error"
    assert classify_error_status(401) == "auth"
    assert classify_error_status(403) == "auth"
    assert classify_error_status(200) == "other"
    assert classify_error_status(None) == "other"


def test_classify_message_ratelimit():
    assert classify_error_message("Rate limit reached") == "ratelimit"
    assert classify_error_message("429 too many requests") == "ratelimit"


def test_classify_message_timeout():
    assert classify_error_message("Request timed out") == "timeout"
    assert classify_error_message("connection timeout") == "timeout"


def test_classify_message_server_error():
    assert classify_error_message("HTTP 503 service unavailable") == "server_error"
    assert classify_error_message("502 bad gateway") == "server_error"


def test_classify_message_auth():
    assert classify_error_message("Unauthorized 401") == "auth"
    assert classify_error_message("invalid api key") == "auth"


def test_is_fallback_worthy():
    assert is_fallback_worthy("ratelimit") is True
    assert is_fallback_worthy("server_error") is True
    assert is_fallback_worthy("timeout") is True
    assert is_fallback_worthy("auth") is False
    assert is_fallback_worthy("other") is False


def test_health_record_success_resets():
    h = ProviderHealth(provider="openrouter")
    h.record_failure("ratelimit", now=1000.0)
    h.record_failure("ratelimit", now=1001.0)
    assert h.consecutive_failures == 2
    h.record_success()
    assert h.consecutive_failures == 0
    assert h.cooldown_until == 0.0


def test_health_failure_threshold_triggers_cooldown():
    h = ProviderHealth(provider="openrouter", failures_threshold=2, failure_window_sec=60)
    h.record_failure("ratelimit", now=1000.0)
    assert h.should_fallback(now=1010.0) is False
    h.record_failure("ratelimit", now=1010.0)
    assert h.should_fallback(now=1020.0) is True


def test_health_cooldown_expires():
    h = ProviderHealth(provider="openrouter", failures_threshold=2, failure_window_sec=30)
    h.record_failure("server_error", now=1000.0)
    h.record_failure("server_error", now=1001.0)
    assert h.should_fallback(now=1010.0) is True
    assert h.should_fallback(now=1100.0) is False


def test_auth_errors_dont_count():
    h = ProviderHealth(provider="openrouter", failures_threshold=2)
    h.record_failure("auth", now=1000.0)
    h.record_failure("auth", now=1001.0)
    assert h.consecutive_failures == 0
    assert h.should_fallback(now=1010.0) is False


def test_router_resolve_returns_fallback_in_cooldown():
    router = FallbackRouter(fallback_provider="ollama")
    router.record_failure("openrouter", "ratelimit", now=1000.0)
    router.record_failure("openrouter", "ratelimit", now=1001.0)
    assert router.resolve("openrouter", now=1010.0) == "ollama"


def test_router_returns_original_when_healthy():
    router = FallbackRouter(fallback_provider="ollama")
    assert router.resolve("openrouter") == "openrouter"


def test_router_resolve_after_recovery():
    router = FallbackRouter(fallback_provider="ollama")
    router.record_failure("openrouter", "ratelimit", now=1000.0)
    router.record_failure("openrouter", "ratelimit", now=1001.0)
    assert router.resolve("openrouter", now=1010.0) == "ollama"
    router.record_success("openrouter")
    assert router.resolve("openrouter", now=1015.0) == "openrouter"


def test_router_snapshot():
    router = FallbackRouter()
    router.record_failure("openrouter", "ratelimit", now=1000.0)
    snap = router.snapshot()
    assert "providers" in snap
    assert "openrouter" in snap["providers"]
    assert snap["providers"]["openrouter"]["consecutive_failures"] == 1
