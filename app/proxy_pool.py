"""Модуль управления общим пулом прокси (Proxy Pool).

Возможности:
1. Массовое добавление прокси из любых форматов (url, ip:port:user:pass, user:pass@ip:port и др.).
2. Проверка здоровья (ping, connect к Twitch HTTPS, задержка ms, статус 🟢/🟡/🔴).
3. Привязка («столбление») прокси за ботом: 1 бот = 1 прокси.
4. Автоматическая замена (failover) при падении прокси на свободный рабочий из пула.
5. Уведомление владельца, если прокси упал, а свободных в пуле нет.
6. Ручной выбор прокси из свободных прямо в карточке бота.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.parse
from typing import Any

from app.database import get_db

logger = logging.getLogger(__name__)


def normalize_proxy_string(raw: str, default_protocol: str = "http") -> str | None:
    """Нормализует любую строку прокси в стандартный URL (http:// или socks5://).

    Поддерживаемые форматы:
    - http://user:pass@host:port
    - socks5://user:pass@host:port
    - host:port:user:pass
    - user:pass@host:port
    - host:port@user:pass
    - host:port
    """
    try:
        s = str(raw or "").strip().strip("\r\n\t '\"")
        # Отрезаем комментарии (включая инлайн "# коммент")
        if "#" in s:
            s = s.split("#", 1)[0].strip()
        if not s:
            return None

        proto = default_protocol.lower().rstrip(":/")
        if proto not in {"http", "https", "socks5", "socks5h", "socks4"}:
            proto = "http"

        # Если протокол уже указан (например, http://, socks4://, socks5://)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s):
            try:
                parsed = urllib.parse.urlsplit(s)
                scheme = (parsed.scheme or "").lower()
                if scheme in {"http", "https", "socks5", "socks5h", "socks4"}:
                    try:
                        port = parsed.port
                        hostname = parsed.hostname
                    except (ValueError, TypeError):
                        port = None
                        hostname = None
                    if hostname and port and 1 <= port <= 65535:
                        user_info = ""
                        if parsed.username:
                            pw = parsed.password or ""
                            user_info = f"{urllib.parse.quote(parsed.username)}:{urllib.parse.quote(pw)}@"
                        return f"{scheme}://{user_info}{hostname}:{port}"
            except Exception:
                pass
            return None

        # Без протокола: проверяем host:port:user:pass
        parts = s.split(":")
        if len(parts) == 4:
            host, port_str, user, password = parts
            try:
                port = int(port_str)
                if 1 <= port <= 65535 and host.strip():
                    u_enc = urllib.parse.quote(user.strip())
                    p_enc = urllib.parse.quote(password.strip())
                    return f"{proto}://{u_enc}:{p_enc}@{host.strip()}:{port}"
            except (ValueError, TypeError):
                pass

        # Формат user:pass@host:port
        if "@" in s:
            auth_part, net_part = s.split("@", 1)
            if ":" in net_part:
                host, port_str = net_part.split(":", 1)
                try:
                    port = int(port_str)
                    if 1 <= port <= 65535 and host.strip():
                        if ":" in auth_part:
                            u, p = auth_part.split(":", 1)
                            u_enc = urllib.parse.quote(u.strip())
                            p_enc = urllib.parse.quote(p.strip())
                            return f"{proto}://{u_enc}:{p_enc}@{host.strip()}:{port}"
                except (ValueError, TypeError):
                    pass

        # Формат host:port@user:pass
        if "@" in s:
            net_part, auth_part = s.split("@", 1)
            if ":" in net_part:
                host, port_str = net_part.split(":", 1)
                try:
                    port = int(port_str)
                    if 1 <= port <= 65535 and host.strip():
                        if ":" in auth_part:
                            u, p = auth_part.split(":", 1)
                            u_enc = urllib.parse.quote(u.strip())
                            p_enc = urllib.parse.quote(p.strip())
                            return f"{proto}://{u_enc}:{p_enc}@{host.strip()}:{port}"
                except (ValueError, TypeError):
                    pass

        # Простой формат host:port
        if len(parts) == 2:
            host, port_str = parts
            try:
                port = int(port_str)
                if 1 <= port <= 65535 and host.strip():
                    return f"{proto}://{host.strip()}:{port}"
            except (ValueError, TypeError):
                pass

        return None
    except Exception:
        return None


def mask_proxy_url(url: str) -> str:
    """Маскирует пароль в proxy-URL для безопасного отображения."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.username:
            user = parsed.username
            masked = f"{parsed.scheme}://{user}:****@{parsed.hostname}:{parsed.port}"
            return masked
        return url
    except Exception:
        return url


def extract_proxy_identity(url: str) -> tuple[str, int, str] | None:
    """Возвращает канонический идентификатор прокси для поиска повторок.

    Для IPv4/IPv6 адресов ключ: (host, port, '') — так как один IP:порт это один и тот же сервер/выход.
    Для доменных шлюзов с авторизацией (ротируемые прокси типа gate.smartproxy.com:7000):
    (host, port, username) — чтобы отличать разные сессии на одном шлюзе.
    """
    if not url:
        return None
    try:
        norm = normalize_proxy_string(url) or str(url).strip()
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", norm):
            norm = f"http://{norm}"
        parsed = urllib.parse.urlsplit(norm)
        host = (parsed.hostname or "").strip().lower()
        port = parsed.port
        if not host or not port or not (1 <= port <= 65535):
            return None

        is_ip = bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host) or ":" in host)
        user = (parsed.username or "").strip()
        if is_ip:
            # Для чистых IP-адресов дубликатом считается тот же IP-адрес (1 IP = 1 бот на Twitch, независимо от порта)
            return (host, 0, "")
        else:
            # Для доменных имен учитываем пользователя и порт (сессию шлюза)
            return (host, port, user)
    except Exception:
        return None


