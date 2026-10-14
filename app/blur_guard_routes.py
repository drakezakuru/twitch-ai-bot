"""§13 WIDGETS_PLAN: роуты Blur Guard (зона widgets, подключается одной
строкой include_router в app/server.py).

Admin (Basic-auth панели):
    GET  /api/blur-guard              — настройки
    PUT  /api/blur-guard              — настройки (вкл/выкл, чувствительность…)
    GET  /api/blur-guard/feedback     — журнал фидбеков

Public (без auth — OBS-хоткеи/бинды и виджет-оверлей):
    POST /api/widgets/public/blur-guard/on        — ручной bind «блюрить»
    POST /api/widgets/public/blur-guard/off       — ручной bind «выключить»
    POST /api/widgets/public/blur-guard/temp      — временный блюр {seconds}
    GET  /api/widgets/public/blur-guard/state     — текущее состояние
    POST /api/widgets/public/blur-guard/feedback  — «Блюрить/Не блюрить» с оверлея
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from app.blur_guard import (
    add_feedback,
    broadcast_runtime,
    get_settings,
    get_runtime_state,
    list_feedback,
    manual_off,
    manual_on,
    sync_obs_filter,
    trigger_blur,
    update_settings,
)
from app.security import auth_dependency

admin_router = APIRouter(dependencies=[Depends(auth_dependency)])
public_router = APIRouter()


@admin_router.get("/api/blur-guard")
async def blur_guard_settings_get() -> dict:
    return await get_settings()


@admin_router.put("/api/blur-guard")
async def blur_guard_settings_put(payload: dict) -> dict:
    return await update_settings(payload)


@admin_router.get("/api/blur-guard/feedback")
async def blur_guard_feedback_list(limit: int = 50) -> list[dict]:
    return await list_feedback(limit)


@public_router.post("/api/widgets/public/blur-guard/on")
async def blur_guard_manual_on() -> dict:
    try:
        await sync_obs_filter(True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    manual_on()
    await broadcast_runtime("blur_on", {"source": "manual"})
    return {"ok": True, "blur": True}


@public_router.post("/api/widgets/public/blur-guard/off")
async def blur_guard_manual_off() -> dict:
    try:
        await sync_obs_filter(False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    manual_off()
    await broadcast_runtime("blur_off", {"source": "manual"})
    return {"ok": True, "blur": False}


@public_router.post("/api/widgets/public/blur-guard/temp")
async def blur_guard_temp(payload: dict | None = None) -> dict:
    seconds = 10
    if payload and "seconds" in payload:
        try:
            seconds = max(1, min(600, int(payload["seconds"])))
        except (TypeError, ValueError):
            seconds = 10
    await trigger_blur(seconds, source="manual_temp")
    return {"ok": True, "seconds": seconds}


@public_router.get("/api/widgets/public/blur-guard/state")
async def blur_guard_state() -> dict:
    return await get_runtime_state()


@admin_router.post("/api/blur-guard/image")
async def blur_guard_image_upload(file: UploadFile = File(...)) -> dict:
    from app.runtime_paths import BLUR_GUARD_DIR
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image is too large (max 10 MB)")
    BLUR_GUARD_DIR.mkdir(parents=True, exist_ok=True)
    target = BLUR_GUARD_DIR / "cover.webp"
    try:
        import io
        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((3840, 2160))
            image.convert("RGB").save(target, "WEBP", quality=92)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid image") from exc
    await broadcast_runtime("blur_config")
    return {"ok": True, "url": "/api/widgets/public/blur-guard/image"}


@public_router.get("/api/widgets/public/blur-guard/image")
async def blur_guard_image() -> FileResponse:
    from app.runtime_paths import BLUR_GUARD_DIR
    target = BLUR_GUARD_DIR / "cover.webp"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Blur Guard image is not configured")
    return FileResponse(target, media_type="image/webp")


@public_router.post("/api/widgets/public/blur-guard/feedback")
async def blur_guard_feedback(payload: dict) -> dict:
    return await add_feedback(payload)
