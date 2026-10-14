#!/usr/bin/env python3
"""DIR-LIVE-10: реальный provider/model replay для живой приёмки Director.

Гоняет выбранные владельцем provider/model комбинации через НАШ production
транспорт (ProductionDirectorAdapter.generate_plan → ai_service.generate_text_with)
и нашу валидацию (validate_replay_response: strict JSON + schema + hard-safety).

Цели задаются переменными окружения (ключи не хранятся в репозитории):
    OPENROUTER_API_KEY   + OPENROUTER_MODELS  (через запятую)
    CUSTOM_AI_BASE_URL   + CUSTOM_AI_API_KEY  + CUSTOM_MODELS (через запятую)

На каждую цель: один plan-replay с реальным моментом чата, замер latency,
валидация ответа; один error-probe с несуществующей моделью (поведение
транспорта при ошибке). Объём внешних вызовов ограничен: ≤2 на цель.

Использование (из корня проекта):
    OPENROUTER_API_KEY=... OPENROUTER_MODELS=m1,m2 \
    CUSTOM_AI_BASE_URL=... CUSTOM_AI_API_KEY=... CUSTOM_MODELS=m3,m4 \
    .venv/bin/python scripts/director_live10_providers.py
"""

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app import director, director_review  # noqa: E402
from app.ai_service import AIService  # noqa: E402
from app.director import ProductionDirectorAdapter  # noqa: E402

MOMENT = (
    "Чат резко ускорился: зрители спамят POGGERS после клатча в финальном "
    "раунде, Viewer-1 пишет «это было красиво», просят реакцию"
)


def _mask(value: str) -> str:
    return (value[:6] + "…") if value else ""


def build_targets() -> list[dict]:
    targets: list[dict] = []
    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    or_models = [m.strip() for m in os.getenv("OPENROUTER_MODELS", "").split(",") if m.strip()]
    if or_key and or_models:
        targets.extend({"provider": "openrouter", "model": m, "key_set": True} for m in or_models)
    custom_url = os.getenv("CUSTOM_AI_BASE_URL", "").strip().rstrip("/")
    custom_key = os.getenv("CUSTOM_AI_API_KEY", "").strip()
    custom_models = [m.strip() for m in os.getenv("CUSTOM_MODELS", "").split(",") if m.strip()]
    if custom_url and custom_key and custom_models:
        targets.extend({"provider": "custom", "model": m, "key_set": True} for m in custom_models)
    return targets


async def run_target(adapter: ProductionDirectorAdapter, service: AIService, target: dict) -> dict:
    config = director.validate_config({
        **director.DEFAULT_CONFIG,
        "provider": target["provider"],
        "model": target["model"],
        "mode": "suggest",
        "temperature": 0.4,
        "max_tokens": int(os.getenv("LIVE10_MAX_TOKENS", "300")) if os.getenv("LIVE10_MAX_TOKENS", "300").isdigit() and 50 <= int(os.getenv("LIVE10_MAX_TOKENS", "300")) <= 1000 else 300,
    })
    prompt_text = "Держи короткую живую реакцию в тоне чата, без упоминаний."
    snapshot = director_review._replay_snapshot(
        "live10check", "run-live10", "case-live10", MOMENT, config
    )
    row: dict = {"provider": target["provider"], "model": target["model"], "key": _mask(
        os.getenv("OPENROUTER_API_KEY", "") or os.getenv("CUSTOM_AI_API_KEY", "")
    )}

    ready = adapter.provider_ready(config)
    row["provider_ready"] = ready
    if not ready:
        row["error"] = "provider_not_ready"
        return row

    start = time.monotonic()
    try:
        response = await adapter.generate_plan(config, prompt_text, snapshot)
    except Exception as exc:  # noqa: BLE001 — отчёт по любой ошибке транспорта
        row["latency_s"] = round(time.monotonic() - start, 2)
        row["error"] = type(exc).__name__
        return row
    row["latency_s"] = round(time.monotonic() - start, 2)

    # Детальный вердикт: strict-JSON / schema / plan-reject — что именно не так.
    try:
        plan = director_review.extract_strict_plan_json(response)
    except Exception as exc:  # noqa: BLE001
        row["replay_valid"] = False
        row["replay_verdict"] = f"strict_json: {type(exc).__name__}: {exc}"
        row["response_head"] = response[:400]
        return row
    if not director_review._matches_schema(plan, director_review.DIRECTOR_PLAN_JSON_SCHEMA):
        row["replay_valid"] = False
        row["replay_verdict"] = "schema_mismatch"
        row["response_head"] = response[:400]
        return row
    ok, reason = director_review.validate_replay_response(response, snapshot, config)
    row["replay_valid"] = ok
    row["replay_verdict"] = reason
    if not ok:
        row["response_head"] = response[:400]
    row["response_bytes"] = len(response.encode())
    return row


async def error_probe(adapter: ProductionDirectorAdapter, service: AIService, target: dict) -> dict:
    """Error-behavior: заведомо несуществующая модель — время и тип ошибки."""
    config = director.validate_config({
        **director.DEFAULT_CONFIG,
        "provider": target["provider"],
        "model": "live10-nonexistent-model",
        "mode": "suggest",
    })
    prompt_text = "probe"
    snapshot = director_review._replay_snapshot(
        "live10check", "run-live10", "case-probe", "probe", config
    )
    row: dict = {"probe": "error_behavior", "provider": target["provider"], "model": target["model"]}
    start = time.monotonic()
    try:
        await adapter.generate_plan(config, prompt_text, snapshot)
        row["error"] = "unexpected_success"
    except Exception as exc:  # noqa: BLE001
        row["latency_s"] = round(time.monotonic() - start, 2)
        row["error"] = type(exc).__name__
    return row


async def main() -> int:
    targets = build_targets()
    if not targets:
        print(json.dumps({"error": "no targets: set OPENROUTER_API_KEY/OPENROUTER_MODELS and/or CUSTOM_*"}, ensure_ascii=False))
        return 2
    service = AIService()
    service.local_fallback_enabled = False  # честное поведение целевого провайдера
    service.offline_mode = False
    adapter = ProductionDirectorAdapter(service, None, None)

    results = []
    for index, target in enumerate(targets):
        if index:
            time.sleep(15)  # free-tier IP-лимиты: пауза между целями
        results.append(await run_target(adapter, service, target))
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
