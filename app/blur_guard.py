"""§13 WIDGETS_PLAN: OBS Blur Guard — автоматическое «затемнение» стрима.

Как это работает:
    1. Фоновый цикл (``analysis_loop``, старт из server.lifespan) раз в
       ``interval_sec`` берёт последний кадр Stream Vision (папка ``FRAMES_DIR``)
       и прогоняет через публичный интерфейс ``ai_service.analyze_image``
       (локальный Ollama Vision или облачный провайдер — настроен в AI-настройках
       панели; зоны general не касаемся).
    2. Модель возвращает JSON-вердикт {nsfw, categories, confidence}.
       Порог задаёт ``sensitivity`` (0-100). Учитываются поправки локальных
       правил из feedback'ов (§13.3) — ``blur_guard_rules``.
    3. При срабатывании: pre-delay (защита от ложных positives) →
       broadcast ``blur_on`` через widget-события → через ``blur_duration_sec``
       — ``blur_off``. Ручное включение/выключение (публичные роуты для
       OBS-хоткеев, §13.1 «ручной bind») имеет приоритет над AI.
    4. Виджет-оверлей ``/obs/blur-guard`` (widgets/blur-guard/index.html)
       слушает WS-события и рисует «матовое стекло» поверх сцены.

Ограничение OBS (честно документируем): Browser Source не может блюрить
*другие* источники сцены — оверлей закрывает экран плотным матовым слоем.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Категории по §13.2 (добавляются пользовательские из настроек).
DEFAULT_CATEGORIES = [
    "нагота",
    "сексуальный контент",
    "грудь и гениталии",
    "чрезмерно открытое тело",
    "кровь и жестокость",
    "оружие",
]

# In-memory состояние (сбрасывается рестартом — ок, стрим тоже перезапускается).
_state = {
    "blur_until": 0.0,        # до какого времени блюр включён (AI)
    "manual_on": False,       # ручное включение (приоритет над AI)
    "manual_off_until": 0.0,  # ручное выключение подавляет AI на N секунд
    "last_check": 0.0,
}


def _build_prompt(custom_prompt: str, categories: list[str]) -> str:
    cats = ", ".join(categories)
    base = (
        "Ты модератор стрима. Посмотри на кадр и ответь СТРОГО в формате JSON: "
        '{"nsfw": true/false, "categories": ["..."], "confidence": 0.0-1.0}. '
        f"Проверяй категории: {cats}. "
        "nsfw=true если кадр требует блюра, confidence — уверенность. "
        "Без пояснений, только JSON."
    )
    if custom_prompt.strip():
        base = custom_prompt.strip() + "\n" + base
    return base


def _parse_verdict(text: str) -> dict | None:
    """Парсинг JSON-вердикта модели (с фолбэком на yes/no)."""
    if not text:
        return None
    text = text.strip()
    # Попробуем вытащить первый JSON-объект из ответа.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return {
                "nsfw": bool(data.get("nsfw")),
                "categories": [str(c) for c in (data.get("categories") or [])][:5],
                "confidence": max(0.0, min(1.0, float(data.get("confidence") or 0))),
            }
        except (ValueError, TypeError):
            pass
    low = text.lower()
    if "yes" in low or "nsfw: true" in low:
        return {"nsfw": True, "categories": [], "confidence": 0.5}
    return {"nsfw": False, "categories": [], "confidence": 0.5}


# ── Настройки / правила (БД) ────────────────────────────────────


async def ensure_schema() -> None:
    from app.widgets import get_db
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS blur_guard_settings (
                id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                sensitivity INTEGER DEFAULT 70,
                interval_sec INTEGER DEFAULT 10,
                pre_delay_ms INTEGER DEFAULT 800,
                blur_duration_sec INTEGER DEFAULT 15,
                custom_prompt TEXT DEFAULT '',
                categories TEXT DEFAULT '[]',
                vision_model TEXT DEFAULT '',
                vision_provider TEXT DEFAULT '',
                blur_percent INTEGER DEFAULT 100,
                blur_mode TEXT DEFAULT 'gaussian',
                region TEXT DEFAULT '',
                consecutive_clean_frames INTEGER DEFAULT 5,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS blur_guard_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT DEFAULT '',
                ai_decision INTEGER DEFAULT 0,
                user_decision INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0,
                prompt TEXT DEFAULT '',
                model TEXT DEFAULT '',
                category TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS blur_guard_rules (
                category TEXT PRIMARY KEY,
                threshold_delta INTEGER DEFAULT 0
            );
        """)
        await db.execute(
            "INSERT OR IGNORE INTO blur_guard_settings (id) VALUES (1)"
        )
        await db.commit()
        # v2 migration: blur_mode, region, consecutive_clean_frames
        for col, typedef in [
            ("blur_mode", "TEXT DEFAULT 'gaussian'"),
            ("region", "TEXT DEFAULT ''"),
            ("consecutive_clean_frames", "INTEGER DEFAULT 5"),
            # P8-W1: always-on зоны для blur-guard-v2 (live-обновление по WS)
            ("always_zones", "TEXT DEFAULT ''"),
            ("protection_mode", "TEXT DEFAULT 'mask'"),
            ("obs_source_name", "TEXT DEFAULT ''"),
            ("obs_filter_name", "TEXT DEFAULT ''"),
        ]:
            try:
                await db.execute(f"ALTER TABLE blur_guard_settings ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # column already exists
        await db.commit()
    finally:
        await db.close()


async def get_settings() -> dict:
    await ensure_schema()
    from app.widgets import get_db
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM blur_guard_settings WHERE id = 1")
        row = await cursor.fetchone()
        data = dict(row) if row else {}
    finally:
        await db.close()
    try:
        extra = json.loads(data.get("categories") or "[]")
    except ValueError:
        extra = []
    data["custom_categories"] = extra
    data.pop("categories", None)
    return data


async def update_settings(payload: dict) -> dict:
    await ensure_schema()
    from app.widgets import get_db
    fields: list[str] = []
    values: list = []
    int_fields = {
        "sensitivity": (1, 100), "interval_sec": (3, 120),
        "pre_delay_ms": (0, 5000), "blur_duration_sec": (1, 600),
    }
    for k, (lo, hi) in int_fields.items():
        if k in payload:
            try:
                fields.append(f"{k} = ?")
                values.append(max(lo, min(hi, int(payload[k]))))
            except (TypeError, ValueError):
                pass
    if "custom_prompt" in payload:
        fields.append("custom_prompt = ?")
        values.append(str(payload["custom_prompt"] or "")[:2000])
    if "vision_model" in payload:
        fields.append("vision_model = ?")
        values.append(str(payload["vision_model"] or "")[:80])
    if "vision_provider" in payload:
        fields.append("vision_provider = ?")
        values.append(str(payload["vision_provider"] or "")[:40])
    if "enabled" in payload:
        fields.append("enabled = ?")
        values.append(1 if payload["enabled"] else 0)
    if "blur_percent" in payload:
        # §13.3: интенсивность матового слоя 1-100% (1% — едва заметная дымка)
        try:
            fields.append("blur_percent = ?")
            values.append(max(1, min(100, int(payload["blur_percent"]))))
        except (TypeError, ValueError):
            pass
    if "blur_mode" in payload:
        mode = str(payload["blur_mode"] or "gaussian").lower()
        if mode in ("gaussian", "mosaic", "combo"):
            fields.append("blur_mode = ?")
            values.append(mode)
    if "region" in payload:
        fields.append("region = ?")
        values.append(str(payload["region"] or "")[:40])
    if "consecutive_clean_frames" in payload:
        try:
            fields.append("consecutive_clean_frames = ?")
            values.append(max(1, min(60, int(payload["consecutive_clean_frames"]))))
        except (TypeError, ValueError):
            pass
    if "always_zones" in payload:
        # P8-W1: always-on зоны blur-guard-v2 ("x,y,w,h;..." | "")
        fields.append("always_zones = ?")
        values.append(str(payload["always_zones"] or "")[:500])
    if "protection_mode" in payload:
        mode = str(payload["protection_mode"] or "mask").lower()
        if mode in ("mask", "image", "obs_filter"):
            fields.append("protection_mode = ?")
            values.append(mode)
    for key in ("obs_source_name", "obs_filter_name"):
        if key in payload:
            fields.append(f"{key} = ?")
            values.append(str(payload[key] or "")[:120])
    if "categories" in payload:
        cats = [str(c).strip()[:60] for c in (payload["categories"] or []) if str(c).strip()]
        fields.append("categories = ?")
        values.append(json.dumps(cats[:20], ensure_ascii=False))
    if fields:
        db = await get_db()
        try:
            values.append(1)
            await db.execute(
                f"UPDATE blur_guard_settings SET {', '.join(fields)} WHERE id = ?",
                tuple(values),
            )
            await db.commit()
        finally:
            await db.close()
    runtime_fields = {
        "always_zones", "blur_percent", "blur_mode", "region",
        "consecutive_clean_frames",
        "protection_mode", "obs_source_name", "obs_filter_name",
    }
    if runtime_fields.intersection(payload):
        await broadcast_runtime("blur_config")
    return await get_settings()


def _active_categories(settings: dict) -> list[str]:
    return DEFAULT_CATEGORIES + [c for c in settings.get("custom_categories", [])
                                 if c not in DEFAULT_CATEGORIES]


async def _rule_threshold_delta(categories: list[str]) -> int:
    """Суммарная поправка порога по правилам из feedback'ов (§13.3)."""
    if not categories:
        return 0
    from app.widgets import get_db
    db = await get_db()
    try:
        marks = ",".join("?" for _ in categories)
        cursor = await db.execute(
            f"SELECT COALESCE(SUM(threshold_delta), 0) AS d FROM blur_guard_rules "
            f"WHERE category IN ({marks})",
            tuple(categories),
        )
        row = await cursor.fetchone()
        return int(row["d"] or 0) if row else 0
    finally:
        await db.close()


def is_blur_active() -> bool:
    return _state["manual_on"] or time.time() < _state["blur_until"]


def manual_on() -> None:
    _state["manual_on"] = True


def manual_off(seconds: int = 120) -> None:
    """Ручное выключение: сброс manual-вкл и подавление AI-блюра."""
    _state["manual_on"] = False
    _state["blur_until"] = 0.0
    _state["manual_off_until"] = time.time() + max(10, seconds)


# ── Feedback (§13.3) ────────────────────────────────────────────


async def add_feedback(payload: dict) -> dict:
    """Сохраняет фидбек пользователя («Блюрить» / «Не блюрить») и обновляет
    локальные правила: 3+ одинаковых ответа по категории двигают порог."""
    await ensure_schema()
    from app.widgets import get_db
    ai_decision = 1 if payload.get("ai_decision") else 0
    user_decision = 1 if payload.get("user_decision") else 0
    category = str(payload.get("category") or "")[:60]
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO blur_guard_feedback (channel, ai_decision, user_decision, "
            "confidence, prompt, model, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(payload.get("channel") or "")[:60], ai_decision, user_decision,
             float(payload.get("confidence") or 0),
             str(payload.get("prompt") or "")[:2000],
             str(payload.get("model") or "")[:80], category),
        )
        await db.commit()
        # Локальное правило: если по категории юзер регулярно расходится с AI.
        if category:
            delta = 0
            if not user_decision and ai_decision:
                delta = +10  # AI блюрил зря → порог строже
            elif user_decision and not ai_decision:
                delta = -10  # юзер хотел блюр → порог мягче
            if delta:
                cursor = await db.execute(
                    "SELECT COUNT(*) AS n FROM blur_guard_feedback WHERE category = ? "
                    "AND user_decision = ? AND ai_decision = ?",
                    (category, user_decision, ai_decision),
                )
                row = await cursor.fetchone()
                # Одноразовая поправка: правило применяется один раз,
                # когда набралось ровно 3 одинаковых расходящихся фидбека.
                if row and int(row["n"]) == 3:
                    await db.execute(
                        "INSERT INTO blur_guard_rules (category, threshold_delta) "
                        "VALUES (?, ?) ON CONFLICT(category) DO UPDATE SET "
                        "threshold_delta = threshold_delta + excluded.threshold_delta",
                        (category, delta),
                    )
                    await db.commit()
    finally:
        await db.close()
    return {"ok": True}


