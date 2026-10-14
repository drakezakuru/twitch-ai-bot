"""MODERATION_PLAN §1-§3.4: движок модерации чата и антиспам зрителей.

Ядро (§1):
  - ``check_message`` — проверка входящего сообщения по кастомным правилам
    (таблица ``moderation_rules``) и встроенным словарям (``moderation_dicts/``).
  - Режимы per-account: ``off`` / ``log_only`` / ``replace`` / ``full``;
    per-channel override — ключ ``moderation_mode`` в ``channel_overrides``.
  - Порог severity: 1-2 → replace, 3 → block, 4-5 → block (+timeout в full).
  - Угрозы (threat 4-5) пишутся в журнал всегда, даже в режиме off.

Антиспам зрителей (§2): caps / links / repeat / emote-spam / copypasta —
чисто эвристический, по умолчанию только лог; роли из белого списка exempt.

Интеграции (§3): ``check_outgoing`` для ответов бота и ручных отправок;
``maybe_timeout`` — реальный таймаут через Helix (§3.4) с fallback до block.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from app import database
from app.anti_detection import compute_self_similarity

logger = logging.getLogger(__name__)

MODES = ("off", "log_only", "replace", "full", "shadow")
CATEGORIES = ("custom", "insult", "hate", "threat", "sexual", "spam", "links", "caps", "repeat")
RULE_ACTIONS = ("replace", "block", "timeout", "log")
# Политика «кто таймаутит» (решение владельца 28.08.2026):
#   auto  — бот таймаутит сам (как раньше);
#   ask   — бот спрашивает владельца (всплывашка Да/Нет в панели);
#   learn — спрашивает и учится: после LEARN_APPROVE_THRESHOLD «Да» подряд
#           (без «Нет») по категории бот начинает таймаутить сам.
POLICIES = ("auto", "ask", "learn")
LEARN_APPROVE_THRESHOLD = 3
LEARN_REJECT_RATIO = 2  # авто только если approved >= rejected * 2

# Q01/Q26 (DEC-OWNER-014): наказания и защищённые зрители.
DEFAULT_TIMEOUT_SEC = 600       # прежний таймаут «по тяжести», когда длительность не задана
PUNISH_ACTIONS = ("timeout", "ban")
# От «бана навсегда» защищены автоматически модераторы/редакторы и сам стример.
# VIP и подписчики НЕ защищены автоматически — только если владелец вписал их в список канала.
PROTECTED_ROLES = frozenset({
    "streamer", "broadcaster", "mod", "moderator", "editor", "staff", "admin",
})
# Статусы вызова maybe_punish: наказание применено / отложено до решения владельца /
# не применено (выключен рубильник, нет токена, не тот вердикт).
PUNISH_APPLIED = "applied"
PUNISH_DEFERRED = "deferred"
PUNISH_SKIPPED = "skipped"

DICTS_DIR = Path(__file__).resolve().parent / "moderation_dicts"
REPEAT_WINDOW_SEC = 60.0
COPYPASTA_WINDOW = 50          # последних сообщений канала для self-similarity
COPYPASTA_THRESHOLD = 0.85
COPYPASTA_MIN_LEN = 20
SETTINGS_TTL = 5.0             # кэш настроек/правил в секундах

# §2: ссылки (переиспользуем подход anti_spam.LINK_RE)
LINK_RE = re.compile(r"(https?://|www\.|\.com|\.ru|\.net|\.io|\.tv|\.gg|\.org)\S*", re.IGNORECASE)
_EMOJI_RE = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF" "\U00002190-\U000021FF" "]+"
)


# ─────────────────────────── Встроенные словари ───────────────────────────

@dataclass(frozen=True)
class DictRule:
    lang: str
    category: str
    pattern: str
    severity: int
    regex: re.Pattern


def _normalize(text: str) -> str:
    """Нормализация перед матчем: lowercase, ё→е, убрать zero-width."""
    text = (text or "").lower().replace("ё", "е")
    return text.replace("\u200b", "").replace("\ufeff", "")


def _compile_pattern(pattern: str) -> re.Pattern | None:
    """Слово → префиксный матч от начала слова (?<!\\w)стем (ловит окончания);
    're:...' → пользовательский regex как есть."""
    try:
        if pattern.startswith("re:"):
            return re.compile(pattern[3:], re.IGNORECASE | re.UNICODE)
        return re.compile(r"(?<!\w)" + re.escape(pattern), re.IGNORECASE | re.UNICODE)
    except re.error as exc:
        logger.warning("moderation: bad pattern %r: %s", pattern, exc)
        return None


def load_builtin_dicts() -> list[DictRule]:
    """Читает app/moderation_dicts/{ru,en,ua}.txt — формат 'category|severity|pattern'."""
    rules: list[DictRule] = []
    if not DICTS_DIR.is_dir():
        return rules
    for path in sorted(DICTS_DIR.glob("*.txt")):
        lang = path.stem
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            logger.warning("moderation: не удалось прочитать %s: %s", path.name, exc)
            continue
        for lineno, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) != 3:
                logger.warning("moderation_dicts/%s:%d: плохая строка: %r", path.name, lineno, line)
                continue
            category, severity_s, pattern = (p.strip() for p in parts)
            if category not in CATEGORIES:
                logger.warning("moderation_dicts/%s:%d: неизвестная категория %r", path.name, lineno, category)
                continue
            try:
                severity = max(1, min(5, int(severity_s)))
            except ValueError:
                logger.warning("moderation_dicts/%s:%d: плохая severity %r", path.name, lineno, severity_s)
                continue
            regex = _compile_pattern(_normalize(pattern))
            if regex is None:
                continue
            rules.append(DictRule(lang, category, pattern, severity, regex))
    return rules


_BUILTIN: list[DictRule] | None = None


def builtin_rules() -> list[DictRule]:
    global _BUILTIN
    if _BUILTIN is None:
        _BUILTIN = load_builtin_dicts()
    return _BUILTIN

# ─────────────────────────── Вердикты ───────────────────────────

@dataclass
class Verdict:
    """Итог проверки сообщения одним правилом.

    ``action``      — что делать сейчас с учётом режима (replace/block/timeout/ban/log).
    ``rule_action`` — что предписывало правило (до применения режима).
    ``masked_text`` — заполнено для replace-вердиктов: текст с маскировкой совпадений.
    ``action_ext``  — явное действие из правила (Q01): '' = лестница по severity.
    ``duration_sec``— длительность таймаута для action_ext 'timeout_*'; иначе None.
    """
    category: str
    action: str
    severity: int
    rule_id: int | None = None
    rule_name: str = ""
    rule_action: str = ""
    match: str = ""
    masked_text: str | None = None
    action_ext: str = ""
    duration_sec: int | None = None
    is_shadow: bool = False

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "action": self.action,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "rule_action": self.rule_action,
            "match": self.match,
            "masked_text": self.masked_text,
            "action_ext": self.action_ext,
            "duration_sec": self.duration_sec,
            "is_shadow": self.is_shadow,
        }


def severity_to_action(severity: int) -> str:
    """План §1: 1-2 = replace, 3 = block, 4-5 = block (+ timeout при full)."""
    if severity <= 2:
        return "replace"
    return "block"


# ─────────────── Q01: конкретное действие правила (action_ext) ───────────────
#
# NULL/'' = «по тяжести» — прежнее поведение (action + severity_to_action).
# Значения хранятся строками, потому что у колонки action CHECK-ограничение и 'ban'
# туда не добавить; действие-переопределение живёт в отдельной колонке action_ext.
ACTION_EXT_TIMEOUTS = {
    "timeout_600": 600,          # 10 минут
    "timeout_3600": 3600,        # 1 час
    "timeout_86400": 86400,      # 1 день
    "timeout_604800": 604800,    # 1 неделя
    "timeout_1209600": 1209600,  # 2 недели — потолок Twitch (BAN_MAX_DURATION)
}

ACTION_EXT_CHOICES: dict[str, tuple[str, int | None]] = {
    "": ("auto", None),
    "auto": ("auto", None),
    "mask": ("replace", None),
    "block": ("block", None),
    "ban": ("ban", None),
    **{key: ("timeout", seconds) for key, seconds in ACTION_EXT_TIMEOUTS.items()},
}


def parse_action_ext(raw) -> tuple[str, int | None]:
    """action_ext правила → (действие, длительность таймаута).

    Неизвестное или пустое значение трактуется как ``auto`` (прежняя лестница): legacy-строки
    и опечатки не должны ломать модерацию. Действие ``auto`` означает «не переопределять».
    """
    key = str(raw or "").strip().lower()
    return ACTION_EXT_CHOICES.get(key, ("auto", None))


def resolve_rule_action(rule_action: str, action_ext_raw) -> tuple[str, str, int | None]:
    """Действие правила с учётом action_ext → (итоговое действие, action_ext, duration).

    Порядок по Q01: явное действие правила важнее лестницы по severity; если action_ext
    не задан, остаётся прежнее поведение.
    """
    ext, duration = parse_action_ext(action_ext_raw)
    if ext == "auto":
        return (rule_action or "block"), "", None
    return ext, ext, duration


def normalize_action_ext(raw) -> str:
    """Любое распознаваемое значение → канонический ключ ACTION_EXT_CHOICES ('' = auto).

    Нужно валидации category_policy роли (Q02) и вообще everywhere, где выбор действия
    хранится вне колонки action_ext правил: опечатки и чужие значения не должны ломать движок.
    """
    target = parse_action_ext(raw)
    if target == ("auto", None):
        return ""
    for key, pair in ACTION_EXT_CHOICES.items():
        if key in ("", "auto"):
            continue
        if pair == target:
            return key
    return ""


@dataclass
class OutgoingResult:
    ok: bool            # False = ответ нельзя публиковать
    text: str           # текст к отправке (замаскированный) или ''
    verdicts: list = field(default_factory=list)


# ─────────────────────────── Настройки / режимы ───────────────────────────

_settings_cache: dict[int, tuple[float, dict]] = {}
_rules_cache: dict[tuple[int, str], tuple[float, list[dict]]] = {}
_mode_cache: dict[tuple[int, str], tuple[float, str]] = {}
_category_policy_cache: dict[int, tuple[float, dict]] = {}
_base_rules_cache: dict[str, tuple[float, list[dict]]] = {}
_bot_role_cache: dict[int, tuple[float, str]] = {}

_extra_schema_ready = False


async def _ensure_extra_schema() -> None:
    """Ленивая схема модерации (первый вызов в любом сценарии — из get_settings).

    DDL живёт в database.ensure_moderation_schema — единственном источнике:
    guard-тест test_s5_db_isolation запрещает CREATE-дубли между файлами.
    """
    global _extra_schema_ready
    if _extra_schema_ready:
        return
    db = await database.get_db()
    try:
        await database.ensure_moderation_schema(db)
        _extra_schema_ready = True
    finally:
        await db.close()


# ─────────────── Q01/Q26: защищённые от «бана навсегда» ───────────────

def _norm_channel(channel: str) -> str:
    """Канал в канонической форме: lower + без ведущего '#'. Совпадает с остальным движком."""
    return (channel or "").lower().lstrip("#")


async def list_protected(account_id: int, channel: str | None = None) -> list[dict]:
    """Ручной список защищённых канала (или всех каналов аккаунта, если channel None)."""
    await _ensure_extra_schema()
    db = await database.get_db()
    try:
        if channel is None:
            cur = await db.execute(
                "SELECT id, channel, username, note, created_at FROM moderation_protected "
                "WHERE account_id = ? ORDER BY channel, username",
                (account_id,),
            )
        else:
            cur = await db.execute(
                "SELECT id, channel, username, note, created_at FROM moderation_protected "
                "WHERE account_id = ? AND channel = ? ORDER BY username",
                (account_id, _norm_channel(channel)),
            )
        rows = await cur.fetchall()
    finally:
        await db.close()
    return [dict(r) for r in rows]


async def add_protected(account_id: int, channel: str, username: str, note: str = "") -> int:
    """Добавить зрителя в список защищённых канала (per-канал, без общего списка)."""
    await _ensure_extra_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_protected (account_id, channel, username, note) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(account_id, channel, username) DO UPDATE SET note = excluded.note",
            (account_id, _norm_channel(channel), (username or "").strip().lower(), note or ""),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def remove_protected(account_id: int, channel: str, username: str) -> bool:
    """Убрать зрителя из списка защищённых канала. True = строка удалена."""
    await _ensure_extra_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "DELETE FROM moderation_protected WHERE account_id = ? AND channel = ? AND username = ?",
            (account_id, _norm_channel(channel), (username or "").strip().lower()),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def is_protected(account_id: int, channel: str, username: str, role: str = "") -> bool:
    """Защищён ли зритель от «бана навсегда» (DEC-OWNER-014).

    Защищены: (1) роль из PROTECTED_ROLES — модераторы/редакторы/стример, автоматически,
    независимо от списков; (2) имя в ручном списке этого канала (moderation_protected).
    Таймауты защита не блокирует — только вечный бан.
    """
    if role and role.strip().lower() in PROTECTED_ROLES:
        return True
    name = (username or "").strip().lower()
    if not name:
        return False
    await _ensure_extra_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT 1 FROM moderation_protected WHERE account_id = ? AND channel = ? AND username = ?",
            (account_id, _norm_channel(channel), name),
        )
        return await cur.fetchone() is not None
    finally:
        await db.close()


def invalidate_cache(account_id: int | None = None) -> None:
    """Сбросить кэши после изменения настроек/правил через API."""
    global _settings_cache, _rules_cache, _mode_cache, _extra_schema_ready
    _extra_schema_ready = False  # БД могла быть пересоздана (тесты, миграция)
    if account_id is None:
        _settings_cache.clear()
        _rules_cache.clear()
        _mode_cache.clear()
        _category_policy_cache.clear()
        _base_rules_cache.clear()
        _bot_role_cache.clear()
    else:
        _settings_cache.pop(account_id, None)
        _category_policy_cache.pop(account_id, None)
        _bot_role_cache.pop(account_id, None)
        _rules_cache = {k: v for k, v in _rules_cache.items() if k[0] != account_id}
        _mode_cache = {k: v for k, v in _mode_cache.items() if k[0] != account_id}


def invalidate_base_rules(channel: str | None = None) -> None:
    """Сброс кэша базы правил канала (после правок через API)."""
    if channel is None:
        _base_rules_cache.clear()
    else:
        _base_rules_cache.pop(_norm_channel(channel), None)


async def get_bot_role(account_id: int) -> str:
    """Q03: роль бота (accounts.bot_role); '' — аккаунта нет."""
    now = time.time()
    cached = _bot_role_cache.get(account_id)
    if cached and now - cached[0] < SETTINGS_TTL:
        return cached[1]
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT bot_role FROM accounts WHERE id = ?", (account_id,))
        row = await cur.fetchone()
    finally:
        await db.close()
    role = ((row["bot_role"] if row is not None else "") or "").strip()
    _bot_role_cache[account_id] = (now, role)
    return role


async def get_settings(account_id: int) -> dict:
    """Настройки модерации аккаунта из таблицы accounts (с TTL-кэшем)."""
    await _ensure_extra_schema()
    now = time.time()
    cached = _settings_cache.get(account_id)
    if cached and now - cached[0] < SETTINGS_TTL:
        return cached[1]
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT moderation_mode, moderation_can_timeout, timeout_policy, moderation_escalation_enabled, "
            "antispam_viewer_enabled, antispam_caps_pct, antispam_repeat_count, antispam_links, "
            "antispam_emote_pct, antispam_exempt_roles FROM accounts WHERE id = ?",
            (account_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if row is None:
        settings = {
            "moderation_mode": "off",
            "moderation_can_timeout": False,
            "timeout_policy": "auto",
            "moderation_escalation_enabled": True,
            "antispam_viewer_enabled": False,
            "antispam_caps_pct": 70,
            "antispam_repeat_count": 3,
            "antispam_links": True,
            "antispam_emote_pct": 80,
            "antispam_exempt_roles": "streamer,mod,vip",
        }
    else:
        keys = row.keys()
        settings = {
            "moderation_mode": (row["moderation_mode"] or "off") if "moderation_mode" in keys else "off",
            "moderation_can_timeout": bool(row["moderation_can_timeout"]) if "moderation_can_timeout" in keys else False,
            "timeout_policy": (row["timeout_policy"] or "auto") if "timeout_policy" in keys and row["timeout_policy"] in POLICIES else "auto",
            "moderation_escalation_enabled": bool(row["moderation_escalation_enabled"]) if "moderation_escalation_enabled" in keys and row["moderation_escalation_enabled"] is not None else True,
            "antispam_viewer_enabled": bool(row["antispam_viewer_enabled"]) if "antispam_viewer_enabled" in keys else False,
            "antispam_caps_pct": int(row["antispam_caps_pct"] or 70) if "antispam_caps_pct" in keys else 70,
            "antispam_repeat_count": int(row["antispam_repeat_count"] or 3) if "antispam_repeat_count" in keys else 3,
            "antispam_links": bool(row["antispam_links"]) if "antispam_links" in keys else True,
            "antispam_emote_pct": int(row["antispam_emote_pct"] or 80) if "antispam_emote_pct" in keys else 80,
            "antispam_exempt_roles": (row["antispam_exempt_roles"] or "") if "antispam_exempt_roles" in keys else "",
        }
    _settings_cache[account_id] = (now, settings)
    return settings


async def get_mode(account_id: int, channel: str = "") -> str:
    """Режим модерации: accounts.moderation_mode, с per-channel override
    (ключ ``moderation_mode`` в channel_overrides.overrides_json)."""
    ch = (channel or "").lower().lstrip("#")
    now = time.time()
    cached = _mode_cache.get((account_id, ch))
    if cached and now - cached[0] < SETTINGS_TTL:
        return cached[1]
    base = (await get_settings(account_id)).get("moderation_mode", "off")
    mode = base if base in MODES else "off"
    if ch:
        try:
            db = await database.get_db()
            try:
                cur = await db.execute(
                    "SELECT overrides_json FROM channel_overrides "
                    "WHERE account_id = ? AND channel = ? AND enabled = 1",
                    (account_id, ch),
                )
                row = await cur.fetchone()
            finally:
                await db.close()
            if row:
                overrides = json.loads(row["overrides_json"] or "{}")
                ov_mode = str(overrides.get("moderation_mode") or "").strip()
                if ov_mode in MODES:
                    mode = ov_mode
        except Exception as exc:
            logger.debug("moderation get_mode override error: %s", exc)
    _mode_cache[(account_id, ch)] = (now, mode)
    return mode


async def get_category_policy(account_id: int) -> dict[str, str]:
    """Q02: политика «категория → действие» из role_config бота (вкладка «Роль»).

    Хранится в accounts.role_config_json (moderator.category_policy — JSON-блоб, схема БД
    не меняется). Значения — канонические ключи ACTION_EXT_CHOICES; '' или нет ключа =
    лестница по severity, как раньше. Боты без этой настройки (не модераторы) получают {}.
    """
    now = time.time()
    cached = _category_policy_cache.get(account_id)
    if cached and now - cached[0] < SETTINGS_TTL:
        return cached[1]
    policy: dict[str, str] = {}
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT bot_role, role_config_json FROM accounts WHERE id = ?", (account_id,)
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if row is not None:
        try:
            from app.bot_roles import load_role_config
            cfg = load_role_config(row["role_config_json"], (row["bot_role"] or "chatter").strip())
            raw = cfg.get("category_policy")
            if isinstance(raw, dict):
                policy = {str(k): normalize_action_ext(v) for k, v in raw.items()}
        except Exception as exc:
            logger.debug("category policy load error: %s", exc)
    policy = {k: v for k, v in policy.items() if v}
    _category_policy_cache[account_id] = (now, policy)
    return policy


async def load_channel_base_rules(channel: str) -> list[dict]:
    """Q03: база правил канала (пресет Twitch + правки владельца).

    Таблица per-канал (moderation_channel_rules), без привязки к боту: любой бот
    с ролью «модератор» применяет её в этом канале (гейт в check_message).
    Правило бота с тем же паттерном переопределяет базу — дубли фильтруются там же.
    """
    ch = _norm_channel(channel)
    if not ch:
        return []
    now = time.time()
    cached = _base_rules_cache.get(ch)
    if cached and now - cached[0] < SETTINGS_TTL:
        return cached[1]
    await _ensure_extra_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_channel_rules WHERE channel = ? AND enabled = 1 ORDER BY id",
            (ch,),
        )
        rows = await cur.fetchall()
    finally:
        await db.close()
    rules = []
    for r in rows:
        rule = dict(r)
        rule["regex"] = _compile_pattern(_normalize(rule["pattern"]))
        rule["name"] = f"base:{rule['id']}"
        if rule["regex"] is not None:
            rules.append(rule)
    _base_rules_cache[ch] = (now, rules)
    return rules


async def load_custom_rules(account_id: int, channel: str = "") -> list[dict]:
    """Кастомные правила аккаунта, применимые к каналу (channel '' = все каналы)."""
    ch = (channel or "").lower().lstrip("#")
    now = time.time()
    cached = _rules_cache.get((account_id, ch))
    if cached and now - cached[0] < SETTINGS_TTL:
        return cached[1]
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM moderation_rules WHERE account_id = ? AND enabled = 1 ORDER BY id",
            (account_id,),
        )
        rows = await cur.fetchall()
    finally:
        await db.close()
    applicable = []
    for r in rows:
        keys = r.keys()
        rule_ch = (r["channel"] or "").lower().lstrip("#") if "channel" in keys else ""
        if rule_ch and ch and rule_ch != ch:
            continue
        rule = dict(r)
        rule["regex"] = _compile_pattern(_normalize(rule["pattern"]))
        if rule["regex"] is not None:
            applicable.append(rule)
    _rules_cache[(account_id, ch)] = (now, applicable)
    return applicable


# ─────────────────────────── Матчинг ───────────────────────────

def _find_matches(regex: re.Pattern, normalized_text: str) -> list[re.Match]:
    try:
        return list(regex.finditer(normalized_text))
    except Exception:
        return []


def _mask_spans(text: str, matches: list[re.Match]) -> str:
    """Частичная замена: каждое совпадение → '*' с сохранением длины."""
    if not matches:
        return text
    chars = list(text)
    for m in matches:
        for i in range(m.start(), min(m.end(), len(chars))):
            if chars[i] != " ":
                chars[i] = "*"
    return "".join(chars)


def _role_exempt(rule_exempt: str, role: str) -> bool:
    if not rule_exempt or not role:
        return False
    return role.lower() in {x.strip().lower() for x in rule_exempt.split(",") if x.strip()}


def _apply_mode_policy(action: str, mode: str, can_timeout: bool, policy: str = "auto") -> str:
    """Приводит действие правила к действию в рамках текущего режима.

    full     — действует всё; timeout/ban при can_timeout ИЛИ при политике ask/learn
               (рекомендация владельцу — наказание выполнится после «Да»).
    replace  — replace/block работают, timeout/ban деградируют до block.
    log_only — всё деградирует до log.
    off      — обрабатывается в check_message (сюда не доходит).

    Ban проходит через тот же рубильник can_timeout, что и таймаут: по умолчанию он выключен,
    значит без явного разрешения владельца вечных банов не бывает (Q01, `DEC-OWNER-014`).
    """
    if mode == "shadow":
        return "shadow"
    if mode == "log_only":
        return "log"
    if action in ("timeout", "ban"):
        allow = mode == "full" and (can_timeout or policy in ("ask", "learn"))
        return action if allow else "block"
    return action


async def check_message(
    account_id: int,
    channel: str,
    username: str,
    text: str,
    role: str = "viewer",
) -> list[Verdict]:
    """MODERATION_PLAN §1: проверка входящего сообщения → список вердиктов.

    Порядок: custom правила → built-in словари; первый вердикт с action ≠ log
    останавливает. В режиме off работает только скан угроз (threat 4-5 всегда
    попадают в журнал — решение владельца).
    """
    if not text or not text.strip():
        return []
    text_norm = _normalize(text)
    if not text_norm:
        return []
    mode = await get_mode(account_id, channel)
    _settings = await get_settings(account_id)
    can_timeout = bool(_settings.get("moderation_can_timeout"))
    policy = _settings.get("timeout_policy", "auto")
    cat_policy = await get_category_policy(account_id)

    def _with_category_policy(
        category: str, action: str, action_ext: str = "", duration_sec: int | None = None,
    ) -> tuple[str, str, int | None]:
        """Q02: политика роли «категория → действие» применяется поверх severity.

        Явное действие правила (action_ext, выбранное в редакторе правил) важнее
        политики роли; политика важнее лестницы по severity. Режим (log_only и т.п.)
        применяется позже, в _make_verdict, как и для любых действий.
        """
        if action_ext not in ("", "auto"):
            return action, action_ext, duration_sec
        pol = cat_policy.get(category)
        if not pol:
            return action, action_ext, duration_sec
        pol_action, pol_duration = parse_action_ext(pol)
        if pol_action == "auto":
            return action, action_ext, duration_sec
        return pol_action, pol, pol_duration

    def _make_verdict(
        *, category: str, action: str, severity: int, matches: list[re.Match],
        rule_id: int | None = None, rule_name: str = "", rule_action: str = "",
        action_ext: str = "", duration_sec: int | None = None,
    ) -> Verdict:
        eff = _apply_mode_policy(action, mode, can_timeout, policy)
        v = Verdict(
            category=category, action=eff, severity=severity,
            rule_id=rule_id, rule_name=rule_name, rule_action=rule_action,
            match=matches[0].group(0) if matches else "",
            action_ext=action_ext, duration_sec=duration_sec,
            is_shadow=(mode == "shadow"),
        )
        if eff == "replace" and matches:
            # Частичная замена: '*' с сохранением длины, по regex самого правила.
            v.masked_text = _mask_spans(text, matches)
        return v

    verdicts: list[Verdict] = []
    stopping = False

    # 1) Правила: база канала (Q03, только боты с ролью «модератор») затем per-бот.
    #    Порядок по Q03: пресет/база канала, затем per-бот правила; правило бота с тем же
    #    паттерном переопределяет базу (дубли из базы убираются).
    custom_rules = await load_custom_rules(account_id, channel)
    base_rules: list[dict] = []
    if await get_bot_role(account_id) == "moderator":
        bot_pats = {_normalize(r.get("pattern") or "") for r in custom_rules}
        base_rules = [
            r for r in await load_channel_base_rules(channel)
            if _normalize(r.get("pattern") or "") not in bot_pats
        ]
    for rule in [*base_rules, *custom_rules]:
        if _role_exempt(rule.get("exempt_roles", ""), role):
            continue
        rx = rule.get("regex")
        if rx is None:
            continue
        matches = _find_matches(rx, text_norm)
        if not matches:
            continue
        # Q01: явное действие правила (action_ext) перекрывает лестницу по severity.
        # Q02: поверх обоих — политика роли «категория → действие».
        eff_action, ext, duration = resolve_rule_action(
            rule.get("action") or "block", rule.get("action_ext")
        )
        eff_action, ext, duration = _with_category_policy(
            rule.get("category") or "custom", eff_action, ext, duration,
        )
        v = _make_verdict(
            category=rule.get("category") or "custom",
            action=eff_action,
            severity=int(rule.get("severity") or 3),
            matches=matches,
            rule_id=rule.get("id"),
            rule_name=rule.get("name") or rule.get("pattern") or "",
            rule_action=rule.get("action") or "block",
            action_ext=ext,
            duration_sec=duration,
        )
        verdicts.append(v)
        if v.action != "log":
            stopping = True
            break

    # 2) Встроенные словари (если кастомное правило не остановило).
    if not stopping:
        for rule in builtin_rules():
            matches = _find_matches(rule.regex, text_norm)
            if not matches:
                continue
            b_action, b_ext, b_duration = _with_category_policy(
                rule.category, severity_to_action(rule.severity),
            )
            v = _make_verdict(
                category=rule.category,
                action=b_action,
                severity=rule.severity,
                matches=matches,
                rule_name=f"builtin:{rule.lang}:{rule.pattern}",
                rule_action=severity_to_action(rule.severity),
                action_ext=b_ext,
                duration_sec=b_duration,
            )
            verdicts.append(v)
            if v.action != "log":
                stopping = True
                break

    # Режим off: только угрозы (всегда в журнал).
    if mode == "off":
        out: list[Verdict] = []
        for rule in builtin_rules():
            if rule.category != "threat" or rule.severity < 4:
                continue
            matches = _find_matches(rule.regex, text_norm)
            if matches:
                out.append(Verdict(
                    category="threat", action="log", severity=rule.severity,
                    rule_name=f"builtin:{rule.lang}:{rule.pattern}",
                    rule_action="log", match=matches[0].group(0),
                ))
        return out

    return verdicts


# ─────────────────────────── Журнал ───────────────────────────

async def log_event(
    account_id: int,
    channel: str,
    username: str,
    verdicts: list[Verdict],
    source: str = "chat_in",
    message_text: str = "",
) -> int:
    """MODERATION_PLAN §3: пишет вердикты в moderation_events. Возвращает кол-во записей."""
    if not verdicts:
        return 0
    excerpt = (message_text or "")[:200]
    db = await database.get_db()
    try:
        n = 0
        for v in verdicts:
            try:
                await db.execute(
                    "INSERT INTO moderation_events "
                    "(account_id, channel, username, rule_id, rule_name, category, severity, "
                    " action_taken, source, message_excerpt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        account_id, (channel or "").lower().lstrip("#"), username or "",
                        v.rule_id, v.rule_name, v.category, v.severity,
                        v.action, source, excerpt,
                    ),
                )
                n += 1
            except Exception as exc:
                logger.warning("moderation log_event insert error: %s", exc)
        await db.commit()
    finally:
        await db.close()
    return n


# ─────────────────────────── Исходящая модерация (§3) ───────────────────────────

async def check_outgoing(account_id: int, channel: str, reply: str, source: str = "bot_out") -> OutgoingResult:
    """Проверка ответа бота / ручной отправки перед публикацией.

    Возвращает OutgoingResult: ok=False → ответ не публикуется вовсе (бот молчит);
    иначе text — возможно замаскированный. Угрозы сканируются всегда, даже при off.
    """
    if not reply or not reply.strip():
        return OutgoingResult(ok=True, text=reply or "")
    mode = await get_mode(account_id, channel)
    _settings = await get_settings(account_id)
    can_timeout = bool(_settings.get("moderation_can_timeout"))
    policy = _settings.get("timeout_policy", "auto")
    text_norm = _normalize(reply)
    verdicts: list[Verdict] = []
    blocked = False
    masked = reply

    # Threat-скан работает всегда (угрозы от бота недопустимы в любом режиме).
    threat_hit = False
    for rule in builtin_rules():
        if rule.category != "threat" or rule.severity < 4:
            continue
        ms = _find_matches(rule.regex, text_norm)
        if ms:
            threat_hit = True
            verdicts.append(Verdict(
                category="threat", action="block", severity=rule.severity,
                rule_name=f"builtin:{rule.lang}:{rule.pattern}",
                rule_action="block", match=ms[0].group(0),
            ))
            break
    if threat_hit:
        blocked = True
        masked = ""

    if mode != "off" and not blocked:
        for rule in await load_custom_rules(account_id, channel):
            rx = rule.get("regex")
            if rx is None:
                continue
            ms = _find_matches(rx, text_norm)
            if not ms:
                continue
            # Q01: action_ext действует и на исходящие — но наказывать бот сам себя не может,
            # поэтому ban/timeout здесь означают «не публиковать ответ».
            rule_action_raw, ext, duration = resolve_rule_action(
                rule.get("action") or "block", rule.get("action_ext")
            )
            action = _apply_mode_policy(rule_action_raw, mode, can_timeout, policy)
            verdicts.append(Verdict(
                category=rule.get("category") or "custom", action=action,
                severity=int(rule.get("severity") or 3), rule_id=rule.get("id"),
                rule_name=rule.get("name") or rule.get("pattern") or "",
                rule_action=rule.get("action") or "block", match=ms[0].group(0),
                action_ext=ext, duration_sec=duration,
            ))
            if action in ("block", "timeout", "ban"):
                blocked = True
                break
        if not blocked:
            for rule in builtin_rules():
                if rule.category == "threat":
                    continue
                ms = _find_matches(rule.regex, text_norm)
                if not ms:
                    continue
                action = _apply_mode_policy(severity_to_action(rule.severity), mode, can_timeout, policy)
                verdicts.append(Verdict(
                    category=rule.category, action=action, severity=rule.severity,
                    rule_name=f"builtin:{rule.lang}:{rule.pattern}",
                    rule_action=severity_to_action(rule.severity), match=ms[0].group(0),
                ))
                if action == "replace":
                    masked = _mask_spans(masked, ms)
                elif action in ("block", "timeout", "ban"):
                    blocked = True
                    break

    if verdicts:
        try:
            await log_event(account_id, channel, "", verdicts, source=source, message_text=reply)
        except Exception as exc:
            logger.warning("moderation outgoing log error: %s", exc)

    if blocked:
        return OutgoingResult(ok=False, text="", verdicts=verdicts)
    return OutgoingResult(ok=True, text=masked, verdicts=verdicts)


# ─────────────────────────── Наказания через Helix (§3.4 + Q01-C2) ───────────────────────────

async def _execute_helix_punishment(account_id: int, channel: str, username: str, action: str,
                                    duration_sec: int, category: str, severity: int, rule_name: str,
                                    token: str, bot_nickname: str,
                                    write_journal: bool = True) -> bool:
    """Q01-C2: реальное наказание через Helix — таймаут с duration из вердикта
    или бан навсегда (тот же POST без `duration`) — плюс запись в журнал.
    False = не получилось (fallback до block делает вызывающий код).

    write_journal=False — когда журнальную строку ведёт вызывающий (исполнение
    из очереди: journal_resolve_by_pending помечает ту же запись applied)."""
    action = action if action in PUNISH_ACTIONS else "timeout"
    duration = int(duration_sec or DEFAULT_TIMEOUT_SEC)
    reason = f"moderation: {category} sev{severity}"
    try:
        from app import twitch_helix
        if action == "ban":
            ok, err = await twitch_helix.ban_user(
                token=token,
                channel=channel,
                moderator_login=bot_nickname,
                username=username,
                reason=reason,
            )
            note = f"ban permanent ({rule_name})"
        else:
            ok, err = await twitch_helix.timeout_user(
                token=token,
                channel=channel,
                moderator_login=bot_nickname,
                username=username,
                duration_sec=duration,
                reason=reason,
            )
            note = f"timeout {duration}s ({rule_name})"
        if ok:
            await log_event(
                account_id, channel, username,
                [Verdict(category=category, action=action, severity=severity,
                         rule_name=rule_name)],
                source="chat_in", message_text=note,
            )
            # Q26: применённое наказание — в владельческий журнал наказаний.
            if write_journal:
                try:
                    from app.moderation_journal import journal_applied
                    await journal_applied(
                        account_id, channel, username, category=category, severity=severity,
                        rule_name=rule_name, action=action,
                        duration_sec=None if action == "ban" else duration,
                        message_excerpt=note,
                    )
                except Exception as exc:
                    logger.warning("moderation journal_applied error: %s", exc)
            return True
        logger.info("moderation: %s fallback для %s в #%s: %s", action, username, channel, err)
    except Exception as exc:
        logger.warning("moderation punishment error: %s", exc)
    return False


async def _execute_helix_timeout(account_id: int, channel: str, username: str, category: str,
                                 severity: int, rule_name: str, token: str, bot_nickname: str,
                                 duration_sec: int = DEFAULT_TIMEOUT_SEC) -> bool:
    """Реальный таймаут через Helix + запись в журнал. False = не получилось.

    Обёртка над _execute_helix_punishment: раньше здесь был жёстко 600 с,
    теперь длительность приходит из вердикта (action_ext «таймаут 1 день» и т.п.)."""
    return await _execute_helix_punishment(
        account_id, channel, username, "timeout", duration_sec,
        category, severity, rule_name, token, bot_nickname,
    )


async def should_auto_timeout(account_id: int, category: str, policy: str = "auto") -> bool:
    """Политика «кто таймаутит»: auto — всегда да; ask — никогда (только вопрос);
    learn — да, если по категории накопился порог одобрений без отказов."""
    if policy == "auto":
        return True
    if policy != "learn":
        return False
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT approved, rejected FROM moderation_learn WHERE account_id = ? AND category = ?",
            (account_id, category),
        )
        row = await cur.fetchone()
    finally:
        await db.close()
    if row is None:
        return False
    approved, rejected = row["approved"] or 0, row["rejected"] or 0
    return approved >= LEARN_APPROVE_THRESHOLD and approved >= rejected * LEARN_REJECT_RATIO


def calculate_escalated_duration(base_duration: int, repeat_count: int) -> tuple[int, str]:
    """Вычисляет эскалированную длительность таймаута за повторные нарушения.
    repeat_count — количество предыдущих таймаутов зрителю за окно эскалации (по умолч. 1 час).
    Возвращает (новое_время_сек, заметка).
    """
    base = max(1, int(base_duration or DEFAULT_TIMEOUT_SEC))
    if repeat_count <= 0:
        return base, ""
    if repeat_count == 1:
        escalated = max(base * 5, 600)  # минимум 10 минут
    elif repeat_count == 2:
        escalated = max(base * 20, 3600)  # минимум 1 час
    else:
        escalated = max(base * 60, 86400)  # минимум 1 день (24 часа)

    # Максимальный допустимый Twitch таймаут: 2 недели (1,209,600 с)
    escalated = min(escalated, 1209600)
    note = f" (эскалация x{repeat_count + 1}: {escalated}s)"
    return escalated, note


async def get_recent_punishment_count(
    account_id: int,
    channel: str,
    username: str,
    window_seconds: int = 3600,
) -> int:
    """Количество применённых таймаутов зрителю в канале за последние window_seconds секунд."""
    if not username:
        return 0
    await _ensure_extra_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) FROM moderation_journal "
            "WHERE account_id = ? AND LOWER(channel) = ? AND LOWER(username) = ? "
            "  AND action = 'timeout' AND status = 'applied' "
            f"  AND created_at >= datetime('now', '-{int(window_seconds)} seconds')",
            (account_id, _norm_channel(channel), (username or "").strip().lower()),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as exc:
        logger.warning("get_recent_punishment_count error: %s", exc)
        return 0
    finally:
        await db.close()


async def create_pending_timeout(
    account_id: int, channel: str, username: str, category: str,
    severity: int, rule_name: str, message_text: str = "",
    requested_action: str = "timeout", duration_sec: int = DEFAULT_TIMEOUT_SEC,
    role: str = "",
) -> int:
    """Кладёт вопрос владельцу в очередь (всплывашка Да/Нет в панели).

    Q01-C2: очередь одна и на таймауты, и на «бан навсегда» (DEC-OWNER-014) —
    запрошенное действие и длительность хранятся в moderation_pending."""
    await _ensure_extra_schema()
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_pending "
            "(account_id, channel, username, category, severity, rule_name, message_excerpt, "
            " requested_action, duration_sec, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, _norm_channel(channel), username or "",
             category, severity, rule_name, (message_text or "")[:200],
             requested_action if requested_action in PUNISH_ACTIONS else "timeout",
             int(duration_sec or DEFAULT_TIMEOUT_SEC), role or ""),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def maybe_punish(
    account_id: int,
    channel: str,
    username: str,
    verdict: Verdict,
    token: str = "",
    bot_nickname: str = "",
    role: str = "",
) -> str:
    """Q01-C2 (DEC-OWNER-014): применить наказание из вердикта — таймаут или бан навсегда.

    Возвращает статус-строку:
      applied  — наказание реально применено через Helix;
      deferred — случай отложен владельцу (защищённый зритель при бане, политика ask/learn);
      skipped  — наказание не применено (не тот вердикт, рубильник выключен, нет токена).

    «Бан навсегда» на защищённого (модератор/редактор/стример или имя в ручном списке
    канала) НЕ применяется вообще: сообщение не удаляется и не маскируется, таймаут не
    даётся (осознанный выбор владельца) — случай уходит в очередь подтверждения и в журнал.
    Таймауты любой длины к защищённым применяются как настроено, без подтверждения.
    """
    if verdict.action not in PUNISH_ACTIONS or not username:
        return PUNISH_SKIPPED
    settings = await get_settings(account_id)
    policy = settings.get("timeout_policy", "auto")
    action = verdict.action
    duration = int(verdict.duration_sec or DEFAULT_TIMEOUT_SEC)
    rule_name = verdict.rule_name

    # Эскалация таймаута за повторные нарушения зрителя
    if action == "timeout" and settings.get("moderation_escalation_enabled", True):
        recent_count = await get_recent_punishment_count(account_id, channel, username)
        if recent_count > 0:
            duration, esc_note = calculate_escalated_duration(duration, recent_count)
            rule_name = f"{rule_name}{esc_note}"

    # Предохранитель вечного бана: срабатывает до политики и рубильников.
    if action == "ban" and await is_protected(account_id, channel, username, role):
        pending_id = await create_pending_timeout(
            account_id, channel, username, verdict.category, verdict.severity,
            rule_name, message_text="",
            requested_action="ban", duration_sec=0, role=role or "",
        )
        await log_event(
            account_id, channel, username,
            [Verdict(category=verdict.category, action="log", severity=verdict.severity,
                     rule_id=verdict.rule_id, rule_name=rule_name)],
            source="punishment_recommend",
            message_text=f"бан навсегда не применён: зритель защищён ({rule_name})",
        )
        # Q26: случай ждёт решения владельца — наказание НЕ применено вообще.
        try:
            from app.moderation_journal import journal_pending
            await journal_pending(
                account_id, channel, username, category=verdict.category,
                severity=verdict.severity, rule_name=rule_name, action="ban",
                duration_sec=None, pending_id=pending_id,
                detail=f"бан навсегда не применён: зритель защищён ({role or 'ручной список'})",
            )
        except Exception as exc:
            logger.warning("moderation journal_pending error: %s", exc)
        return PUNISH_DEFERRED

    if policy in ("ask", "learn") and not await should_auto_timeout(account_id, verdict.category, policy):
        pending_id = await create_pending_timeout(
            account_id, channel, username, verdict.category, verdict.severity,
            rule_name, message_text="",
            requested_action=action, duration_sec=duration, role=role or "",
        )
        await log_event(
            account_id, channel, username,
            [Verdict(category=verdict.category, action="log", severity=verdict.severity,
                     rule_id=verdict.rule_id, rule_name=rule_name)],
            source="timeout_recommend" if action == "timeout" else "punishment_recommend",
            message_text=(f"рекомендация таймаута {duration}s ({rule_name})"
                          if action == "timeout" else
                          f"рекомендация бана навсегда ({rule_name})"),
        )
        # Q26: рекомендация ждёт владельца — в журнале статус pending.
        try:
            from app.moderation_journal import journal_pending
            await journal_pending(
                account_id, channel, username, category=verdict.category,
                severity=verdict.severity, rule_name=rule_name, action=action,
                duration_sec=None if action == "ban" else duration, pending_id=pending_id,
                detail=f"политика {policy}: ждёт решения владельца",
            )
        except Exception as exc:
            logger.warning("moderation journal_pending error: %s", exc)
        return PUNISH_DEFERRED

    if not settings.get("moderation_can_timeout") or not token:
        return PUNISH_SKIPPED
    ok = await _execute_helix_punishment(
        account_id, channel, username, action, duration,
        verdict.category, verdict.severity, rule_name, token, bot_nickname,
    )
    return PUNISH_APPLIED if ok else PUNISH_SKIPPED


async def maybe_timeout(
    account_id: int,
    channel: str,
    username: str,
    verdict: Verdict,
    token: str = "",
    bot_nickname: str = "",
) -> bool:
    """§3.4 + политика «кто таймаутит» (auto/ask/learn).

    auto  — таймаут сразу (если есть token/can_timeout), иначе fallback block+лог.
    ask   — вопрос владельцу в moderation_pending; таймаут только после «Да».
    learn — как ask, но выученные категории (should_auto_timeout) таймаутятся сами.

    Возвращает True, если таймаут реально применён. Делегирует в maybe_punish (Q01-C2):
    бан-вердикты и предохранитель защищённых обрабатываются там же."""
    status = await maybe_punish(
        account_id, channel, username, verdict, token=token, bot_nickname=bot_nickname,
    )
    return status == PUNISH_APPLIED


async def list_pending_timeouts(account_id: int | None = None, limit: int = 20) -> list[dict]:
    """Нерешённые вопросы владельцу (для всплывашки в панели)."""
    # P7 Ф4 (Ф2-2): таблица ленивая — на свежей БД эндпоинт падал 500
    # (прецедент snippets, ddbfb8f).
    await _ensure_extra_schema()
    db = await database.get_db()
    try:
        if account_id is None:
            cur = await db.execute(
                "SELECT * FROM moderation_pending WHERE status = 'pending' "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM moderation_pending WHERE status = 'pending' AND account_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (account_id, limit),
            )
        rows = await cur.fetchall()
    finally:
        await db.close()
    return [dict(r) for r in rows]


async def record_timeout_decision(
    rec_id: int,
    approved: bool,
    token: str = "",
    bot_nickname: str = "",
) -> dict:
    """Ответ владельца на всплывашку: Да → таймаут + «+1 одобрено» в обучении,
    Нет → «+1 отклонено». Возвращает итог решения."""
    await _ensure_extra_schema()  # Ф2-2: свежая БД — таблица ленивая
    db = await database.get_db()
    try:
        cur = await db.execute("SELECT * FROM moderation_pending WHERE id = ?", (rec_id,))
        row = await cur.fetchone()
        if row is None:
            return {"ok": False, "error": "not_found"}
        if row["status"] != "pending":
            return {"ok": False, "error": "already_decided"}
        await db.execute(
            "UPDATE moderation_pending SET status = ?, decided_at = datetime('now') WHERE id = ?",
            ("approved" if approved else "rejected", rec_id),
        )
        if approved:
            await db.execute(
                "INSERT INTO moderation_learn (account_id, category, approved, rejected) VALUES (?, ?, 1, 0) "
                "ON CONFLICT(account_id, category) DO UPDATE SET approved = approved + 1",
                (row["account_id"], row["category"]),
            )
        else:
            await db.execute(
                "INSERT INTO moderation_learn (account_id, category, approved, rejected) VALUES (?, ?, 0, 1) "
                "ON CONFLICT(account_id, category) DO UPDATE SET rejected = rejected + 1",
                (row["account_id"], row["category"]),
            )
        await db.commit()
    finally:
        await db.close()

    executed = False
    if approved and row["username"]:
        # Q01-C2: выполняем запрошенное действие из строки очереди (таймаут нужной
        # длительности или бан навсегда), а не всегда таймаут 600 с. Одобрение владельца —
        # явное решение по защищённому зрителю: предохранитель здесь не переспрашивает.
        req_action = (row["requested_action"] or "timeout") if "requested_action" in row.keys() else "timeout"
        if req_action not in PUNISH_ACTIONS:
            req_action = "timeout"
        req_duration = int(row["duration_sec"] or DEFAULT_TIMEOUT_SEC) if "duration_sec" in row.keys() else DEFAULT_TIMEOUT_SEC
        executed = await _execute_helix_punishment(
            row["account_id"], row["channel"], row["username"], req_action, req_duration,
            row["category"], row["severity"], row["rule_name"], token, bot_nickname,
            write_journal=False,  # журнальную строку пометит journal_resolve_by_pending
        )
        if executed:
            db = await database.get_db()
            try:
                await db.execute(
                    "UPDATE moderation_pending SET status = 'executed' WHERE id = ?", (rec_id,)
                )
                await db.commit()
            finally:
                await db.close()
    # Q26: решение владельца отражается в журнале наказаний (pending → applied/cancelled) —
    # и при одобрении, и при отклонении, поэтому вне ветки исполнения.
    try:
        from app.moderation_journal import journal_resolve_by_pending
        await journal_resolve_by_pending(rec_id, approved=bool(approved), executed=bool(executed))
    except Exception as exc:
        logger.warning("moderation journal_resolve error: %s", exc)
    return {"ok": True, "approved": approved, "executed": executed}


async def get_learn_stats(account_id: int) -> list[dict]:
    """Статистика обучения по категориям (для панели)."""
    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT category, approved, rejected FROM moderation_learn WHERE account_id = ? ORDER BY category",
            (account_id,),
        )
        rows = await cur.fetchall()
    finally:
        await db.close()
    out = []
    for r in rows:
        d = dict(r)
        d["auto"] = await should_auto_timeout(
            account_id, r["category"],
            "learn",
        )
        out.append(d)
    return out


# ─────────────────────────── Антиспам зрителей (§2) ───────────────────────────

@dataclass
class SpamHit:
    category: str          # caps / links / repeat / emote / copypasta
    severity: int
    detail: str
    action: str = "spam_log"    # spam_log | spam_timeout_recommend


@dataclass
class _SpamChannelState:
    user_repeat: dict = field(default_factory=dict)     # username -> deque[(ts, text)]
    channel_recent: deque = field(default_factory=lambda: deque(maxlen=COPYPASTA_WINDOW))


class SpamDetector:
    """Эвристики спама для входящего чата (§2). In-memory, без БД.

    По умолчанию все попадания — только лог (spam_log). Если включён §3.4
    (full + can_timeout) — для links/repeat пишется рекомендация таймаута.
    Бот сам не банит по эвристикам.
    """

    def __init__(self) -> None:
        self._state: dict[tuple[int, str], _SpamChannelState] = {}

    def _state_for(self, account_id: int, channel: str) -> _SpamChannelState:
        key = (account_id, (channel or "").lower().lstrip("#"))
        st = self._state.get(key)
        if st is None:
            st = _SpamChannelState()
            self._state[key] = st
        return st

    def check(
        self,
        account_id: int,
        channel: str,
        username: str,
        text: str,
        settings: dict,
        role: str = "viewer",
        mode: str = "off",
    ) -> list[SpamHit]:
        if not text or not text.strip():
            return []
        exempt = {x.strip().lower() for x in (settings.get("antispam_exempt_roles") or "").split(",") if x.strip()}
        if role and role.lower() in exempt:
            return []

        hits: list[SpamHit] = []
        recommend = mode == "full" and bool(settings.get("moderation_can_timeout"))
        recommend_action = "spam_timeout_recommend" if recommend else "spam_log"
        tokens = text.split()

        # CAPS: >70% (настраивается) и длина ≥8 букв.
        caps_pct = int(settings.get("antispam_caps_pct") or 0)
        if caps_pct:
            letters = [c for c in text if c.isalpha()]
            if len(letters) >= 8:
                caps = sum(1 for c in letters if c.isupper())
                ratio = caps * 100 // len(letters)
                if ratio > caps_pct:
                    hits.append(SpamHit("caps", 1, f"caps {ratio}% > {caps_pct}%", recommend_action))

        # Links.
        if settings.get("antispam_links") and LINK_RE.search(text):
            hits.append(SpamHit("links", 2, "содержит ссылку", recommend_action))

        # Repeat: одинаковые сообщения N раз в окне (не обязательно подряд).
        repeat_n = int(settings.get("antispam_repeat_count") or 0)
        if repeat_n >= 2:
            st = self._state_for(account_id, channel)
            norm = _normalize(text).strip()
            hist = st.user_repeat.setdefault((username or "").lower(), deque(maxlen=max(repeat_n, 10)))
            now = time.time()
            hist.append((now, norm))
            recent_same = sum(1 for ts, t in hist if t == norm and now - ts <= REPEAT_WINDOW_SEC)
            if recent_same >= repeat_n:
                hits.append(SpamHit("repeat", 2, f"повтор {recent_same}x за {int(REPEAT_WINDOW_SEC)}с", recommend_action))

        # Emote-spam: >80% токенов — эмодзи/короткие реагирования.
        emote_pct = int(settings.get("antispam_emote_pct") or 0)
        if emote_pct and len(tokens) >= 4:
            emote_like = 0
            for tok in tokens:
                clean = tok.strip(".,!?~")
                if not clean:
                    emote_like += 1
                elif _EMOJI_RE.fullmatch(clean):
                    emote_like += 1
                elif len(clean) <= 2:
                    emote_like += 1
                elif clean.isupper() and 2 <= len(clean) <= 6 and clean.isalpha():
                    # KEKW / LUL / POG / Kappa-подобные
                    emote_like += 1
            ratio = emote_like * 100 // len(tokens)
            if ratio > emote_pct:
                hits.append(SpamHit("emote", 1, f"эмодзи/эмоуты {ratio}% > {emote_pct}%", "spam_log"))

        # Copypasta: самопохожесть с недавними сообщениями канала.
        if len(text) >= COPYPASTA_MIN_LEN:
            st = self._state_for(account_id, channel)
            recent = [t for _, t in st.channel_recent]
            if recent:
                try:
                    sim = compute_self_similarity(text, recent)
                except Exception:
                    sim = 0.0
                if sim >= COPYPASTA_THRESHOLD:
                    hits.append(SpamHit("copypasta", 1, f"copypasta sim={sim:.2f}", "spam_log"))
            st.channel_recent.append((time.time(), text))

        return hits


spam_detector = SpamDetector()


# ─────────────────────────── Удобные обёртки для вызывающих ───────────────────────────

def summarize(verdicts: list[Verdict], hits: list[SpamHit] = ()) -> str:
    """Короткая строка для ai_log: 'insult/replace sev2, caps/spam_log'."""
    parts = [f"{v.category}/{v.action}({v.severity})" for v in verdicts]
    parts += [f"{h.category}/{h.action}" for h in hits]
    return ", ".join(parts)


async def check_incoming(
    account_id: int,
    channel: str,
    username: str,
    text: str,
    role: str = "viewer",
) -> tuple[list[Verdict], list[SpamHit]]:
    """Полная проверка входящего сообщения (правила + антиспам) с журналированием.

    Возвращает (verdicts, spam_hits). Лог пишется здесь же (одна точка).
    """
    settings = await get_settings(account_id)
    mode = await get_mode(account_id, channel)
    verdicts = await check_message(account_id, channel, username, text, role=role)
    hits: list[SpamHit] = []
    if mode != "off" and settings.get("antispam_viewer_enabled"):
        hits = spam_detector.check(account_id, channel, username, text, settings, role=role, mode=mode)
        # Политика ask/learn: рекомендации спам-таймаута тоже спрашивают владельца.
        policy = settings.get("timeout_policy", "auto")
        for h in hits:
            if h.action == "spam_timeout_recommend" and not await should_auto_timeout(account_id, h.category, policy):
                await create_pending_timeout(
                    account_id, channel, username, h.category, h.severity,
                    f"antispam:{h.category}", message_text=text,
                )
    if verdicts:
        await log_event(account_id, channel, username, verdicts, source="chat_in", message_text=text)
    if hits:
        await log_spam_hits(account_id, channel, username, hits, message_text=text)
    return verdicts, hits


async def log_spam_hits(
    account_id: int,
    channel: str,
    username: str,
    hits: list[SpamHit],
    message_text: str = "",
) -> None:
    """Пишет антиспам-попадания в moderation_events (source='antispam')."""
    if not hits:
        return
    excerpt = (message_text or "")[:200]
    db = await database.get_db()
    try:
        for h in hits:
            await db.execute(
                "INSERT INTO moderation_events "
                "(account_id, channel, username, rule_id, rule_name, category, severity, "
                " action_taken, source, message_excerpt) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, 'antispam', ?)",
                (account_id, (channel or "").lower().lstrip("#"), username or "",
                 f"spam:{h.category}", "spam", h.severity, h.action, excerpt),
            )
        await db.commit()
    finally:
        await db.close()
