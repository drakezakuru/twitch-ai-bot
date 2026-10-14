"""Owner settings for the Media Share external-provider disclosure.

Q16 F2 (DEC-OWNER-016): UI (модалка + «показать снова») убран — в форме
медиа-шары постоянная подсказка. Роуты остаются legacy-контрактом
(``DEC-MEDIA-001``); сохранённое значение не удаляется, но из UI недостижимо.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.database import get_setting_bool, set_setting
from app.security import auth_dependency


router = APIRouter(dependencies=[Depends(auth_dependency)], tags=["media-share"])

_DISCLOSURE_KEY = "media_share_youtube_disclosure_acknowledged"


@router.get("/api/media-share/disclosure")
async def get_media_share_disclosure() -> dict[str, bool]:
    return {"acknowledged": await get_setting_bool(_DISCLOSURE_KEY)}


@router.put("/api/media-share/disclosure")
async def set_media_share_disclosure(payload: dict[str, Any]) -> dict[str, bool]:
    acknowledged = payload.get("acknowledged") is True
    await set_setting(_DISCLOSURE_KEY, "1" if acknowledged else "0")
    return {"ok": True, "acknowledged": acknowledged}
