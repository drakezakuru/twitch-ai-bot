"""v10.4.7 Wave 4.4 — Local fallback (Ollama backup для rate-limit/5xx).

Если облачный провайдер (OpenRouter/Gemini/OpenAI/Anthropic) вернул rate-limit
или 5xx — автоматически failover на Ollama (локальный).

Дизайн:
- ProviderHealthTracker хранит per-provider error counts + last_error_at.
- classify_error(exc_or_status) → 'ratelimit' | 'server_error' | 'timeout' | 'other'.
- should_fallback(provider) — True если recent failures > threshold.
- after success → reset counter.

Сам fallback (вызов Ollama) делает caller, этот модуль только решает «надо ли».
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

ErrorKind = Literal["ratelimit", "server_error", "timeout", "auth", "other", "ok"]


def classify_error_status(status: int | None) -> ErrorKind:
    if status is None:
        return "other"
    if status == 429:
        return "ratelimit"
    if status in (401, 403):
        return "auth"
    if 500 <= status < 600:
        return "server_error"
    return "other"


def classify_error_message(message: str) -> ErrorKind:
    if not message:
        return "other"
    m = message.lower()
    if "rate" in m and "limit" in m:
        return "ratelimit"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "429" in m:
        return "ratelimit"
    if "503" in m or "502" in m or "504" in m or "500" in m:
        return "server_error"
    if "unauthorized" in m or "forbidden" in m or "invalid api key" in m or "401" in m or "403" in m:
        return "auth"
    return "other"


def is_fallback_worthy(kind: ErrorKind) -> bool:
    """Эти ошибки оправдывают переход на локальный Ollama.
    'auth' и 'other' — НЕ оправдывают (там проблема не в провайдере)."""
    return kind in ("ratelimit", "server_error", "timeout")


@dataclass
class ProviderHealth:
    """Per-provider tracker (например, "openrouter", "gemini", "openai", "anthropic")."""

    provider: str
    consecutive_failures: int = 0
    last_error_at: float = 0.0
    last_error_kind: ErrorKind = "ok"
    failure_window_sec: float = 300.0  # 5 минут — окно «свежих» ошибок
    failures_threshold: int = 2  # 2 подряд → fallback включается
    cooldown_until: float = 0.0

    def record_failure(self, kind: ErrorKind, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.last_error_at = now
        self.last_error_kind = kind
        if is_fallback_worthy(kind):
            self.consecutive_failures += 1
            # эскалирующий cooldown
            if self.consecutive_failures >= self.failures_threshold:
                self.cooldown_until = now + self.failure_window_sec

    def record_success(self, now: float | None = None) -> None:
        self.consecutive_failures = 0
        self.last_error_kind = "ok"
        self.cooldown_until = 0.0

    def should_fallback(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return now < self.cooldown_until and self.consecutive_failures >= self.failures_threshold


@dataclass
class FallbackRouter:
    """Глобальный router для нескольких провайдеров."""

    providers: dict[str, ProviderHealth] = field(default_factory=dict)
    fallback_provider: str = "ollama"

    def get(self, provider: str) -> ProviderHealth:
        if provider not in self.providers:
            self.providers[provider] = ProviderHealth(provider=provider)
        return self.providers[provider]

    def record_failure(self, provider: str, kind: ErrorKind, now: float | None = None) -> None:
        self.get(provider).record_failure(kind, now)

    def record_success(self, provider: str, now: float | None = None) -> None:
        self.get(provider).record_success(now)

    def resolve(self, provider: str, now: float | None = None) -> str:
        """Возвращает provider который надо использовать СЕЙЧАС.

        Если основной в cooldown — возвращает fallback_provider.
        """
        h = self.get(provider)
        if h.should_fallback(now):
            return self.fallback_provider
        return provider

    def snapshot(self) -> dict:
        return {
            "fallback_provider": self.fallback_provider,
            "providers": {
                p: {
                    "consecutive_failures": h.consecutive_failures,
                    "last_error_kind": h.last_error_kind,
                    "last_error_at": h.last_error_at,
                    "cooldown_until": h.cooldown_until,
                    "in_cooldown": h.should_fallback(),
                }
                for p, h in self.providers.items()
            },
        }
