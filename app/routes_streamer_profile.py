"""streamer_profile — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from fastapi import HTTPException, Request
from app.routes import router, router  # noqa: E402


# ===================== v11: STREAMER PROFILE + FACE =====================

@router.get("/api/accounts/{account_id}/streamer-profile")
async def get_streamer_profile_route(account_id: int, channel: str = ""):
    from app.streamer_profile import get_streamer_profile
    if not channel.strip():
        raise HTTPException(status_code=400, detail="channel_required")
    profile = await get_streamer_profile(account_id, channel)
    return {"ok": True, "profile": profile}


@router.put("/api/accounts/{account_id}/streamer-profile")
async def upsert_streamer_profile_route(account_id: int, request: Request, channel: str = ""):
    from app.streamer_profile import upsert_streamer_profile
    if not channel.strip():
        raise HTTPException(status_code=400, detail="channel_required")
    body = await request.json()
    await upsert_streamer_profile(account_id, body, channel)
    return {"ok": True}


@router.get("/api/accounts/{account_id}/streamer-face")
async def get_streamer_face_route(account_id: int, include: int = 0):
    from app.streamer_profile import get_streamer_face
    face = await get_streamer_face(account_id, include_image=bool(include))
    if not face:
        return {"ok": True, "has_face": False}
    return {"ok": True, "has_face": True, **face}


@router.post("/api/accounts/{account_id}/streamer-face")
async def upload_streamer_face_route(account_id: int, request: Request):
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
    await upsert_streamer_face(account_id, b64, mime)
    return {"ok": True, "mime_type": mime, "size": len(contents)}


@router.delete("/api/accounts/{account_id}/streamer-face")
async def delete_streamer_face_route(account_id: int):
    from app.streamer_profile import delete_streamer_face
    await delete_streamer_face(account_id)
    return {"ok": True}
