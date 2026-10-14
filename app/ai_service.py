"""AI-сервис: анализ изображений и генерация текста.

Поддерживаемые провайдеры (v10.4.3):
  * ``openrouter`` — OpenAI-совместимый gateway, бывают free-tier модели;
  * ``ollama``     — локальный inference (LLaVa, llama3, qwen-vl, и т.д.);
  * ``gemini``     — Google Generative Language API напрямую (gemini-2.0-flash, etc.);
  * ``openai``     — OpenAI Chat Completions API (gpt-4o-mini, gpt-4o);
  * ``anthropic``  — Anthropic Messages API (claude-3-5-haiku, claude-3-5-sonnet).
«Primary» провайдер настраивается глобально в .env (AI_PROVIDER) или
per-account через ``ai_provider_override`` (таблица ``accounts``).
"""

import base64
import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from PIL import Image

from app.local_fallback import FallbackRouter

logger = logging.getLogger(__name__)

_ai_log_callback: Any = None


@dataclass
class AccountAIOverride:
    """v10.4.3: per-account override AI-настроек.

    Если значение не пустое — заменяет соответствующее поле глобального
    конфига при запросах от этого аккаунта. Позволяет разнести нагрузку:
    каждый бот может иметь свой ключ + свою модель, чтобы они
    не толкались в один rate-limit / одну квоту.

    ``api_key`` — универсальный оверрайд ключа. Какой провайдер сейчас выбран
    (глобальный или через ``provider``) — туда этот ключ и уйдёт.
    Поле ``openrouter_key`` оставлено для backward-compat (было в ранней версии v10.4.3).
    """
    provider: str = ""
    chat_model: str = ""
    vision_model: str = ""
    openrouter_key: str = ""  # backward-compat (ранняя v10.4.3)
    api_key: str = ""          # универсальный оверрайд ключа провайдера
    # v12: кастомний провайдер
    custom_base_url: str = ""
    custom_api_key: str = ""
    # Q15c (E4): резерв «локальная Ollama» — осознанный opt-in конкретного бота
    local_fallback: bool = False
    # Q15d (E5): smart-routing чат-моделей per-бот. Пустой dict = наследовать
    # глобальные ai_smart_routing_* (legacy до переноса); непустой — свой конфиг:
    # {enabled, threshold, simple_provider, simple_model, complex_provider, complex_model}
    smart_routing: dict = field(default_factory=dict)

    def effective_key(self) -> str:
        return self.api_key or self.openrouter_key or self.custom_api_key


def set_ai_log_callback(callback: Any) -> None:
    global _ai_log_callback
    _ai_log_callback = callback


async def ai_log(event: str, detail: str, account_id: int = 0, channel: str = "") -> None:
    logger.info("[AI:%s] %s", event, detail)
    if event == "fallback" and account_id:
        # OPS_PLAN §3: fallback пишется и в bot_logs — событие видно в панели
        # (вкладка логов бота) и сохраняется после рестарта, а не только в WS.
        try:
            from app.bot_logs import log_per_bot
            await log_per_bot(account_id, channel, "fallback", detail, level="warning")
        except Exception:
            pass
    if _ai_log_callback:
        try:
            await _ai_log_callback(event, detail, account_id, channel)
        except Exception:
            pass


def _extract_openrouter_text(data: dict) -> str:
    """v10.4.2 hotfix: достаём текст из ответа OpenRouter, толерантно к reasoning-моделям.

    У моделей с reasoning (z-ai/glm-4.5-air:free, ...:reasoning, ...) поле
    ``message.content`` приходит ``null`` — текст лежит либо в
    ``message.reasoning_details[].text``, либо в ``message.reasoning``.
    Старая версия делала ``.strip()`` на ``None`` и падала с
    ``'NoneType' object has no attribute 'strip'``.
    """
    try:
        msg = (data.get("choices") or [{}])[0].get("message") or {}
    except (AttributeError, IndexError, TypeError):
        return ""
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        # Multimodal content array — собираем текстовые сегменты.
        parts: list[str] = []
        for seg in content:
            if isinstance(seg, dict):
                t = seg.get("text") or seg.get("content")
                if isinstance(t, str):
                    parts.append(t)
        joined = "".join(parts).strip()
        if joined:
            return joined
    # Reasoning-модели: текст может быть в reasoning_details[i].text.
    rd = msg.get("reasoning_details")
    if isinstance(rd, list):
        parts = []
        for seg in rd:
            if isinstance(seg, dict):
                t = seg.get("text") or seg.get("summary") or seg.get("content")
                if isinstance(t, str):
                    parts.append(t)
        joined = "".join(parts).strip()
        if joined:
            return joined
    # Старое поле ``reasoning`` (строкой).
    reasoning = msg.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning.strip()
    return ""


