"""token_refresh — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
import hashlib
import time
from typing import Any

from app.database import get_db, get_setting, set_setting
from app.routes import (
    router,
    decrypt_token, encrypt_token, is_helix_configured, log_action, refresh_oauth_token,
)
from app.twitch_helix import validate_oauth_token_status


# ===================== FEATURE 2: TOKEN REFRESH =====================

TOKEN_EXPIRY_WARNING_DAYS = "token_expiry_warning_days"
_TOKEN_STATUS_TTL = 600
_token_status_cache: dict[int, tuple[float, str, dict]] = {}


def _warning_days(value: Any) -> int:
    try:
        return max(1, min(90, int(value)))
    except (TypeError, ValueError):
        return 7


async def _token_status(account: Any, warning_days: int, now: int) -> str:
    token = decrypt_token(account["token"] or "")
    if not token:
        return "unknown"
    expires_at = int(account["token_expires_at"] or 0)
    if expires_at:
        if expires_at <= now:
            return "expired"
        if expires_at < now + warning_days * 86400:
            return "expiring"
        return "valid"

    if not account["has_refresh_token"]:
        return "not_refreshable"
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cached = _token_status_cache.get(account["id"])
    if cached and cached[0] > time.monotonic() and cached[1] == fingerprint:
        result = cached[2]
    else:
        result = await validate_oauth_token_status(token)
        if result.get("status") in {"valid", "expired"}:
            _token_status_cache[account["id"]] = (
                time.monotonic() + _TOKEN_STATUS_TTL, fingerprint, result,
            )
    if result.get("status") == "expired":
        return "expired"
    if result.get("status") != "valid":
        return "unknown"
    expires_in = int(result.get("expires_in", 0) or 0)
    return "expiring" if expires_in and expires_in < warning_days * 86400 else "valid"


@router.post("/api/accounts/{account_id}/refresh-token")
async def manual_refresh_token(account_id: int) -> dict:
    """Ручной refresh OAuth-токена аккаунта."""
    if not is_helix_configured():
        return {"ok": False, "error": "TWITCH_CLIENT_ID/SECRET не заданы в .env"}
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT refresh_token FROM accounts WHERE id = ?", (account_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"ok": False, "error": "Аккаунт не найден"}
        refresh = decrypt_token(row["refresh_token"] or "")
        if not refresh:
            return {"ok": False, "error": "У аккаунта нет refresh_token. Получи токен с refresh через oauth-flow."}
        result = await refresh_oauth_token(refresh)
        if not result:
            return {"ok": False, "error": "Twitch отклонил refresh. Возможно refresh_token устарел."}
        new_access = result.get("access_token", "")
        if not new_access:
            return {"ok": False, "error": "Twitch не вернул новый access_token."}
        new_refresh = result.get("refresh_token", refresh)
        expires_in = int(result.get("expires_in", 0))
        expires_at = int(time.time()) + expires_in if expires_in else 0
        await db.execute(
            "UPDATE accounts SET token = ?, refresh_token = ?, token_expires_at = ? WHERE id = ?",
            (encrypt_token(new_access), encrypt_token(new_refresh), expires_at, account_id),
        )
        await db.commit()
        _token_status_cache.pop(account_id, None)
        await log_action("Token refresh", f"account {account_id}, expires_in={expires_in}")
        return {"ok": True, "expires_in": expires_in}
    finally:
        await db.close()


@router.get("/api/settings/auto-refresh")
async def get_auto_refresh() -> dict:
    val = await get_setting("auto_refresh_tokens", "1")
    days = _warning_days(await get_setting(TOKEN_EXPIRY_WARNING_DAYS, "7"))
    return {"auto_refresh": val == "1", "warning_days": days}


@router.put("/api/settings/auto-refresh")
async def set_auto_refresh(data: dict[str, Any]) -> dict:
    if "auto_refresh" in data:
        await set_setting("auto_refresh_tokens", "1" if data.get("auto_refresh") else "0")
    if "warning_days" in data:
        await set_setting(TOKEN_EXPIRY_WARNING_DAYS, str(_warning_days(data.get("warning_days"))))
    return {"ok": True}


@router.get("/api/token-status/accounts")
async def account_token_statuses() -> dict:
    warning_days = _warning_days(await get_setting(TOKEN_EXPIRY_WARNING_DAYS, "7"))
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, token, refresh_token, token_expires_at FROM accounts ORDER BY id"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    now = int(time.time())
    statuses = {}
    for row in rows:
        account = dict(row)
        account["has_refresh_token"] = bool(decrypt_token(account.pop("refresh_token") or ""))
        statuses[str(account["id"])] = await _token_status(account, warning_days, now)
    return {"statuses": statuses}
