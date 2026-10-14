"""security — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from app.routes import (
    router,
    is_helix_configured, twitch_oauth,
)
from app.security import credential_storage_mode, is_auth_enabled, is_encryption_enabled, panel_access_mode


# ===================== FEATURE 1: SECURITY STATUS =====================

@router.get("/api/security/status")
async def security_status() -> dict:
    """Возвращает, включена ли авторизация и шифрование (для UI-индикаторов)."""
    storage_mode = credential_storage_mode()
    return {
        "auth_enabled": is_auth_enabled(),
        "access_mode": panel_access_mode(),
        "local_passwordless": panel_access_mode() in {"local_no_auth", "qa_no_auth"},
        "encryption_enabled": is_encryption_enabled(),
        "credential_storage_mode": storage_mode,
        "plaintext_warning": storage_mode == "local_plaintext",
        "helix_configured": is_helix_configured(),
        "device_oauth_configured": twitch_oauth.is_configured(),
    }
