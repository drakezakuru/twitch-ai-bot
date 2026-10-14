"""Token storage and local/network access policy for the owner panel.

The desktop panel is passwordless on loopback. A non-loopback deployment needs
both HTTP Basic credentials and encrypted token storage.

Network mode is configured through `.env`:
    PANEL_AUTH_USER=admin
    PANEL_AUTH_PASS=secret
    TOKEN_ENCRYPTION_KEY=<fernet key, 44 chars>

Сгенерировать ключ:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import ipaddress
import logging
import os
import secrets
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket, status

logger = logging.getLogger(__name__)


# ============== ENCRYPTION ==============

_FERNET: Any = None
_FERNET_TRIED = False
_PLAINTEXT_WARNING_EMITTED = False


class CredentialStoragePolicyError(RuntimeError):
    """Raised when credentials would be persisted without an approved storage mode."""


def _get_fernet() -> Any:
    """Возвращает Fernet-объект если ключ задан и cryptography установлен, иначе None."""
    global _FERNET, _FERNET_TRIED
    if _FERNET_TRIED:
        return _FERNET
    _FERNET_TRIED = True
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("TOKEN_ENCRYPTION_KEY задан, но cryptography не установлен. "
                       "Запустите: pip install cryptography")
        return None
    try:
        _FERNET = Fernet(key.encode() if isinstance(key, str) else key)
        logger.info("Шифрование токенов: ВКЛЮЧЕНО")
    except Exception as exc:
        logger.error("Невалидный TOKEN_ENCRYPTION_KEY: %s. Сгенерируй новый: "
                     'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"',
                     exc)
        _FERNET = None
    return _FERNET


def is_encryption_enabled() -> bool:
    return _get_fernet() is not None


_ENC_PREFIX = "enc::"


def is_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address((host or "").strip()).is_loopback
    except ValueError:
        return (host or "").strip().lower() == "localhost"


def credential_storage_mode() -> str:
    """Return encrypted, local_plaintext, qa_plaintext, or blocked."""
    if is_encryption_enabled():
        return "encrypted"
    if _truthy_env("QA_PROFILE"):
        return "qa_plaintext"
    if is_loopback_host(os.getenv("PANEL_BIND_HOST", "")):
        return "local_plaintext"
    return "blocked"


def ensure_credential_storage_policy() -> None:
    mode = credential_storage_mode()
    if mode == "blocked":
        raise CredentialStoragePolicyError(
            "TOKEN_ENCRYPTION_KEY не настроен: незашифрованные credentials разрешены "
            "только при loopback-only запуске через run.py"
        )


def _store_plaintext_or_raise(plaintext: str) -> str:
    global _PLAINTEXT_WARNING_EMITTED
    ensure_credential_storage_policy()
    if not _PLAINTEXT_WARNING_EMITTED and credential_storage_mode() == "local_plaintext":
        logger.warning(
            "ВНИМАНИЕ: credentials сохраняются в БД БЕЗ ШИФРОВАНИЯ; "
            "панель ограничена loopback-интерфейсом. Настройте TOKEN_ENCRYPTION_KEY."
        )
        _PLAINTEXT_WARNING_EMITTED = True
    return plaintext


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token or allow plaintext only for loopback/QA runtimes."""
    if not plaintext:
        return plaintext
    if plaintext.startswith(_ENC_PREFIX):
        return plaintext  # уже зашифрован
    f = _get_fernet()
    if f is None:
        return _store_plaintext_or_raise(plaintext)
    try:
        encrypted = f.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return _ENC_PREFIX + encrypted
    except Exception as exc:
        logger.error("Ошибка шифрования токена: %s", exc)
        return _store_plaintext_or_raise(plaintext)


def decrypt_token(stored: str) -> str:
    """Дешифрует токен из БД. Если он не зашифрован — возвращает как есть."""
    if not stored:
        return stored
    if not stored.startswith(_ENC_PREFIX):
        return stored
    f = _get_fernet()
    if f is None:
        # Ключ не задан, но в БД есть зашифрованные токены — авария
        logger.error("В БД есть зашифрованные токены, но TOKEN_ENCRYPTION_KEY не задан!")
        return ""
    try:
        return f.decrypt(stored[len(_ENC_PREFIX):].encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logger.error("Ошибка дешифровки токена: %s", exc)
        return ""


def mask_token(token: str) -> str:
    """Возвращает замаскированный токен для отображения в UI."""
    if not token:
        return ""
    clean = token.replace("oauth:", "")
    if len(clean) <= 8:
        return "***"
    return clean[:4] + "..." + clean[-4:]


# ============== AUTH (HTTP Basic) ==============

def is_auth_enabled() -> bool:
    return bool(os.getenv("PANEL_AUTH_USER", "").strip()) and bool(os.getenv("PANEL_AUTH_PASS", "").strip())


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def panel_access_mode() -> str:
    """Return qa_no_auth, local_no_auth, network_basic, or blocked."""
    if _truthy_env("QA_PROFILE"):
        return "qa_no_auth"
    bind_host = os.getenv("PANEL_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if is_loopback_host(bind_host):
        return "local_no_auth"
    if is_auth_enabled() and is_encryption_enabled():
        return "network_basic"
    return "blocked"


def require_loopback_client(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if not is_loopback_host(client_host):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Loopback client required",
        )


def require_same_origin_request(request: Request) -> None:
    """Reject browser cross-site mutations while preserving local CLI compatibility."""
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return
    host = request.headers.get("host", "").strip().lower()
    try:
        parsed = urlsplit(source)
    except ValueError:
        parsed = None
    if not parsed or parsed.scheme not in {"http", "https"} or not host or parsed.netloc.lower() != host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Same-origin request required",
        )


def _allows_passwordless_client(client_host: str) -> bool:
    mode = panel_access_mode()
    if mode == "qa_no_auth":
        return True
    return mode == "local_no_auth" and is_loopback_host(client_host)


def _check_basic_auth(request: Request) -> bool:
    """Проверяет HTTP Basic заголовок. Возвращает True если авторизован."""
    user = os.getenv("PANEL_AUTH_USER", "").strip()
    pwd = os.getenv("PANEL_AUTH_PASS", "").strip()
    if not user or not pwd:
        return False

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False
    try:
        import base64
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        if ":" not in decoded:
            return False
        u, p = decoded.split(":", 1)
        return secrets.compare_digest(u, user) and secrets.compare_digest(p, pwd)
    except Exception:
        return False


async def auth_dependency(request: Request) -> None:
    """Allow the desktop panel locally; require Basic auth only in network mode."""
    client_host = request.client.host if request.client else ""
    if _allows_passwordless_client(client_host):
        return
    mode = panel_access_mode()
    if mode == "network_basic" and _check_basic_auth(request):
        return
    if mode == "network_basic":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Twitch AI Bot Panel"'},
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Panel is available from localhost only",
    )


def check_ws_auth(headers: dict, client_host: str = "") -> bool:
    """Use the same local/network access mode as HTTP routes."""
    if _allows_passwordless_client(client_host):
        return True
    if panel_access_mode() != "network_basic":
        return False
    user = os.getenv("PANEL_AUTH_USER", "").strip()
    pwd = os.getenv("PANEL_AUTH_PASS", "").strip()
    auth_header = headers.get("authorization", "") or headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False
    try:
        import base64
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        if ":" not in decoded:
            return False
        u, p = decoded.split(":", 1)
        return secrets.compare_digest(u, user) and secrets.compare_digest(p, pwd)
    except Exception:
        return False
