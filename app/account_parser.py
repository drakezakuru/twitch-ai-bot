"""Универсальный парсер строк аккаунтов, кук и токенов Twitch.

Поддерживает форматы:
1. Магазинный: `login:password:token` или `login:password:cookie` или `login:pass:mail:mailpass:token`
2. Чистые куки: `auth-token=xxxx; unique_id=yyyy; ...`
3. JSON Cookie (Cookie-Editor, EditThisCookie): `[{"name": "auth-token", "value": "xxxx"}, ...]`
4. Токен с прокси: `login:pass:token:ip:port:user:pass` или `login:pass:token:socks5://...`
5. Чистый токен: `oauth:xxxx` или `xxxx`
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class ParsedAccount:
    token: str
    nickname_hint: str = ""
    proxy: str = ""
    raw: str = ""


_AUTH_TOKEN_COOKIE_RE = re.compile(r'(?:^|[;\s])auth-token=([a-zA-Z0-9_-]+)', re.IGNORECASE)
_OAUTH_PREFIX_RE = re.compile(r'^oauth:([a-zA-Z0-9_-]+)$', re.IGNORECASE)
_PLAIN_TOKEN_RE = re.compile(r'^[a-zA-Z0-9_-]{24,45}$')
_TWITCH_LOGIN_RE = re.compile(r'^[a-zA-Z0-9_]{3,25}$')
_IPV4_PORT_USER_PASS_RE = re.compile(r'^(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5}):([^:]+):([^:]+)$')
_IPV4_PORT_RE = re.compile(r'^(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})$')


def parse_cookie_json(text: str) -> list[ParsedAccount]:
    """Парсит JSON-экспорт кук (Cookie-Editor, EditThisCookie и др.)."""
    try:
        data = json.loads(text.strip())
    except Exception:
        return []

    results: list[ParsedAccount] = []
    if isinstance(data, list):
        token_found = None
        for item in data:
            if isinstance(item, dict):
                name = str(item.get("name") or "").lower()
                if name == "auth-token" and item.get("value"):
                    token_found = str(item["value"]).strip()
                    break
                if "token" in item:
                    tok = str(item["token"]).strip()
                    results.append(ParsedAccount(
                        token=tok[len("oauth:"):] if tok.startswith("oauth:") else tok,
                        nickname_hint=str(item.get("login") or item.get("nickname") or ""),
                        proxy=str(item.get("proxy") or ""),
                        raw=text[:100],
                    ))
        if token_found:
            results.append(ParsedAccount(token=token_found, raw=text[:100]))
    elif isinstance(data, dict):
        if "auth-token" in data:
            results.append(ParsedAccount(token=str(data["auth-token"]).strip(), raw=text[:100]))
        elif "token" in data:
            tok = str(data["token"]).strip()
            results.append(ParsedAccount(
                token=tok[len("oauth:"):] if tok.startswith("oauth:") else tok,
                nickname_hint=str(data.get("login") or data.get("nickname") or ""),
                proxy=str(data.get("proxy") or ""),
                raw=text[:100],
            ))
    return results


def parse_account_line(line: str) -> ParsedAccount | None:
    """Парсит одну строку любого поддерживаемого формата."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Проверка на JSON
    if (line.startswith("[") and line.endswith("]")) or (line.startswith("{") and line.endswith("}")):
        json_res = parse_cookie_json(line)
        if json_res:
            return json_res[0]

    # Вариант 1: Кука auth-token в строке
    cookie_match = _AUTH_TOKEN_COOKIE_RE.search(line)
    if cookie_match:
        token = cookie_match.group(1).strip()
        prefix = line[:cookie_match.start()].strip(" :|;\t")
        nickname_hint = ""
        if prefix:
            parts = [p.strip() for p in re.split(r'[:|;]', prefix) if p.strip()]
            if parts and _TWITCH_LOGIN_RE.match(parts[0]):
                nickname_hint = parts[0]
        return ParsedAccount(token=token, nickname_hint=nickname_hint, raw=line)

    # Вариант 2: Строка с разделителями (логин:пароль:токен или с прокси)
    proxy_part = ""
    proto_proxy_match = re.search(r'((?:https?|socks[45]?)://[^\s|]+)', line, re.IGNORECASE)
    if proto_proxy_match:
        proxy_part = proto_proxy_match.group(1).rstrip(" ;,\t")
        prefix = line[:proto_proxy_match.start()].rstrip(" :|;\t")
        suffix = line[proto_proxy_match.end():].lstrip(" :|;\t")
        line_clean = f"{prefix}:{suffix}" if prefix and suffix else (prefix or suffix)
    else:
        line_clean = line

    delimiter = "|" if "|" in line_clean and line_clean.count("|") >= 2 else (":" if ":" in line_clean else "\t")
    parts = [p.strip() for p in line_clean.split(delimiter) if p.strip()]

    # Проверяем на формат IP:PORT:USER:PASS в конце parts
    if len(parts) >= 6 and not proxy_part:
        candidate_ip_port = f"{parts[-4]}:{parts[-3]}:{parts[-2]}:{parts[-1]}"
        m_proxy = _IPV4_PORT_USER_PASS_RE.match(candidate_ip_port)
        if m_proxy:
            proxy_part = f"http://{m_proxy.group(3)}:{m_proxy.group(4)}@{m_proxy.group(1)}:{m_proxy.group(2)}"
            parts = parts[:-4]
    elif len(parts) >= 4 and not proxy_part:
        candidate_ip_port = f"{parts[-2]}:{parts[-1]}"
        m_proxy = _IPV4_PORT_RE.match(candidate_ip_port)
        if m_proxy:
            proxy_part = f"http://{m_proxy.group(1)}:{m_proxy.group(2)}"
            parts = parts[:-2]

    token_found = ""
    nickname_hint = ""

    # Проход 1: явный oauth:xxxx
    for p in parts:
        m = _OAUTH_PREFIX_RE.match(p)
        if m:
            token_found = m.group(1)
            break

    # Проход 2: auth-token=xxxx
    if not token_found:
        for p in parts:
            m = _AUTH_TOKEN_COOKIE_RE.search(p)
            if m:
                token_found = m.group(1)
                break

    # Проход 3: подходящая по длине строка токена (24-45 символов, без @ и точек)
    if not token_found:
        for p in reversed(parts):
            if "@" in p or "." in p:
                continue
            if _PLAIN_TOKEN_RE.match(p):
                token_found = p
                break

    # Проход 4: эвристика для магазинных строк (login:pass:token или login:token)
    if not token_found and len(parts) >= 2:
        for p in reversed(parts[1:]):
            if "@" not in p and "." not in p and len(p) >= 4 and not p.isdigit():
                token_found = p
                break

    # Если токен не найден, но частей 1 — возможно это токен любой длины
    if not token_found and len(parts) == 1:
        raw_p = parts[0]
        token_found = raw_p[len("oauth:"):] if raw_p.startswith("oauth:") else raw_p

    if not token_found:
        return None

    if len(parts) > 1 and parts[0] != token_found:
        candidate_nick = parts[0]
        if _TWITCH_LOGIN_RE.match(candidate_nick) and "@" not in candidate_nick:
            nickname_hint = candidate_nick

    return ParsedAccount(
        token=token_found,
        nickname_hint=nickname_hint,
        proxy=proxy_part,
        raw=line,
    )


def parse_accounts_input(text_or_lines: str | list[str]) -> list[ParsedAccount]:
    """Парсит весь входной текст или список строк."""
    if isinstance(text_or_lines, list):
        lines = [str(x or "").strip() for x in text_or_lines if str(x or "").strip()]
        full_text = "\n".join(lines)
    else:
        full_text = str(text_or_lines or "").strip()

    if not full_text:
        return []

    # Если весь текст — это один большой JSON-массив кук
    if full_text.startswith("[") and full_text.endswith("]"):
        json_res = parse_cookie_json(full_text)
        if json_res:
            return json_res

    results: list[ParsedAccount] = []
    for line in full_text.splitlines():
        parsed = parse_account_line(line)
        if parsed and parsed.token:
            results.append(parsed)

    return results
