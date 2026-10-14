"""device_code — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ
router из app.routes; импортируется ВНИЗУ routes.py (после создания router).
"""
from typing import Any

from app.database import get_db
from app.routes import (
    router,
    encrypt_token, log_action, twitch_oauth,
)
from app.routes import router  # noqa: E402


# ===================== DEVICE CODE FLOW (login без вставки токена) =====================

@router.post("/api/twitch-oauth/start")
async def twitch_oauth_start(data: dict[str, Any] | None = None) -> dict:
    """Начать Device Code Flow. Возвращает user_code и ссылку для активации."""
    if not twitch_oauth.is_configured():
        return {
            "ok": False,
            "error": "TWITCH_CLIENT_ID не задан в .env. Зарегистрируй приложение на dev.twitch.tv/console/apps."
        }
    scopes = (data or {}).get("scopes")
    result = await twitch_oauth.start_device_flow(scopes if isinstance(scopes, list) else None)
    if result.get("ok"):
        twitch_oauth.remember_session(
            result["device_code"], result["user_code"], result["expires_in"]
        )
        await log_action(
            "OAuth: device flow start",
            f"user_code={result['user_code']} scopes={','.join(result.get('scopes', []))}",
        )
    return result


@router.post("/api/twitch-oauth/poll")
async def twitch_oauth_poll(data: dict[str, Any]) -> dict:
    """Один опрос статуса device-flow.

    Если юзер ввёл код — создаём аккаунт (или обновляем существующий по nickname)
    и возвращаем {ok: True, account_id, login}.
    """
    device_code = (data or {}).get("device_code")
    nickname = ((data or {}).get("nickname") or "").strip()
    if not device_code:
        return {"ok": False, "error": "device_code обязателен"}

    twitch_oauth.gc_expired_sessions()
    if not twitch_oauth.is_known_session(device_code):
        return {"ok": False, "error": "unknown_device_session"}

    result = await twitch_oauth.poll_device_token(device_code)

    if not result.get("ok"):
        if result.get("expired") or result.get("denied"):
            twitch_oauth.forget_session(device_code)
        # пробросить статус как есть (pending / slow_down / expired / denied / error)
        return result

    # Token endpoint consumes the device grant; do not permit a second exchange even
    # if validation or the following local DB write fails.
    twitch_oauth.forget_session(device_code)

    access = result["access_token"]
    refresh = result.get("refresh_token", "")
    expires_in = int(result.get("expires_in", 0))

    # Узнаём настоящий login через /validate
    info = await twitch_oauth.fetch_user_info(access)
    if not info.get("ok"):
        return {"ok": False, "error": f"токен получен, но валидация упала: {info.get('error')}"}
    login = info.get("login") or nickname or "twitch_user"
    final_nickname = nickname or login

    # IRC хочет токен с префиксом "oauth:"
    irc_token = access if access.startswith("oauth:") else f"oauth:{access}"

    import time as _t
    expires_at = int(_t.time()) + expires_in if expires_in else 0

    db = await get_db()
    try:
        # ищем существующий аккаунт по nickname (для re-login)
        cur = await db.execute("SELECT id FROM accounts WHERE nickname = ?", (final_nickname,))
        existing = await cur.fetchone()
        if existing:
            account_id = existing["id"]
            await db.execute(
                "UPDATE accounts SET token = ?, refresh_token = ?, token_expires_at = ? WHERE id = ?",
                (encrypt_token(irc_token), encrypt_token(refresh), expires_at, account_id),
            )
            mode = "updated"
        else:
            cur = await db.execute(
                "INSERT INTO accounts (nickname, token, refresh_token, token_expires_at, enabled) VALUES (?,?,?,?,1)",
                (final_nickname, encrypt_token(irc_token), encrypt_token(refresh), expires_at),
            )
            account_id = cur.lastrowid
            mode = "created"
        await db.commit()
    finally:
        await db.close()

    await log_action(
        "OAuth: device flow ok",
        f"login={login} acc_id={account_id} mode={mode} scopes={','.join(info.get('scopes', []))}",
    )
    return {
        "ok": True,
        "account_id": account_id,
        "login": login,
        "nickname": final_nickname,
        "mode": mode,
        "expires_in": expires_in,
        "scopes": info.get("scopes", []),
        "has_refresh": bool(refresh),
    }


@router.post("/api/twitch-oauth/cancel")
async def twitch_oauth_cancel(data: dict[str, Any]) -> dict:
    """Юзер отменил процесс — забываем сессию."""
    code = (data or {}).get("device_code")
    if code:
        twitch_oauth.forget_session(code)
    return {"ok": True}
