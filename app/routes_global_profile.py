"""global_profile — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from fastapi import HTTPException, Request
from app.routes import router, get_db, router  # noqa: E402


# ===================== PLAN_FEEDBACK_2908 §5: ГЛОБАЛЬНЫЙ ПРОФИЛЬ СТРИМЕРА =====================
# Панельный слой (account_id=0): «Глобальный профиль (все каналы/боты)» и
# per-channel профили. Старые per-account роуты выше работают как раньше.
# Рантайм-резолвер: bot+channel → bot global → panel channel → panel global.

@router.get("/api/streamer-channels")
async def list_all_streamer_channels() -> dict:
    """§5: каналы всех ботов — для селекта в глобальном профиле стримера."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT DISTINCT lower(trim(channel_name)) AS channel FROM channels "
            "ORDER BY channel"
        )
        rows = [r["channel"] for r in await cursor.fetchall()]
        return {"channels": [c for c in rows if c]}
    finally:
        await db.close()


@router.get("/api/streamer-profile/resolve")
async def resolve_streamer_profile(account_id: int, channel: str = "") -> dict:
    """§5: какой профиль применится для бота на канале (fallback-цепочка)."""
    from app.streamer_profile import get_streamer_profile_resolved
    profile = await get_streamer_profile_resolved(account_id, channel)
    if not profile:
        return {"ok": True, "scope_label": "—", "profile": None}
    scope = profile.get("scope", "")
    if scope.startswith("bot#"):
        label = scope.replace("bot#", "бот #").replace("/#", " · #").replace("/global", " · глобальный")
    else:
        label = {"global/all": "🌐 глобальный (панель)",
                 "global/": "🌐 глобальный (панель)"}.get(scope, f"🌐 панель · {scope}")
    return {"ok": True, "scope_label": label, "profile": profile}

def _required_channel(channel: str) -> str:
    ch = (channel or "").strip().lstrip("#").lower()
    if not ch:
        raise HTTPException(status_code=400, detail="channel_required")
    return "#" + ch


def _channel_scope(channel: str) -> str:
    return f"канал {_required_channel(channel).lstrip('#')}"


@router.get("/api/streamer-profile")
async def global_streamer_profile_get(channel: str = ""):
    channel = _required_channel(channel)
    from app.streamer_profile import get_streamer_profile
    profile = await get_streamer_profile(0, channel)
    return {"ok": True, "scope": _channel_scope(channel), "profile": profile}


@router.put("/api/streamer-profile")
async def global_streamer_profile_put(request: Request, channel: str = ""):
    channel = _required_channel(channel)
    from app.streamer_profile import upsert_streamer_profile
    body = await request.json()
    await upsert_streamer_profile(0, body, channel)
    return {"ok": True, "scope": _channel_scope(channel)}


@router.delete("/api/streamer-profile")
async def global_streamer_profile_delete(channel: str = ""):
    channel = _required_channel(channel)
    from app.streamer_profile import delete_streamer_profile
    await delete_streamer_profile(0, channel)
    return {"ok": True, "scope": _channel_scope(channel)}


@router.get("/api/streamer-face")
async def global_streamer_face_get(channel: str = "", include: int = 0):
    channel = _required_channel(channel)
    from app.streamer_profile import get_streamer_face
    face = await get_streamer_face(0, include_image=bool(include), channel=channel)
    if not face:
        return {"ok": True, "has_face": False, "scope": _channel_scope(channel)}
    return {"ok": True, "has_face": True, "scope": _channel_scope(channel), **face}


@router.post("/api/streamer-face")
async def global_streamer_face_post(request: Request, channel: str = ""):
    channel = _required_channel(channel)
    import base64
    from app.streamer_profile import upsert_streamer_face
    form = await request.form()
    file = form.get("file")
    if not file:
        return {"error": "No file uploaded"}
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:  # 2MB limit
        return {"error": "File too large (max 2MB)"}
    mime = file.content_type or "image/jpeg"
    b64 = base64.b64encode(contents).decode()
    await upsert_streamer_face(0, b64, mime, channel)
    return {"ok": True, "mime_type": mime, "size": len(contents), "scope": _channel_scope(channel)}


@router.delete("/api/streamer-face")
async def global_streamer_face_delete(channel: str = ""):
    channel = _required_channel(channel)
    from app.streamer_profile import delete_streamer_face
    await delete_streamer_face(0, channel)
    return {"ok": True, "scope": _channel_scope(channel)}