async def ensure_schema(db=None) -> None:
    """Инициализирует таблицу proxy_pool и настройки пула."""
    close_db = False
    if db is None:
        db = await get_db()
        close_db = True
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proxy_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                label TEXT DEFAULT '',
                assigned_account_id INTEGER,
                status TEXT DEFAULT 'untested',
                latency_ms REAL DEFAULT 0,
                last_error TEXT DEFAULT '',
                last_checked_at REAL DEFAULT 0,
                created_at REAL DEFAULT 0,
                FOREIGN KEY (assigned_account_id) REFERENCES accounts(id) ON DELETE SET NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_proxy_pool_assigned ON proxy_pool(assigned_account_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_proxy_pool_status ON proxy_pool(status)")

        # Глобальные настройки пула в settings
        await db.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('proxy_pool_auto_failover', '1'),
                ('proxy_pool_notify_owner', '1')
        """)
        await db.commit()
    finally:
        if close_db:
            await db.close()


async def add_proxies_to_pool(
    raw_text: str,
    default_protocol: str = "http",
    label: str = "",
) -> dict[str, Any]:
    """Добавляет список прокси в общий пул с парсингом, валидацией и фильтрацией повторок."""
    await ensure_schema()
    # Автоматически разделяем слипшиеся без перевода строки URL (например, http://...:80socks4://...)
    cleaned_text = re.sub(r"([^\s\n])(https?://|socks[45]h?://)", r"\1\n\2", str(raw_text or ""))
    lines = [line.strip() for line in cleaned_text.splitlines() if line.strip()]
    if not lines:
        return {"ok": False, "error": "Нет строк для добавления", "added": 0, "duplicates": 0, "invalid": 0}

    added = 0
    duplicates = 0
    invalid = 0
    now = time.time()

    db = await get_db()
    try:
        # Загружаем существующие URL и идентификаторы прокси из базы для быстрой проверки дубликатов
        cur = await db.execute("SELECT url FROM proxy_pool")
        existing_rows = await cur.fetchall()
        existing_urls = {r["url"] for r in existing_rows}
        existing_identities: set[tuple[str, int, str]] = set()
        for r in existing_rows:
            ident = extract_proxy_identity(r["url"])
            if ident:
                existing_identities.add(ident)

        seen_in_batch_urls: set[str] = set()
        seen_in_batch_identities: set[tuple[str, int, str]] = set()

        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            norm = normalize_proxy_string(s, default_protocol)
            if not norm:
                invalid += 1
                continue

            ident = extract_proxy_identity(norm)

            # Проверка на повторку: в текущей пачке или уже в таблице proxy_pool
            is_dup = (
                norm in existing_urls
                or norm in seen_in_batch_urls
                or bool(ident and (ident in existing_identities or ident in seen_in_batch_identities))
            )
            if is_dup:
                duplicates += 1
                continue

            seen_in_batch_urls.add(norm)
            if ident:
                seen_in_batch_identities.add(ident)

            try:
                await db.execute(
                    "INSERT INTO proxy_pool (url, label, status, created_at) VALUES (?, ?, 'untested', ?)",
                    (norm, label, now),
                )
                added += 1
                existing_urls.add(norm)
                if ident:
                    existing_identities.add(ident)
            except Exception:
                # UNIQUE constraint failed -> дубликат
                duplicates += 1
        await db.commit()
    except Exception as e:
        logger.error("[proxy_pool] Ошибка сохранения прокси: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"Ошибка сохранения: {e}", "added": added, "duplicates": duplicates, "invalid": invalid}
    finally:
        await db.close()

    return {
        "ok": True,
        "added": added,
        "duplicates": duplicates,
        "invalid": invalid,
        "total_lines": len(lines),
    }


async def get_proxy_pool_items() -> list[dict[str, Any]]:
    """Возвращает все элементы пула прокси с информацией о привязанных ботах."""
    await ensure_schema()
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT p.id, p.url, p.label, p.assigned_account_id, p.status, p.latency_ms,
                   p.last_error, p.last_checked_at, p.created_at,
                   a.nickname as assigned_nickname, a.bot_role as assigned_bot_role
            FROM proxy_pool p
            LEFT JOIN accounts a ON p.assigned_account_id = a.id
            ORDER BY p.id ASC
        """)
        rows = await cur.fetchall()
        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "url": r["url"],
                "masked_url": mask_proxy_url(r["url"]),
                "label": r["label"] or "",
                "assigned_account_id": r["assigned_account_id"],
                "assigned_nickname": r["assigned_nickname"] or "",
                "assigned_bot_role": r["assigned_bot_role"] or "",
                "is_assigned": bool(r["assigned_account_id"]),
                "status": r["status"] or "untested",
                "latency_ms": round(float(r["latency_ms"] or 0), 1),
                "last_error": r["last_error"] or "",
                "last_checked_at": r["last_checked_at"] or 0,
                "created_at": r["created_at"] or 0,
            })
        return items
    finally:
        await db.close()