class AIService:

    SUPPORTED_PROVIDERS = ("openrouter", "ollama", "gemini", "openai", "anthropic", "custom")

    def __init__(self) -> None:
        self.provider = os.getenv("AI_PROVIDER", "openrouter").lower()
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_vision = os.getenv("OPENROUTER_VISION_MODEL", "google/gemini-2.0-flash-exp:free")
        self.openrouter_chat = os.getenv("OPENROUTER_CHAT_MODEL", "google/gemini-2.0-flash-exp:free")
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self.ollama_vision = os.getenv("OLLAMA_VISION_MODEL", "llava")
        self.ollama_chat = os.getenv("OLLAMA_CHAT_MODEL", "llama3")
        # v10.4.3: Google Gemini напрямую через generativelanguage.googleapis.com.
        # Бесплатный tier работает без OpenRouter. И chat, и vision в одной multimodal-модели.
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_chat = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.0-flash")
        self.gemini_vision = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash")
        # v10.4.3: OpenAI Chat Completions API.
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_chat = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        self.openai_vision = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
        self.openai_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
        # v10.4.3: Anthropic Messages API.
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.anthropic_chat = os.getenv("ANTHROPIC_CHAT_MODEL", "claude-3-5-haiku-latest")
        self.anthropic_vision = os.getenv("ANTHROPIC_VISION_MODEL", "claude-3-5-sonnet-latest")
        self.custom_base_url = os.getenv("CUSTOM_AI_BASE_URL", "").rstrip("/")
        self.custom_api_key = os.getenv("CUSTOM_AI_API_KEY", "")
        self.custom_model = os.getenv("CUSTOM_AI_MODEL", "")
        # Q15c (E4): локальный fallback на Ollama выключен по умолчанию —
        # включается вручную per-бот («резерв: локальная Ollama»); переменная
        # окружения остаётся глобальным аварийным рубильником.
        self.local_fallback_enabled = os.getenv("LOCAL_FALLBACK_ENABLED", "0").lower() in ("1", "true", "yes")
        self.offline_mode = os.getenv("OFFLINE_MODE", "0").lower() in ("1", "true", "yes")
        self.fallback_router = FallbackRouter(fallback_provider="ollama")
        # BUG-4: circuit breaker локального fallback (Ollama). Мёртвый Ollama
        # не долбится каждым AI-вызовом: после FALLBACK_FAIL_THRESHOLD неудач
        # подряд вызовы локального провайдера пропускаются на FALLBACK_FAIL_COOLDOWN
        # секунд (в логе один warning вместо потока connect_tcp.failed).
        self.FALLBACK_FAIL_THRESHOLD = 3
        self.FALLBACK_FAIL_COOLDOWN = 300.0
        self._fallback_fail_streak = 0
        self._fallback_fail_until = 0.0
        # §25.4: именованные кастомные провайдеры (custom_providers из БД).
        # Кэш в памяти: {name: {base_url, api_key, models: [str]}} — обновляется
        # set_custom_providers() при старте и после CRUD-роутов.
        self._custom_providers: dict[str, dict] = {}
        self.global_vision_override = ""
        # Последняя ошибка vision-провайдера: _openai_vision возвращает "" (рантайм
        # рассчитывает на пустую строку), а /api/ai/test-vision показывает причину.
        self.last_vision_error = ""
        self._client = httpx.AsyncClient(timeout=180.0)
        # v10.4.3: per-account override. Заполняется server.py при загрузке
        # аккаунтов из БД и через /api/accounts/{id}/ai-override.
        self._account_overrides: dict[int, AccountAIOverride] = {}
        # v10.4.4: smart-routing — простые промпты на дешёвый провайдер,
        # сложные на премиум. По дефолту выключено.
        self.smart_routing_enabled = False
        # Порог длины (chars) после которого считаем промпт «сложным».
        self.smart_routing_complexity_threshold = 600
        # Пустые поля = «как есть» (без переключения).
        self.smart_routing_simple_provider = ""
        self.smart_routing_simple_model = ""
        self.smart_routing_complex_provider = ""
        self.smart_routing_complex_model = ""

    # ---------- v10.4.3: per-account override ----------

    def set_account_override(self, account_id: int, override: AccountAIOverride | None) -> None:
        """Установить пер-account override. None или пустые поля — удалить из cache."""
        if account_id <= 0:
            return
        if override is None or not (
            override.provider or override.chat_model or override.vision_model
            or override.openrouter_key or override.api_key
            or override.custom_base_url or override.custom_api_key
            or override.local_fallback or override.smart_routing
        ):
            self._account_overrides.pop(account_id, None)
            return
        self._account_overrides[account_id] = override

    def get_account_override(self, account_id: int) -> AccountAIOverride | None:
        return self._account_overrides.get(account_id)

    def _local_fallback_for(self, account_id: int) -> bool:
        """Q15c (E4): эффективный локальный fallback для бота.

        По умолчанию выключен; включается вручную per-бот (флаг
        ``ai_local_fallback`` в ai-override). Переменная окружения
        ``LOCAL_FALLBACK_ENABLED`` остаётся глобальным аварийным рубильником
        (для ботов без явного выбора). Circuit breaker (BUG-4) работает как
        раньше и от флага бота не зависит.
        """
        ov = self._account_overrides.get(account_id)
        if ov is not None and ov.local_fallback:
            return True
        return self.local_fallback_enabled

    def _smart_routing_for(self, account_id: int) -> dict | None:
        """Q15d (E5): smart-routing конфиг бота или None (наследовать глобальный)."""
        ov = self._account_overrides.get(account_id)
        if ov is not None and ov.smart_routing:
            return ov.smart_routing
        return None

    # ---------- §25.4: named custom providers ----------

    def set_custom_providers(self, items: list[dict]) -> None:
        """Обновить кэш именованных провайдеров. items — строки из custom_providers."""
        cache: dict[str, dict] = {}
        for item in items or []:
            name = str(item.get("name") or "").strip()
            if not name or not item.get("enabled", 1):
                continue
            models = item.get("models") or []
            if isinstance(models, str):
                try:
                    models = json.loads(models)
                except (TypeError, ValueError):
                    models = [m.strip() for m in models.split(",") if m.strip()]
            vision_models = item.get("vision_models") or []
            if isinstance(vision_models, str):
                try:
                    vision_models = json.loads(vision_models)
                except (TypeError, ValueError):
                    vision_models = [m.strip() for m in vision_models.split(",") if m.strip()]
            cache[name] = {
                "base_url": str(item.get("base_url") or "").rstrip("/"),
                "api_key": str(item.get("api_key") or ""),
                "models": [str(m).strip() for m in models if str(m).strip()],
                "vision_models": [str(m).strip() for m in vision_models if str(m).strip()],
            }
        self._custom_providers = cache

    def custom_provider_names(self) -> list[str]:
        return sorted(self._custom_providers.keys())

    def get_custom_provider(self, name: str) -> dict | None:
        wanted = (name or "").strip()
        direct = self._custom_providers.get(wanted)
        if direct is not None:
            return direct
        wanted_lower = wanted.lower()
        return next(
            (cfg for saved_name, cfg in self._custom_providers.items()
             if saved_name.lower() == wanted_lower),
            None,
        )

    def _provider_defaults(self, provider: str) -> tuple[str, str, str]:
        """Возвращает (chat_model, vision_model, api_key) для глобальных настроек провайдера."""
        p = (provider or "").lower()
        if p == "openrouter":
            return self.openrouter_chat, self.openrouter_vision, self.openrouter_key
        if p == "ollama":
            return self.ollama_chat, self.ollama_vision, ""
        if p == "gemini":
            return self.gemini_chat, self.gemini_vision, self.gemini_key
        if p == "openai":
            return self.openai_chat, self.openai_vision, self.openai_key
        if p == "anthropic":
            return self.anthropic_chat, self.anthropic_vision, self.anthropic_key
        if p == "custom":
            return self.custom_model, self.custom_model, self.custom_api_key
        if p.startswith("custom:"):
            cfg = self.get_custom_provider(p.split(":", 1)[1])
            if cfg:
                chat = cfg["models"][0] if cfg["models"] else ""
                vision = cfg["vision_models"][0] if cfg["vision_models"] else ""
                return chat, vision, cfg["api_key"]
            return "", "", ""
        # Для неизвестных провайдеров fallback на OpenRouter.
        return self.openrouter_chat, self.openrouter_vision, self.openrouter_key

    def _resolve(self, account_id: int) -> tuple[str, str, str, str]:
        """Вычислить эффективные (provider, chat_model, vision_model, api_key)
        для конкретного аккаунта.

        Порядок: per-account override -> provider-specific global -> openrouter fallback.
        ``api_key`` — универсальный ключ для выбранного provider (OpenRouter/Gemini/OpenAI/Anthropic),
        для Ollama пустой (локальный инференс не требует ключа).
        """
        ov = self._account_overrides.get(account_id) if account_id else None
        provider = (ov.provider if ov and ov.provider else self.provider).lower() or "openrouter"
        default_chat, default_vision, default_key = self._provider_defaults(provider)
        chat_model = ov.chat_model if ov and ov.chat_model else default_chat
        vision_model = ov.vision_model if ov and ov.vision_model else (self.global_vision_override or default_vision)
        # Оверрайд ключа — выбираем первый непустой: api_key (универсальный),
        # openrouter_key (legacy v10.4.3-early), default по провайдеру.
        api_key = (ov.effective_key() if ov else "") or default_key
        return provider, chat_model, vision_model, api_key

    # ---------- v10.4.4: smart-routing ----------

    def _classify_complexity(self, prompt: str, system: str = "", threshold: int | None = None) -> str:
        """Простой классификатор: simple / complex.

        complex если: суммарный prompt+system длиннее threshold ИЛИ если в
        промпте явно много контекста (несколько блоков `[...]`).
        ``threshold`` — per-бот порог (Q15d); None = глобальный.
        """
        n = len(prompt or "") + len(system or "")
        if n >= (threshold if threshold is not None else self.smart_routing_complexity_threshold):
            return "complex"
        # Считаем разделители "контекстных блоков" в system. Их много → значит RAG/vision/etc.
        block_markers = (system or "").count("[")
        if block_markers >= 3:
            return "complex"
        return "simple"

    def _apply_smart_routing(
        self, provider: str, chat_model: str, api_key: str, complexity: str,
        cfg: dict | None = None,
    ) -> tuple[str, str, str]:
        """Если smart_routing включён и для класса заданы простой/сложный
        провайдер+модель — переопределяем. Иначе возвращаем что было.

        ``cfg`` — per-бот конфиг (Q15d); None = глобальные поля self.*.
        """
        cfg = cfg or {}
        if not cfg.get("enabled", self.smart_routing_enabled):
            return provider, chat_model, api_key
        if complexity == "simple":
            new_p = (cfg.get("simple_provider", self.smart_routing_simple_provider) or "").strip().lower()
            new_m = (cfg.get("simple_model", self.smart_routing_simple_model) or "").strip()
        elif complexity == "complex":
            new_p = (cfg.get("complex_provider", self.smart_routing_complex_provider) or "").strip().lower()
            new_m = (cfg.get("complex_model", self.smart_routing_complex_model) or "").strip()
        else:
            new_p, new_m = "", ""
        # custom:<имя> разрешён (Q15d): ключ/модель тянутся из кэша named-провайдера
        if new_p and (new_p in self.SUPPORTED_PROVIDERS or new_p.startswith("custom:")):
            _c, _v, new_key = self._provider_defaults(new_p)
            provider = new_p
            api_key = new_key
            if new_m:
                chat_model = new_m
        elif new_m:
            chat_model = new_m
        return provider, chat_model, api_key

    def get_config(self) -> dict:
        return {
            "provider": self.provider,
            "openrouter_key": self.openrouter_key,
            "openrouter_vision": self.openrouter_vision,
            "openrouter_chat": self.openrouter_chat,
            "ollama_host": self.ollama_host,
            "ollama_vision": self.ollama_vision,
            "ollama_chat": self.ollama_chat,
            # v10.4.3:
            "gemini_key": self.gemini_key,
            "gemini_chat": self.gemini_chat,
            "gemini_vision": self.gemini_vision,
            "openai_key": self.openai_key,
            "openai_chat": self.openai_chat,
            "openai_vision": self.openai_vision,
            "openai_base": self.openai_base,
            "anthropic_key": self.anthropic_key,
            "anthropic_chat": self.anthropic_chat,
            "anthropic_vision": self.anthropic_vision,
            "custom_ai_base_url": self.custom_base_url,
            "custom_ai_api_key": self.custom_api_key,
            "custom_ai_model": self.custom_model,
            "global_vision_override": self.global_vision_override,
            "offline_mode": self.offline_mode,
            # v10.4.4: smart-routing.
            "smart_routing_enabled": self.smart_routing_enabled,
            "smart_routing_complexity_threshold": self.smart_routing_complexity_threshold,
            "smart_routing_simple_provider": self.smart_routing_simple_provider,
            "smart_routing_simple_model": self.smart_routing_simple_model,
            "smart_routing_complex_provider": self.smart_routing_complex_provider,
            "smart_routing_complex_model": self.smart_routing_complex_model,
        }

    async def ollama_status(self) -> dict:
        """Probe Ollama readiness without loading or running a model."""
        try:
            response = await self._client.get(f"{self.ollama_host}/api/version", timeout=2.0)
            response.raise_for_status()
            return {"state": "ready", "version": str(response.json().get("version") or "")}
        except Exception:
            return {"state": "paused", "version": ""}

    # ---------- BUG-4: circuit breaker локального fallback ----------

    def _fallback_healthy(self) -> bool:
        """True пока circuit breaker не открыт (пауза после серии неудач)."""
        return time.monotonic() >= self._fallback_fail_until

    def _note_fallback_result(self, ok: bool) -> None:
        """Учитывает результат вызова локального провайдера (Ollama)."""
        if ok:
            self._fallback_fail_streak = 0
            self._fallback_fail_until = 0.0
            return
        self._fallback_fail_streak += 1
        if self._fallback_fail_streak >= self.FALLBACK_FAIL_THRESHOLD:
            self._fallback_fail_streak = 0
            self._fallback_fail_until = time.monotonic() + self.FALLBACK_FAIL_COOLDOWN
            logger.warning(
                "local_fallback: Ollama недоступен (%d неудач подряд) — не вызываю его %.0f с",
                self.FALLBACK_FAIL_THRESHOLD, self.FALLBACK_FAIL_COOLDOWN,
            )

    def update_config(self, data: dict) -> dict:
        if "provider" in data:
            p = (data["provider"] or "").strip().lower()
            if p in self.SUPPORTED_PROVIDERS or p.startswith("custom:"):
                self.provider = p
        if "openrouter_key" in data:
            self.openrouter_key = data["openrouter_key"]
        if "openrouter_vision" in data:
            self.openrouter_vision = data["openrouter_vision"]
        if "openrouter_chat" in data:
            self.openrouter_chat = data["openrouter_chat"]
        if "ollama_host" in data:
            self.ollama_host = data["ollama_host"].rstrip("/")
        if "ollama_vision" in data:
            self.ollama_vision = data["ollama_vision"]
        if "ollama_chat" in data:
            self.ollama_chat = data["ollama_chat"]
        # v10.4.3:
        if "gemini_key" in data:
            self.gemini_key = data["gemini_key"]
        if "gemini_chat" in data:
            self.gemini_chat = data["gemini_chat"]
        if "gemini_vision" in data:
            self.gemini_vision = data["gemini_vision"]
        if "openai_key" in data:
            self.openai_key = data["openai_key"]
        if "openai_chat" in data:
            self.openai_chat = data["openai_chat"]
        if "openai_vision" in data:
            self.openai_vision = data["openai_vision"]
        if "openai_base" in data:
            self.openai_base = (data["openai_base"] or "").rstrip("/") or "https://api.openai.com/v1"
        if "anthropic_key" in data:
            self.anthropic_key = data["anthropic_key"]
        if "anthropic_chat" in data:
            self.anthropic_chat = data["anthropic_chat"]
        if "anthropic_vision" in data:
            self.anthropic_vision = data["anthropic_vision"]
        if "custom_ai_base_url" in data:
            self.custom_base_url = (data["custom_ai_base_url"] or "").rstrip("/")
        if "custom_ai_api_key" in data:
            self.custom_api_key = data["custom_ai_api_key"]
        if "custom_ai_model" in data:
            self.custom_model = data["custom_ai_model"]
        if "global_vision_override" in data:
            self.global_vision_override = str(data["global_vision_override"] or "").strip()
        if "offline_mode" in data:
            self.offline_mode = bool(data["offline_mode"])
        # v10.4.4: smart-routing.
        if "smart_routing_enabled" in data:
            self.smart_routing_enabled = bool(data["smart_routing_enabled"])
        if "smart_routing_complexity_threshold" in data:
            try:
                self.smart_routing_complexity_threshold = max(50, int(data["smart_routing_complexity_threshold"]))
            except (TypeError, ValueError):
                pass
        if "smart_routing_simple_provider" in data:
            self.smart_routing_simple_provider = str(data["smart_routing_simple_provider"] or "")
        if "smart_routing_simple_model" in data:
            self.smart_routing_simple_model = str(data["smart_routing_simple_model"] or "")
        if "smart_routing_complex_provider" in data:
            self.smart_routing_complex_provider = str(data["smart_routing_complex_provider"] or "")
        if "smart_routing_complex_model" in data:
            self.smart_routing_complex_model = str(data["smart_routing_complex_model"] or "")
        logger.info("AI config updated: provider=%s", self.provider)
        return self.get_config()

    @staticmethod
    def _image_to_base64(image: Image.Image) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    async def analyze_image(self, image: Image.Image, prompt: str, account_id: int = 0, channel: str = "") -> str:
        provider, _chat, vision_model, api_key = self._resolve(account_id)
        requested_provider = provider
        # Q15c (E4): fallback per-бот, по умолчанию выключен
        local_fallback = self._local_fallback_for(account_id)
        if self.offline_mode:
            provider, vision_model, api_key = "ollama", self.ollama_vision, ""
        if local_fallback and self._fallback_healthy():
            provider = self.fallback_router.resolve(provider)
            if provider == "ollama" and requested_provider != provider:
                vision_model = self.ollama_vision
        await ai_log("vision_start", f"Анализирую кадр... (модель: {vision_model})", account_id, channel)
        await ai_log("vision_prompt", f"Промпт: {prompt}", account_id, channel)

        img_b64 = self._image_to_base64(image)

        if provider == "openrouter":
            result = await self._openrouter_vision(img_b64, prompt, model=vision_model, api_key=api_key)
        elif provider == "gemini":
            result = await self._gemini_vision(img_b64, prompt, model=vision_model, api_key=api_key)
        elif provider == "openai":
            result = await self._openai_vision(img_b64, prompt, model=vision_model, api_key=api_key)
        elif provider == "anthropic":
            result = await self._anthropic_vision(img_b64, prompt, model=vision_model, api_key=api_key)
        elif provider == "custom":
            result = await self._openai_vision(
                img_b64, prompt, model=vision_model, api_key=api_key,
                base_url=(self._account_overrides.get(account_id).custom_base_url
                          if self._account_overrides.get(account_id)
                          and self._account_overrides[account_id].custom_base_url
                          else self.custom_base_url),
            )
        elif provider.startswith("custom:"):
            cfg = self.get_custom_provider(provider.split(":", 1)[1]) or {}
            result = await self._openai_vision(
                img_b64, prompt, model=vision_model,
                api_key=cfg.get("api_key") or api_key,
                base_url=cfg.get("base_url") or "",
            )
        else:
            # BUG-4: при открытом breaker'е локальный провайдер не вызываем
            # (пустой результат вместо потока connect_tcp.failed).
            if not self._fallback_healthy():
                result = ""
            else:
                result = await self._ollama_vision(img_b64, prompt, model=vision_model)
                self._note_fallback_result(bool(result))

        # Vision providers can fail without raising (for example on a 5xx
        # response). Keep the stream observer useful by retrying locally.
        if not result and local_fallback and self._fallback_healthy() and provider not in ("ollama", "custom"):
            fallback_model = self.ollama_vision
            fallback = await self._ollama_vision(img_b64, prompt, model=fallback_model)
            self._note_fallback_result(bool(fallback))
            if fallback:
                result = fallback
                await ai_log("fallback", f"Локальный vision fallback: ollama/{fallback_model}", account_id, channel)

        if result:
            self.fallback_router.record_success(requested_provider)
        elif requested_provider != "ollama":
            self.fallback_router.record_failure(requested_provider, "server_error")

        if result:
            await ai_log("vision_result", f"Вижу: {result}", account_id, channel)
        else:
            await ai_log("vision_error", "Не удалось проанализировать кадр", account_id, channel)
        return result

    async def generate_text(
        self,
        prompt: str,
        system: str = "",
        account_id: int = 0,
        channel: str = "",
        temperature: float | None = None,
    ) -> str:
        """Генерация текста.

        ``temperature`` — опциональная "креативность":
          - 0.2..0.4 — чёткие фактологичные ответы, держится темы (рекомендуется для чата);
          - 0.6..0.8 — более разнообразные/творческие;
          - None — дефолт модели.
        """
        provider, chat_model, _vision, api_key = self._resolve(account_id)
        requested_provider = provider
        # Q15c (E4): fallback per-бот, по умолчанию выключен
        local_fallback = self._local_fallback_for(account_id)
        if self.offline_mode:
            provider, chat_model, api_key = "ollama", self.ollama_chat, ""
        # v10.4.4: smart-routing — переопределяем провайдер/модель в зависимости
        # от сложности промпта (простой → дешёвый/локальный, сложный → премиум).
        # Q15d (E5): у бота свой конфиг (ai-override) — он сильнее глобального.
        sr_cfg = self._smart_routing_for(account_id)
        if sr_cfg or self.smart_routing_enabled:
            complexity = self._classify_complexity(
                prompt, system, threshold=sr_cfg.get("threshold") if sr_cfg else None,
            )
            new_provider, new_model, new_key = self._apply_smart_routing(provider, chat_model, api_key, complexity, cfg=sr_cfg)
            if new_provider != provider or new_model != chat_model:
                await ai_log(
                    "smart_route",
                    f"{complexity} → {new_provider}/{new_model} (было {provider}/{chat_model})",
                    account_id,
                    channel,
                )
                provider, chat_model, api_key = new_provider, new_model, new_key
        if local_fallback and self._fallback_healthy():
            resolved_provider = self.fallback_router.resolve(provider)
            if resolved_provider != provider:
                provider = resolved_provider
                chat_model = self.ollama_chat
        await ai_log("think_start", f"Думаю... (модель: {chat_model})", account_id, channel)
        if system:
            await ai_log("think_system", f"Системный промпт: {system[:200]}", account_id, channel)
        await ai_log("think_prompt", f"Запрос: {prompt[:300]}", account_id, channel)

        if provider == "openrouter":
            result = await self._openrouter_chat(prompt, system, temperature=temperature, model=chat_model, api_key=api_key)
        elif provider == "gemini":
            result = await self._gemini_chat(prompt, system, temperature=temperature, model=chat_model, api_key=api_key)
        elif provider == "openai":
            result = await self._openai_chat(prompt, system, temperature=temperature, model=chat_model, api_key=api_key)
        elif provider == "anthropic":
            result = await self._anthropic_chat(prompt, system, temperature=temperature, model=chat_model, api_key=api_key)
        elif provider == "custom":
            result = await self._openai_chat(prompt, system, temperature=temperature, model=chat_model,
                                              api_key=api_key,
                                              base_url=(self._account_overrides.get(account_id).custom_base_url
                                                        if self._account_overrides.get(account_id)
                                                        and self._account_overrides[account_id].custom_base_url
                                                        else self.custom_base_url))
        elif provider.startswith("custom:"):
            # §25.4: именованный кастомный провайдер — base_url/ключ из кэша БД
            cfg = self.get_custom_provider(provider.split(":", 1)[1]) or {}
            result = await self._openai_chat(prompt, system, temperature=temperature, model=chat_model,
                                              api_key=cfg.get("api_key") or api_key,
                                              base_url=cfg.get("base_url") or "")
        else:
            # BUG-4: при открытом breaker'е локальный провайдер не вызываем
            # (пустой результат вместо потока connect_tcp.failed).
            if not self._fallback_healthy():
                result = ""
            else:
                result = await self._ollama_chat(prompt, system, temperature=temperature, model=chat_model)
                self._note_fallback_result(bool(result))

        # Cloud providers can fail without raising (rate limits and gateway errors
        # are commonly returned as an empty response). Retry locally when enabled.
        if not result and local_fallback and self._fallback_healthy() and provider not in ("ollama", "custom"):
            fallback_model = self.ollama_chat
            fallback = await self._ollama_chat(prompt, system, temperature=temperature, model=fallback_model)
            self._note_fallback_result(bool(fallback))
            if fallback:
                result = fallback
                await ai_log("fallback", f"Локальный fallback: ollama/{fallback_model}", account_id, channel)
        if result:
            self.fallback_router.record_success(requested_provider)
        elif requested_provider != "ollama":
            self.fallback_router.record_failure(requested_provider, "server_error")
        if result:
            await ai_log("think_result", f"Решение: {result}", account_id, channel)
        else:
            await ai_log("think_error", "Не удалось сгенерировать ответ", account_id, channel)
        return result

    async def generate_text_with(
        self,
        provider: str,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """v10.3 4C: генерация для конкретной модели/провайдера.

        Не меняет состояние сервиса (не пишет ai_log). Возвращает
        ``{ok, response, error}``.
        """
        provider = (provider or "").strip().lower()
        model = (model or "").strip()
        # named custom могут брать модель по умолчанию из конфига — не отсекаем пустую
        if not model and not provider.startswith("custom:"):
            return {"ok": False, "error": "model is empty", "response": ""}
        if provider not in self.SUPPORTED_PROVIDERS and not provider.startswith("custom:"):
            return {"ok": False, "error": f"unknown provider: {provider}", "response": ""}
        if provider == "openrouter":
            return await self._openrouter_chat_explicit(model, prompt, system, temperature, max_tokens=max_tokens)
        if provider == "ollama":
            return await self._ollama_chat_explicit(model, prompt, system, temperature, max_tokens=max_tokens)
        token_options = {"max_tokens": max_tokens} if max_tokens is not None else {}
        if provider.startswith("custom:"):
            # §25.4: проверка конкретного именованного провайдера
            cfg = self.get_custom_provider(provider.split(":", 1)[1])
            if not cfg:
                return {"ok": False, "error": f"Custom provider '{provider}' not found", "response": ""}
            model = model or (cfg["models"][0] if cfg["models"] else "")
            try:
                text = await self._openai_chat(prompt, system, model=model,
                                               api_key=cfg["api_key"], temperature=temperature,
                                               base_url=cfg["base_url"], **token_options)
                return {"ok": bool(text), "error": "" if text else "empty response", "response": text}
            except Exception as exc:
                return {"ok": False, "error": str(exc), "response": ""}
        # v10.4.3: для Gemini/OpenAI/Anthropic вызываем primary-метод и заворачиваем в dict.
        try:
            if provider == "gemini":
                text = await self._gemini_chat(prompt, system, temperature=temperature, model=model, api_key=self.gemini_key, **token_options)
            elif provider == "openai":
                text = await self._openai_chat(prompt, system, temperature=temperature, model=model, api_key=self.openai_key, **token_options)
            elif provider == "anthropic":
                text = await self._anthropic_chat(prompt, system, temperature=temperature, model=model, api_key=self.anthropic_key, **token_options)
            elif provider == "custom":
                if not self.custom_base_url:
                    return {"ok": False, "error": "custom endpoint is empty", "response": ""}
                text = await self._openai_chat(prompt, system, temperature=temperature, model=model,
                                               api_key=self.custom_api_key, base_url=self.custom_base_url, **token_options)
            else:
                return {"ok": False, "error": f"unsupported in compare: {provider}", "response": ""}
            return {"ok": bool(text), "error": "" if text else "empty response", "response": text}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "response": ""}

    async def _openrouter_chat_explicit(
        self, model: str, prompt: str, system: str, temperature: float | None, *, max_tokens: int | None = None,
    ) -> dict:
        if not self.openrouter_key:
            return {"ok": False, "error": "OPENROUTER_API_KEY not set", "response": ""}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_tokens) if max_tokens is not None else 300,
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        try:
            resp = await self._client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Twitch AI Bot",
                },
                json=payload,
            )
            data = resp.json()
            if resp.status_code >= 400 or "error" in data:
                err = data.get("error") if isinstance(data, dict) else None
                msg = err.get("message", str(err)) if isinstance(err, dict) else (str(err) or f"HTTP {resp.status_code}")
                return {"ok": False, "error": f"OpenRouter: {msg}", "response": ""}
            text = _extract_openrouter_text(data)
            return {"ok": True, "error": "", "response": text}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "response": ""}

    async def _ollama_chat_explicit(
        self, model: str, prompt: str, system: str, temperature: float | None, *, max_tokens: int | None = None,
    ) -> dict:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload: dict[str, Any] = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        options: dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = float(temperature)
        if max_tokens is not None:
            options["num_predict"] = int(max_tokens)
        if options:
            payload["options"] = options
        try:
            resp = await self._client.post(
                f"{self.ollama_host}/api/generate", json=payload,
            )
            if resp.status_code >= 400:
                return {
                    "ok": False,
                    "error": f"Ollama HTTP {resp.status_code}",
                    "response": "",
                }
            data = resp.json()
            return {"ok": True, "error": "", "response": (data.get("response") or "").strip()}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "response": ""}

    async def _openrouter_vision(self, img_b64: str, prompt: str, model: str | None = None, api_key: str | None = None) -> str:
        model = model or self.openrouter_vision
        api_key = api_key or self.openrouter_key
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }],
            "max_tokens": 300,
        }
        try:
            resp = await self._client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Twitch AI Bot",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.error("OpenRouter vision error: %s", data["error"])
                return ""
            return _extract_openrouter_text(data)
        except Exception as exc:
            logger.error("OpenRouter vision error: %s", exc)
            return ""

    async def _openrouter_chat(
        self, prompt: str, system: str, temperature: float | None = None,
        model: str | None = None, api_key: str | None = None,
    ) -> str:
        model = model or self.openrouter_chat
        api_key = api_key or self.openrouter_key
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 300,
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        try:
            resp = await self._client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Twitch AI Bot",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.error("OpenRouter API error: %s", data["error"])
                return ""
            return _extract_openrouter_text(data)
        except Exception as exc:
            logger.error("OpenRouter chat error: %s", exc)
            return ""

    # ============== v10.4.3: Google Gemini (generativelanguage.googleapis.com) ==============

    @staticmethod
    def _gemini_combine_text(system: str, prompt: str) -> str:
        return f"{system}\n\n{prompt}" if system else prompt

    @staticmethod
    def _extract_gemini_text(data: dict) -> str:
        try:
            candidates = data.get("candidates") or []
            if not candidates:
                return ""
            parts = (candidates[0].get("content") or {}).get("parts") or []
            texts = [p.get("text") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
            return "".join(texts).strip()
        except Exception:
            return ""

    async def _gemini_chat(
        self, prompt: str, system: str, temperature: float | None = None,
        model: str | None = None, api_key: str | None = None, max_tokens: int | None = None,
    ) -> str:
        model = model or self.gemini_chat
        api_key = api_key or self.gemini_key
        if not api_key:
            logger.error("Gemini chat: GEMINI_API_KEY not set")
            return ""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": self._gemini_combine_text(system, prompt)}]}],
            "generationConfig": {"maxOutputTokens": int(max_tokens) if max_tokens is not None else 300},
        }
        if temperature is not None:
            payload["generationConfig"]["temperature"] = float(temperature)
        try:
            resp = await self._client.post(url, params={"key": api_key}, json=payload)
            if resp.status_code >= 400:
                logger.error("Gemini chat HTTP %s: %s", resp.status_code, resp.text[:300])
                return ""
            return self._extract_gemini_text(resp.json())
        except Exception as exc:
            logger.error("Gemini chat error: %s", exc)
            return ""

    async def _gemini_vision(
        self, img_b64: str, prompt: str,
        model: str | None = None, api_key: str | None = None,
    ) -> str:
        model = model or self.gemini_vision
        api_key = api_key or self.gemini_key
        if not api_key:
            logger.error("Gemini vision: GEMINI_API_KEY not set")
            return ""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
                ],
            }],
            "generationConfig": {"maxOutputTokens": 300},
        }
        try:
            resp = await self._client.post(url, params={"key": api_key}, json=payload)
            if resp.status_code >= 400:
                logger.error("Gemini vision HTTP %s: %s", resp.status_code, resp.text[:300])
                return ""
            return self._extract_gemini_text(resp.json())
        except Exception as exc:
            logger.error("Gemini vision error: %s", exc)
            return ""

    # ============== v10.4.3: OpenAI Chat Completions ==============

    @staticmethod
    def _extract_openai_text(data: dict) -> str:
        try:
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                # gpt-4o multimodal — собираем text-сегменты
                parts = [seg.get("text", "") for seg in content if isinstance(seg, dict)]
                return "".join(parts).strip()
        except Exception:
            pass
        return ""

    async def _openai_chat(
        self, prompt: str, system: str, temperature: float | None = None,
        model: str | None = None, api_key: str | None = None, base_url: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        model = model or self.openai_chat
        api_key = self.openai_key if api_key is None else api_key
        if not api_key and not base_url:
            logger.error("OpenAI chat: OPENAI_API_KEY not set")
            return ""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": int(max_tokens) if max_tokens is not None else 300}
        if temperature is not None:
            payload["temperature"] = float(temperature)
        try:
            resp = await self._client.post(
                f"{(base_url or self.openai_base).rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("OpenAI chat HTTP %s: %s", resp.status_code, resp.text[:300])
                return ""
            return self._extract_openai_text(resp.json())
        except Exception as exc:
            logger.error("OpenAI chat error: %s", exc)
            return ""

    async def _openai_vision(
        self, img_b64: str, prompt: str,
        model: str | None = None, api_key: str | None = None,
        base_url: str | None = None,
    ) -> str:
        model = model or self.openai_vision
        api_key = api_key or self.openai_key
        if not api_key:
            logger.error("OpenAI vision: OPENAI_API_KEY not set")
            return ""
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }],
            "max_tokens": 300,
        }
        try:
            resp = await self._client.post(
                f"{(base_url or self.openai_base).rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("OpenAI vision HTTP %s: %s", resp.status_code, resp.text[:300])
                self.last_vision_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                return ""
            self.last_vision_error = ""
            return self._extract_openai_text(resp.json())
        except Exception as exc:
            logger.error("OpenAI vision error: %s", exc)
            self.last_vision_error = str(exc)[:200]
            return ""

    # ============== v10.4.3: Anthropic Messages API ==============

    @staticmethod
    def _extract_anthropic_text(data: dict) -> str:
        try:
            blocks = data.get("content") or []
            parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
            return "".join(parts).strip()
        except Exception:
            return ""

    async def _anthropic_chat(
        self, prompt: str, system: str, temperature: float | None = None,
        model: str | None = None, api_key: str | None = None, max_tokens: int | None = None,
    ) -> str:
        model = model or self.anthropic_chat
        api_key = api_key or self.anthropic_key
        if not api_key:
            logger.error("Anthropic chat: ANTHROPIC_API_KEY not set")
            return ""
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": int(max_tokens) if max_tokens is not None else 300,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = float(temperature)
        try:
            resp = await self._client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("Anthropic chat HTTP %s: %s", resp.status_code, resp.text[:300])
                return ""
            return self._extract_anthropic_text(resp.json())
        except Exception as exc:
            logger.error("Anthropic chat error: %s", exc)
            return ""

    async def _anthropic_vision(
        self, img_b64: str, prompt: str,
        model: str | None = None, api_key: str | None = None,
    ) -> str:
        model = model or self.anthropic_vision
        api_key = api_key or self.anthropic_key
        if not api_key:
            logger.error("Anthropic vision: ANTHROPIC_API_KEY not set")
            return ""
        payload = {
            "model": model,
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        try:
            resp = await self._client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("Anthropic vision HTTP %s: %s", resp.status_code, resp.text[:300])
                return ""
            return self._extract_anthropic_text(resp.json())
        except Exception as exc:
            logger.error("Anthropic vision error: %s", exc)
            return ""

    async def _ollama_vision(self, img_b64: str, prompt: str, model: str | None = None) -> str:
        model = model or self.ollama_vision
        payload = {"model": model, "prompt": prompt, "images": [img_b64], "stream": False}
        try:
            resp = await self._client.post(f"{self.ollama_host}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as exc:
            logger.error("Ollama vision error: %s", exc)
            return ""

    async def _ollama_chat(
        self, prompt: str, system: str, temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        model = model or self.ollama_chat
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload: dict[str, Any] = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        if temperature is not None:
            payload["options"] = {"temperature": float(temperature)}
        try:
            resp = await self._client.post(f"{self.ollama_host}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as exc:
            logger.error("Ollama chat error: %s", exc)
            return ""

    async def test_connection(self, provider: str | None = None) -> dict:
        """Простой ping выбранного provider'а: одна короткая chat-генерация."""
        import time as _time
        t0 = _time.perf_counter()

        def _ok(resp_text: str, model_name: str) -> dict:
            return {
                "ok": True,
                "response": resp_text,
                "model": model_name,
                "latency_ms": max(1, round((_time.perf_counter() - t0) * 1000)),
            }

        provider = (provider or self.provider).strip().lower()
        if provider == "openrouter":
            if not self.openrouter_key:
                return {"ok": False, "error": "API key not set. Enter your key in Settings."}
            try:
                resp = await self._client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_key}",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-Title": "Twitch AI Bot",
                    },
                    json={"model": self.openrouter_chat, "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 10},
                )
                data = resp.json()
                if "error" in data:
                    err = data["error"]
                    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    return {"ok": False, "error": f"OpenRouter: {msg}"}
                resp.raise_for_status()
                text = _extract_openrouter_text(data)
                return _ok(text, self.openrouter_chat)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if provider == "gemini":
            if not self.gemini_key:
                return {"ok": False, "error": "GEMINI_API_KEY not set"}
            try:
                text = await self._gemini_chat("Say OK", "", model=self.gemini_chat, api_key=self.gemini_key)
                if not text:
                    return {"ok": False, "error": "Gemini вернул пустой ответ (проверь модель/ключ)"}
                return _ok(text, self.gemini_chat)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if provider == "openai":
            if not self.openai_key:
                return {"ok": False, "error": "OPENAI_API_KEY not set"}
            try:
                text = await self._openai_chat("Say OK", "", model=self.openai_chat, api_key=self.openai_key)
                if not text:
                    return {"ok": False, "error": "OpenAI вернул пустой ответ (проверь модель/ключ)"}
                return _ok(text, self.openai_chat)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if provider == "anthropic":
            if not self.anthropic_key:
                return {"ok": False, "error": "ANTHROPIC_API_KEY not set"}
            try:
                text = await self._anthropic_chat("Say OK", "", model=self.anthropic_chat, api_key=self.anthropic_key)
                if not text:
                    return {"ok": False, "error": "Anthropic вернул пустой ответ (проверь модель/ключ)"}
                return _ok(text, self.anthropic_chat)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if provider == "custom":
            if not self.custom_api_key and not self.custom_base_url:
                return {"ok": False, "error": "Custom AI base URL or API key not set"}
            try:
                text = await self._openai_chat("Say OK", "", model=self.custom_model,
                                               api_key=self.custom_api_key,
                                               base_url=self.custom_base_url)
                return _ok(text or "", self.custom_model)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        # DEF-03: именованные провайдеры custom:<имя>
        if provider.startswith("custom:"):
            name = provider.split(":", 1)[1].strip()
            cfg = self.get_custom_provider(name)
            if not cfg:
                return {"ok": False, "error": f"Custom provider '{name}' not found"}
            if not cfg.get("base_url"):
                return {"ok": False, "error": f"Custom provider '{name}' has no base URL"}
            model = (cfg.get("models") or [""])[0]
            if not model:
                return {"ok": False, "error": f"Custom provider '{name}' has no chat model"}
            try:
                text = await self._openai_chat("Say OK", "", model=model,
                                               api_key=cfg.get("api_key") or "",
                                               base_url=cfg["base_url"])
                if not text:
                    return {"ok": False, "error": f"Custom provider '{name}' returned empty response"}
                return _ok(text, model)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if provider not in self.SUPPORTED_PROVIDERS:
            return {"ok": False, "error": f"Unsupported provider: {provider}"}
        # ollama (default fallback)
        try:
            resp = await self._client.post(
                f"{self.ollama_host}/api/generate",
                json={"model": self.ollama_chat, "prompt": "Say OK", "stream": False},
            )
            if resp.status_code == 500:
                return {"ok": False, "error": f"Ollama error 500. Выполните: ollama pull {self.ollama_chat}"}
            resp.raise_for_status()
            text = resp.json().get("response", "").strip()
            return _ok(text, self.ollama_chat)
        except (httpx.ConnectError, OSError):
            return {"ok": False, "error": f"Ollama не запущен на {self.ollama_host}. Запустите в терминале: ollama serve"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def close(self) -> None:
        await self._client.aclose()