async def list_feedback(limit: int = 50) -> list[dict]:
    await ensure_schema()
    from app.widgets import get_db
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, channel, ai_decision, user_decision, confidence, prompt, "
            "model, category, created_at FROM blur_guard_feedback "
            "ORDER BY id DESC LIMIT ?", (max(1, min(200, limit)),),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


# ── Анализ (цикл) ───────────────────────────────────────────────


def _latest_frame() -> Path | None:
    """Последний сохранённый кадр Stream Vision (data/stream_vision_frames)."""
    try:
        from app.stream_vision import FRAMES_DIR
        frames = sorted(
            (p for p in Path(FRAMES_DIR).glob("*.jpg") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        return frames[-1] if frames else None
    except Exception as exc:
        logger.debug("[blur-guard] no frames: %s", exc)
        return None


async def _broadcast(kind: str, extra: dict | None = None) -> None:
    """Событие для виджета-оверлея через общий /ws."""
    try:
        from app.routes import broadcast_log
        await broadcast_log({"type": "blur_guard", "kind": kind, "at": time.time(),
                             **(extra or {})})
    except Exception as exc:
        logger.debug("[blur-guard] broadcast failed: %s", exc)


def _runtime_config(settings: dict) -> dict:
    cover_percent = int(settings.get("blur_percent") or 100)
    return {
        "mode": "manual" if _state["manual_on"] else "ai",
        "blur_percent": cover_percent,
        # New clients use the honest name; blur_percent stays for old OBS URLs/clients.
        "cover_percent": cover_percent,
        "blur_mode": settings.get("blur_mode") or "gaussian",
        "region": settings.get("region") or "",
        "always_zones": settings.get("always_zones") or "",
        "consecutive_clean_frames": int(
            settings.get("consecutive_clean_frames") or 5
        ),
        "persistent": bool(_state["manual_on"]),
        "protection_mode": settings.get("protection_mode") or "mask",
        "cover_image_url": "/api/widgets/public/blur-guard/image",
        "obs_source_name": settings.get("obs_source_name") or "",
        "obs_filter_name": settings.get("obs_filter_name") or "",
    }


async def get_runtime_state() -> dict:
    return {
        "blur": is_blur_active(),
        "at": time.time(),
        **_runtime_config(await get_settings()),
    }


async def broadcast_runtime(kind: str, extra: dict | None = None) -> None:
    payload = _runtime_config(await get_settings())
    payload.update(extra or {})
    if kind == "blur_on":
        await _broadcast("blur_on", payload)
    elif kind == "blur_off":
        await _broadcast("blur_off", payload)
    elif kind == "blur_config":
        await _broadcast("blur_config", payload)
    else:
        raise ValueError(f"unsupported Blur Guard event: {kind}")


async def sync_obs_filter(enabled: bool) -> None:
    settings = await get_settings()
    if settings.get("protection_mode") != "obs_filter":
        return
    source = str(settings.get("obs_source_name") or "").strip()
    filter_name = str(settings.get("obs_filter_name") or "").strip()
    if not source or not filter_name:
        raise ValueError("OBS source and blur filter names are required")
    from app.obs_blur import set_filter_enabled
    await set_filter_enabled(source, filter_name, enabled)


async def _disable_obs_filter_after(duration_sec: int) -> None:
    await asyncio.sleep(max(1, duration_sec))
    if not is_blur_active():
        try:
            await sync_obs_filter(False)
        except Exception as exc:
            logger.warning("[blur-guard] OBS filter disable failed: %s", exc)


async def trigger_blur(duration_sec: int, source: str = "ai") -> None:
    """Включить блюр (AI или временный bind) и запланировать отбой."""
    if _state["manual_on"]:
        return
    _state["blur_until"] = time.time() + max(1, duration_sec)
    settings = await get_settings()
    await broadcast_runtime("blur_on", {
        "source": source,
        "duration": max(1, duration_sec),
        "persistent": False,
    })
    try:
        await sync_obs_filter(True)
        asyncio.create_task(_disable_obs_filter_after(duration_sec))
    except Exception as exc:
        logger.warning("[blur-guard] OBS filter enable failed: %s", exc)
    logger.info("[blur-guard] BLUR ON (%s, %ss, %s%%)", source, duration_sec,
                settings.get("blur_percent") or 100)


async def _check_once() -> None:
    try:
        # Публичный интерфейс AI (зона general не редактируется): синглтон
        # ai_service из server.py + analyze_image (Ollama Vision / облачные).
        from app.server import ai_service as ai
    except Exception:
        return
    settings = await get_settings()
    if not settings.get("enabled"):
        return
    frame = _latest_frame()
    if frame is None:
        return
    try:
        from PIL import Image
        img = Image.open(frame).convert("RGB")
    except Exception as exc:
        logger.debug("[blur-guard] frame open failed: %s", exc)
        return
    prompt = _build_prompt(settings.get("custom_prompt") or "",
                           _active_categories(settings))
    verdict = None
    try:
        answer = await ai.analyze_image(img, prompt)
        verdict = _parse_verdict(answer)
    except Exception as exc:
        logger.debug("[blur-guard] analyze failed: %s", exc)
        return
    if verdict is None:
        return
    base_threshold = int(settings.get("sensitivity") or 70) / 100.0
    delta = await _rule_threshold_delta(verdict["categories"]) / 100.0
    threshold = max(0.05, min(1.0, base_threshold + delta))
    triggered = verdict["nsfw"] and verdict["confidence"] >= threshold
    if triggered and time.time() > _state["manual_off_until"]:
        # pre-delay: защита от ложных срабатываний
        await asyncio.sleep(int(settings.get("pre_delay_ms") or 0) / 1000.0)
        if verdict["confidence"] >= threshold:
            await trigger_blur(int(settings.get("blur_duration_sec") or 15))


async def analysis_loop() -> None:
    """Фоновый цикл (server.lifespan одной строкой)."""
    logger.info("[blur-guard] analysis loop запущен")
    interval = 10
    while True:
        try:
            settings = await get_settings()
            interval = max(3, int(settings.get("interval_sec") or 10))
            if settings.get("enabled"):
                _state["last_check"] = time.time()
                await _check_once()
        except Exception as exc:
            logger.debug("[blur-guard] loop error: %s", exc)
        await asyncio.sleep(interval)