async def check_single_proxy_health(proxy_id: int) -> dict[str, Any]:
    """Проверяет работоспособность конкретного прокси в пуле через HTTPS ping."""
    await ensure_schema()
    db = await get_db()
    try:
        cur = await db.execute("SELECT id, url FROM proxy_pool WHERE id = ?", (proxy_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Прокси не найден"}
        proxy_url = row["url"]
    finally:
        await db.close()

    status = "error"
    latency_ms = 0.0
    last_error = ""

    start_time = time.monotonic()
    try:
        import httpx
        # Проверяем HTTPS соединение через прокси к Twitch endpoint с таймаутом 4.5 сек, игнорируя SSL-ошибки сертификатов
        async with httpx.AsyncClient(proxy=proxy_url, timeout=4.5, verify=False) as client:
            got_response = False
            try:
                resp = await client.get("https://id.twitch.tv/oauth2/validate", timeout=4.0)
                latency_ms = (time.monotonic() - start_time) * 1000.0
                if resp.status_code in {200, 401, 400}:
                    status = "ok" if latency_ms < 1500 else "slow"
                    got_response = True
            except Exception:
                pass

            if not got_response:
                try:
                    resp2 = await client.get("https://httpbin.org/ip", timeout=4.0)
                    latency_ms = (time.monotonic() - start_time) * 1000.0
                    if resp2.status_code == 200:
                        status = "ok" if latency_ms < 1500 else "slow"
                        got_response = True
                    else:
                        status = "error"
                        last_error = f"HTTP {resp2.status_code}"
                except Exception as ex2:
                    status = "error"
                    last_error = str(ex2)[:120]
                    latency_ms = (time.monotonic() - start_time) * 1000.0
    except (httpx.ConnectTimeout, asyncio.TimeoutError):
        status = "error"
        last_error = "Таймаут соединения"
        latency_ms = (time.monotonic() - start_time) * 1000.0
    except Exception as e:
        status = "error"
        last_error = str(e)[:120]
        latency_ms = (time.monotonic() - start_time) * 1000.0

    now = time.time()
    db = await get_db()
    try:
        await db.execute("""
            UPDATE proxy_pool
            SET status = ?, latency_ms = ?, last_error = ?, last_checked_at = ?
            WHERE id = ?
        """, (status, round(latency_ms, 1), last_error, now, proxy_id))
        await db.commit()
    finally:
        await db.close()

    return {
        "ok": True,
        "proxy_id": proxy_id,
        "status": status,
        "latency_ms": round(latency_ms, 1),
        "last_error": last_error,
        "last_checked_at": now,
    }


async def check_all_proxies_pool() -> dict[str, Any]:
    """Параллельно проверяет весь пул прокси с контролем конкурентности."""
    await ensure_schema()
    items = await get_proxy_pool_items()
    if not items:
        return {"ok": True, "total": 0, "results": []}

    sem = asyncio.Semaphore(40)

    async def _safe_check(pid: int):
        async with sem:
            try:
                return await asyncio.wait_for(check_single_proxy_health(pid), timeout=6.0)
            except Exception as ex:
                return {"ok": False, "proxy_id": pid, "status": "error", "error": str(ex)}

    tasks = [_safe_check(item["id"]) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    formatted = []
    for r in results:
        if isinstance(r, dict):
            formatted.append(r)
        else:
            formatted.append({"ok": False, "error": str(r)})

    counts = {
        "ok": sum(1 for r in formatted if r.get("status") == "ok"),
        "slow": sum(1 for r in formatted if r.get("status") == "slow"),
        "error": sum(1 for r in formatted if r.get("status") == "error"),
        "total": len(formatted),
    }
    return {"ok": True, "counts": counts, "total": len(formatted), "results": formatted}


async def claim_proxy_for_bot(account_id: int, proxy_id: int | None = None) -> dict[str, Any]:
    """Столбит прокси за ботом.

    Если proxy_id не задан (автовыбор):
    - Ищет свободный рабочий прокси (`assigned_account_id IS NULL`, status in ('ok', 'slow', 'untested')).
    - Столбит его за account_id.
    - Обновляет accounts.proxy на этот URL.
    """
    await ensure_schema()
    if account_id <= 0:
        return {"ok": False, "error": "Некорректный ID аккаунта"}

    db = await get_db()
    try:
        # Проверяем бота
        cur = await db.execute("SELECT id, nickname, proxy FROM accounts WHERE id = ?", (account_id,))
        acc = await cur.fetchone()
        if not acc:
            return {"ok": False, "error": "Аккаунт не найден"}

        # Если бот уже занимал какой-то прокси в пуле — освобождаем старый
        await db.execute("UPDATE proxy_pool SET assigned_account_id = NULL WHERE assigned_account_id = ?", (account_id,))

        target_row = None
        if proxy_id and proxy_id > 0:
            cur = await db.execute(
                "SELECT id, url, status, assigned_account_id FROM proxy_pool WHERE id = ?",
                (proxy_id,),
            )
            target_row = await cur.fetchone()
            if not target_row:
                return {"ok": False, "error": "Выбранный прокси не найден"}
            if target_row["assigned_account_id"] and target_row["assigned_account_id"] != account_id:
                return {"ok": False, "error": f"Этот прокси уже занят другим ботом (ID {target_row['assigned_account_id']})"}
        else:
            # Автовыбор из свободных: сначала статус 'ok', затем 'slow', затем 'untested'
            cur = await db.execute("""
                SELECT id, url, status FROM proxy_pool
                WHERE assigned_account_id IS NULL AND status IN ('ok', 'slow', 'untested')
                ORDER BY CASE status WHEN 'ok' THEN 1 WHEN 'slow' THEN 2 ELSE 3 END, latency_ms ASC
                LIMIT 1
            """)
            target_row = await cur.fetchone()
            if not target_row:
                # Если с хорошим статусом нет — проверяем есть ли вообще свободный (кроме явных 'error')
                cur = await db.execute("SELECT id, url, status FROM proxy_pool WHERE assigned_account_id IS NULL AND status != 'error' LIMIT 1")
                target_row = await cur.fetchone()

        if not target_row:
            return {"ok": False, "error": "В пуле нет свободных рабочих прокси"}

        chosen_id = target_row["id"]
        chosen_url = target_row["url"]

        # Привязываем прокси в пуле
        await db.execute("UPDATE proxy_pool SET assigned_account_id = ? WHERE id = ?", (account_id, chosen_id))
        # Обновляем аккаунт в таблице accounts
        await db.execute("UPDATE accounts SET proxy = ? WHERE id = ?", (chosen_url, account_id))
        await db.commit()

        # Синхронизируем инстанс запущенного бота в памяти
        try:
            from app.server import bot_manager
            inst = bot_manager.instances.get(account_id)
            if inst:
                inst.proxy = chosen_url
                if getattr(inst, "bot", None) and getattr(inst.bot, "_http", None) and getattr(inst.bot._http, "session", None):
                    try:
                        await inst.bot._http.session.close()
                    except Exception:
                        pass
        except Exception as be:
            logger.debug("[proxy_pool] Could not sync running bot instance proxy: %s", be)

        logger.info("[proxy_pool] Бот %s (id=%d) застолбил прокси id=%d (%s)",
                    acc["nickname"], account_id, chosen_id, mask_proxy_url(chosen_url))

        return {
            "ok": True,
            "account_id": account_id,
            "nickname": acc["nickname"],
            "proxy_id": chosen_id,
            "proxy_url": chosen_url,
            "masked_url": mask_proxy_url(chosen_url),
        }
    finally:
        await db.close()


async def release_proxy_for_bot(account_id: int) -> dict[str, Any]:
    """Освобождает прокси, застолбленный за ботом (возвращает прокси в свободный пул)."""
    await ensure_schema()
    if account_id <= 0:
        return {"ok": False, "error": "Некорректный ID аккаунта"}

    db = await get_db()
    try:
        await db.execute("UPDATE proxy_pool SET assigned_account_id = NULL WHERE assigned_account_id = ?", (account_id,))
        await db.execute("UPDATE accounts SET proxy = '' WHERE id = ?", (account_id,))
        await db.commit()

        # Синхронизируем инстанс запущенного бота в памяти
        try:
            from app.server import bot_manager
            inst = bot_manager.instances.get(account_id)
            if inst:
                inst.proxy = ""
                if getattr(inst, "bot", None) and getattr(inst.bot, "_http", None) and getattr(inst.bot._http, "session", None):
                    try:
                        await inst.bot._http.session.close()
                    except Exception:
                        pass
        except Exception as be:
            logger.debug("[proxy_pool] Could not sync running bot instance proxy: %s", be)

        return {"ok": True, "account_id": account_id}
    finally:
        await db.close()


async def failover_bot_proxy(account_id: int, reason: str = "") -> dict[str, Any]:
    """Автоматическая замена упавшего прокси бота на свободный рабочий из пула.

    1. Находит текущий прокси бота в пуле и помечает его ошибкой ('error').
    2. Освобождает его.
    3. Столбит следующий рабочий прокси из свободных.
    4. Если бота нет или свободных прокси нет — возвращает статус и отправляет предупреждение.
    """
    await ensure_schema()
    db = await get_db()
    bot_nick = ""
    old_proxy_url = ""
    try:
        cur = await db.execute("SELECT nickname, proxy FROM accounts WHERE id = ?", (account_id,))
        acc = await cur.fetchone()
        if not acc:
            return {"ok": False, "error": "Бот не найден"}
        bot_nick = acc["nickname"]
        old_proxy_url = acc["proxy"] or ""

        # Если старый прокси был в пуле, помечаем его как 'error' и отвязываем
        if old_proxy_url:
            await db.execute("""
                UPDATE proxy_pool
                SET status = 'error', last_error = ?, assigned_account_id = NULL
                WHERE url = ? OR assigned_account_id = ?
            """, (reason or "Failover: connection dropped", old_proxy_url, account_id))
            await db.commit()
    finally:
        await db.close()

    # Пробуем взять новый из свободных
    claim_res = await claim_proxy_for_bot(account_id)
    if claim_res.get("ok"):
        new_masked = claim_res["masked_url"]
        logger.warning(
            "[proxy_pool] 🔄 Авто-замена прокси для бота %s: старый [%s] упал -> выдан новый [%s]",
            bot_nick, mask_proxy_url(old_proxy_url), new_masked,
        )
        return {
            "ok": True,
            "account_id": account_id,
            "nickname": bot_nick,
            "old_proxy": mask_proxy_url(old_proxy_url),
            "new_proxy": new_masked,
            "new_proxy_url": claim_res.get("proxy_url", ""),
            "message": f"Прокси для {bot_nick} успешно заменен на {new_masked}",
        }
    else:
        err = claim_res.get("error", "Нет свободных прокси")
        logger.error(
            "[proxy_pool] ⚠️ Не удалось заменить прокси для бота %s: %s!",
            bot_nick, err,
        )
        return {
            "ok": False,
            "account_id": account_id,
            "nickname": bot_nick,
            "error": err,
            "message": f"Прокси бота {bot_nick} упал, но свободных прокси в пуле нет! Пополните пул.",
        }


async def delete_proxy_from_pool(proxy_id: int) -> bool:
    """Удаляет прокси из пула. Если за ним был закреплен бот — очищает accounts.proxy."""
    await ensure_schema()
    db = await get_db()
    try:
        cur = await db.execute("SELECT assigned_account_id FROM proxy_pool WHERE id = ?", (proxy_id,))
        row = await cur.fetchone()
        if row and row["assigned_account_id"]:
            await db.execute("UPDATE accounts SET proxy = '' WHERE id = ?", (row["assigned_account_id"],))
        await db.execute("DELETE FROM proxy_pool WHERE id = ?", (proxy_id,))
        await db.commit()
        return True
    finally:
        await db.close()


async def clean_dead_proxies_from_pool() -> int:
    """Удаляет из пула все прокси со статусом 'error'."""
    await ensure_schema()
    db = await get_db()
    try:
        cur = await db.execute("SELECT id, assigned_account_id FROM proxy_pool WHERE status = 'error'")
        dead = await cur.fetchall()
        if not dead:
            return 0
        dead_ids = [d["id"] for d in dead]
        assigned_aids = [d["assigned_account_id"] for d in dead if d["assigned_account_id"]]
        if assigned_aids:
            p_aids = ",".join("?" for _ in assigned_aids)
            await db.execute(f"UPDATE accounts SET proxy = '' WHERE id IN ({p_aids})", assigned_aids)

        placeholders = ",".join("?" for _ in dead_ids)
        await db.execute(f"DELETE FROM proxy_pool WHERE id IN ({placeholders})", dead_ids)
        await db.commit()
        return len(dead_ids)
    finally:
        await db.close()


async def clean_slow_proxies_from_pool(max_ping_ms: float = 2000.0, only_unassigned: bool = False) -> int:
    """Удаляет из пула все прокси с задержкой выше max_ping_ms (или со статусом 'error').

    Если only_unassigned=True (для фонового воркера): удаляет только свободные адреса,
    не привязанные к ботам (assigned_account_id IS NULL), гарантируя, что активный бот
    не останется без прокси посреди стрима.
    Для привязанных ботов при наличии замены вызывается failover_bot_proxy(), а не простое обнуление.
    """
    await ensure_schema()
    db = await get_db()
    try:
        where_cond = "(latency_ms >= ? OR status = 'error')"
        params: list[Any] = [max_ping_ms]
        if only_unassigned:
            where_cond += " AND (assigned_account_id IS NULL OR assigned_account_id = 0)"

        cur = await db.execute(f"""
            SELECT id, assigned_account_id FROM proxy_pool
            WHERE {where_cond}
        """, params)
        slow = await cur.fetchall()
        if not slow:
            return 0
        slow_ids = [d["id"] for d in slow]
        assigned_aids = [d["assigned_account_id"] for d in slow if d["assigned_account_id"]]

        # Если удаляются привязанные прокси — пытаемся переключить бота на здоровый прокси через failover
        if assigned_aids:
            for aid in assigned_aids:
                try:
                    fo = await failover_bot_proxy(aid, reason="Удаление медленного прокси")
                    if not fo.get("ok"):
                        await db.execute("UPDATE accounts SET proxy = '' WHERE id = ?", (aid,))
                except Exception:
                    await db.execute("UPDATE accounts SET proxy = '' WHERE id = ?", (aid,))

        placeholders = ",".join("?" for _ in slow_ids)
        await db.execute(f"DELETE FROM proxy_pool WHERE id IN ({placeholders})", slow_ids)
        await db.commit()
        return len(slow_ids)
    finally:
        await db.close()


async def clean_duplicate_proxies_from_pool() -> dict[str, int]:
    """Находит и удаляет повторяющиеся прокси из пула (с одинаковым host:port или идентичным URL).

    При обнаружении дубликатов сохраняется один наилучший:
    1. Прокси, привязанный к боту (assigned_account_id), сохраняется в первую очередь.
    2. Статус здоровья: 'ok' > 'slow' > 'untested' > 'error'.
    3. Наименьшая задержка (latency_ms > 0).
    4. Наименьший id (добавлен раньше).

    Возвращает dict: {'deleted': int, 'unique_remaining': int}.
    """
    await ensure_schema()
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT id, url, status, latency_ms, assigned_account_id
            FROM proxy_pool
            ORDER BY id ASC
        """)
        rows = await cur.fetchall()
        if not rows:
            return {"deleted": 0, "unique_remaining": 0}

        groups: dict[Any, list[dict[str, Any]]] = {}
        for r in rows:
            u = r["url"]
            ident = extract_proxy_identity(u)
            key = ident if ident else u.strip().lower()
            groups.setdefault(key, []).append(dict(r))

        deleted_ids: list[int] = []

        def _proxy_score(item: dict[str, Any]) -> tuple[int, int, float, int]:
            is_assigned = 1 if item.get("assigned_account_id") else 0
            status = str(item.get("status") or "")
            status_priority = {"ok": 4, "slow": 3, "untested": 2, "error": 1}.get(status, 0)
            lat = float(item.get("latency_ms") or 0.0)
            lat_score = -lat if lat > 0 else -999999.0
            return (is_assigned, status_priority, lat_score, -int(item.get("id") or 0))

        for key, items in groups.items():
            if len(items) <= 1:
                continue

            items.sort(key=_proxy_score, reverse=True)
            keeper = items[0]
            keeper_assigned = keeper.get("assigned_account_id")

            for dup in items[1:]:
                dup_id = dup["id"]
                dup_assigned = dup.get("assigned_account_id")
                # Если дубликат привязан к другому боту - не удаляем его, чтобы не сломать бота
                if dup_assigned and dup_assigned != keeper_assigned:
                    continue
                deleted_ids.append(dup_id)

        if deleted_ids:
            placeholders = ",".join("?" for _ in deleted_ids)
            await db.execute(f"DELETE FROM proxy_pool WHERE id IN ({placeholders})", deleted_ids)
            await db.commit()

        cur2 = await db.execute("SELECT COUNT(*) as cnt FROM proxy_pool")
        row2 = await cur2.fetchone()
        remaining = int(row2["cnt"]) if row2 else 0

        return {"deleted": len(deleted_ids), "unique_remaining": remaining}
    finally:
        await db.close()


async def get_proxy_pool_settings() -> dict[str, Any]:
    """Возвращает настройки авто-замены, авто-чистки и уведомлений."""
    await ensure_schema()
    db = await get_db()
    try:
        cur = await db.execute("SELECT key, value FROM settings WHERE key IN ('proxy_pool_auto_failover', 'proxy_pool_notify_owner', 'proxy_pool_auto_clean')")
        rows = dict(await cur.fetchall())
        return {
            "auto_failover": rows.get("proxy_pool_auto_failover", "1") == "1",
            "notify_owner": rows.get("proxy_pool_notify_owner", "1") == "1",
            "auto_clean": rows.get("proxy_pool_auto_clean", "1") == "1",
        }
    finally:
        await db.close()


async def save_proxy_pool_settings(auto_failover: bool, notify_owner: bool, auto_clean: bool = True) -> dict[str, Any]:
    """Сохраняет настройки авто-замены, авто-чистки и уведомлений."""
    await ensure_schema()
    db = await get_db()
    try:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('proxy_pool_auto_failover', ?)", ("1" if auto_failover else "0",))
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('proxy_pool_notify_owner', ?)", ("1" if notify_owner else "0",))
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('proxy_pool_auto_clean', ?)", ("1" if auto_clean else "0",))
        await db.commit()
        return {"ok": True, "auto_failover": auto_failover, "notify_owner": notify_owner, "auto_clean": auto_clean}
    finally:
        await db.close()


async def proxy_pool_clean_loop(interval: float = 900.0) -> None:
    """Фоновый воркер: периодически проверяет свободные прокси и тихо удаляет >2000ms и ошибки."""
    # Ждём 60 секунд после старта сервера перед первой фоновой проверкой
    await asyncio.sleep(60.0)
    while True:
        try:
            settings = await get_proxy_pool_settings()
            if settings.get("auto_clean", True):
                logger.debug("[proxy_pool] Запуск периодической фоновой проверки свободных прокси...")
                await check_all_proxies_pool()
                deleted = await clean_slow_proxies_from_pool(2000.0, only_unassigned=True)
                if deleted > 0:
                    logger.info("[proxy_pool] 🧹 Фоновая авто-чистка: удалено %d медленных/упавших прокси", deleted)
                    try:
                        from app.routes import log_action
                        await log_action("Фоновая авто-чистка пула", f"Удалено {deleted} медленных (>2000ms) или ошибочных прокси")
                    except Exception:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("[proxy_pool] Ошибка в proxy_pool_clean_loop: %s", exc)
        await asyncio.sleep(interval)
