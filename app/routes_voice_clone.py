"""voice_clone — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from app.routes import router  # noqa: E402


# ===================== v10.4.6 Wave 3: Voice cloning =====================

@router.get("/api/voice-clone/models")
async def voice_clone_list_models() -> dict:
    from app.voice_clone import list_voice_models

    return {"ok": True, "models": [m.to_dict() for m in list_voice_models()]}


@router.post("/api/voice-clone/upload")
async def voice_clone_upload(payload: dict) -> dict:
    """Сохраняет загруженный .onnx (+ опциональный .onnx.json).

    payload: {name, onnx_b64, config_json_b64?}
    """
    import base64

    from app.voice_clone import save_voice_model_files

    name = (payload.get("name") or "").strip()
    onnx_b64 = (payload.get("onnx_b64") or "").strip()
    cfg_b64 = (payload.get("config_json_b64") or "").strip()
    if not name or not onnx_b64:
        return {"ok": False, "error": "name и onnx_b64 обязательны"}
    try:
        onnx_bytes = base64.b64decode(onnx_b64)
        cfg_bytes = base64.b64decode(cfg_b64) if cfg_b64 else None
        vm = save_voice_model_files(name, onnx_bytes, cfg_bytes)
        return {"ok": True, "model": vm.to_dict()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.delete("/api/voice-clone/models/{name}")
async def voice_clone_delete(name: str) -> dict:
    from app.voice_clone import delete_voice_model

    return {"ok": True, "deleted": delete_voice_model(name)}


@router.get("/api/voice-clone/setup-guide")
async def voice_clone_setup_guide() -> dict:
    from pathlib import Path

    from app.voice_clone import write_setup_guide

    path = write_setup_guide()
    content = ""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except Exception:
        pass
    return {"ok": True, "path": path, "content": content}
