"""PLAN_FEEDBACK_3008 §6: роли ботов.

Роль задаёт боту свою панель настроек (role_config) и гейты в рантайме.
role_config хранится ОТДЕЛЬНО на каждую роль (§6.7): {role: {...}} —
переключение модератор→болтун→модератор не теряет настройки.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

VALID_ROLES = ("chatter", "moderator", "voice_companion", "lurker", "director")
DEFAULT_ROLE = "chatter"

ROLE_COLORS = {
    "moderator": "#e74c3c",       # красный
    "voice_companion": "#9146ff",  # фиолетовый
    "chatter": "#22c55e",          # зелёный
    "lurker": "#38bdf8",           # голубой
    "director": "#f59e0b",         # янтарный
}

ROLE_DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
    "chatter": {
        "anti_assistant": True,
        # §R4: пресет стиля ('' = дефолт) + копирка «как у живого»
        "preset_key": "",                # svoi_vdosku|emotional|ehidny|znatok|memny|custom
        "mimic_mode": "off",             # off | copy | profile
        "mimic_user": "",
        "mimic_copy_msgs": [],           # последние 30–50 сообщений юзера (few-shot)
        "mimic_copy_summary": "",        # одна авто-строка выжимки стиля
        "mimic_profile": "",             # редактируемый стил-профиль (режим B)
        "mimic_strength": 60,            # сила копирования 0–100
        "mimic_checks": {"lexicon": True, "emoji": True, "caps": True,
                         "typos": False, "length": True},
        "learned_pool": [],              # 👍 ответы бота (самообучение, лимит 30)
    },
    "moderator": {
        "chat_activity": "chatter",     # chatter | moderation_only | silent (болтает по умолчанию)
        "strictness": "normal",          # soft | normal | strict | manual
        "ladder_warn": 1,                # нарушение № → предупреждение
        "ladder_t1_min": 1,              # нарушение №2 → таймаут, мин
        "ladder_t2_min": 10,             # нарушение №3 → таймаут, мин
        "ladder_ban": 4,                 # нарушение №4 → бан
        "dictionary": "builtin",         # builtin | off (ru/en/ua встроенный)
        "custom_words": [],
        "translit": True,                # ловить замаскированные «м***к»/транслит
        "ai_judge": False,               # AI-судья для спорных
        "ai_judge_soft": True,           # при сомнении — предупреждение вместо таймаута
        "exempt_roles": ["broadcaster", "moderator", "vip", "subscriber"],
        "whitelist": [],
        "warn_before": True,             # писать «@user, предупреждение» перед наказанием
        "warn_text": "",
        "announce_in_chat": False,       # дефолт — всплывашки mod-feed, не чат
        "tts_announce": False,
        "confirm_mode": "auto",          # auto | confirm (намерения ждут одобрения)
        # Q02: таблица «категория → явное действие» (insult/hate/threat/sexual/spam).
        # Значения — ключи ACTION_EXT_CHOICES ('' = лестница по severity, как раньше);
        # живёт в role_config_json, схему БД не меняет.
        "category_policy": {},
        "stream_tool_modes": {           # §6.1a: auto | suggest | off
            "category": "suggest", "title": "suggest", "slow": "suggest",
            "follower": "suggest", "emote_only": "off", "unique": "off",
            "ai_category": "suggest",
        },
    },
    "voice_companion": {
        "companion_scope": "channel_chat",  # W3: наблюдает и отвечает в публичном Twitch-чате
        "voice_source": "preset",        # preset | clone
        "clone_id": None,
        "provider_voice": "",
        "rate": 1.0, "volume": 1.0, "emotion": "",
        "on_speech": True, "on_questions": False, "on_silence": False,
        "silence_sec": 20, "command_phrases": [],
        "reply_delay_sec": 2, "max_reply_len": 120,
        "interruptible": False,          # договаривает по умолчанию
        "excluded_topics": [], "ignore_swears": True,
        "whisper_confidence": 0.6, "min_streamer_words": 3,
        "max_per_10min": 6, "cooldown_sec": 45,
    },
    "lurker": {
        # C6 (PLAN_TODO ТРЕК 1): остальные lurker-поля (collect_users/collect_lore/
        # observations/observation_interval_min/memory_limit_per_stream/auto_cleanup_days)
        # удалены — их не читал ни один код-путь. mention_reply реально гейтит ответы
        # в chat_analyzer._role_gate.
        "mention_reply": False,          # по умолчанию молчит даже на @
    },
    # Director observes and creates structured plans only.  Its account is never
    # an outbound chat speaker; per-channel configuration lives in director_configs.
    "director": {},
}

# §6.5: валидация полей по роли — whitelist ключей на каждом уровне.
_NESTED_KEYS = {
    "stream_tool_modes": {"category", "title", "slow", "follower",
                          "emote_only", "unique", "ai_category"},
    "mimic_checks": {"lexicon", "emoji", "caps", "typos", "length"},
    # Q02: политика «категория → действие» — только категории verdict'ов движка
    "category_policy": {"insult", "hate", "threat", "sexual", "spam"},
}

_ENUM_VALUES = {
    "preset_key": {"", "svoi_vdosku", "emotional", "ehidny", "znatok", "memny", "custom"},
    "mimic_mode": {"off", "copy", "profile"},
    "chat_activity": {"chatter", "moderation_only", "silent"},
    "strictness": {"soft", "normal", "strict", "manual"},
    "dictionary": {"builtin", "off"},
    "confirm_mode": {"auto", "confirm"},
    "companion_scope": {"channel_chat"},
    "voice_source": {"preset", "clone"},
}

_NESTED_ENUM_VALUES = {
    "stream_tool_modes": {"auto", "suggest", "off"},
}


def _allowed_keys(role: str) -> set[str]:
    return set(ROLE_DEFAULT_CONFIGS.get(role, {}).keys())


def validate_role_config(role: str, config: Any) -> dict[str, Any]:
    """Фильтрует config до разрешённых полей роли + нормализует типы/размер.

    Неизвестные ключи отбрасываются, типы приводятся (bool/int/str/list/dict),
    итог ≤ 32 КБ JSON. Бросает ValueError на кривой тип config.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"unknown_role: {role}")
    if config is None:
        return dict(ROLE_DEFAULT_CONFIGS[role])
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    allowed = _allowed_keys(role)
    clean: dict[str, Any] = {}
    for k, v in config.items():
        if k not in allowed:
            continue
        if k in _NESTED_KEYS:
            clean[k] = _clean_nested(role, k, v)
        elif k in _ENUM_VALUES:
            candidate = str(v)[:2000] if isinstance(v, str) else ""
            clean[k] = candidate if candidate in _ENUM_VALUES[k] else ROLE_DEFAULT_CONFIGS[role][k]
        elif isinstance(v, bool):
            clean[k] = v
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            clean[k] = _clamp(k, v)
        elif isinstance(v, str):
            clean[k] = v[:2000]
        elif isinstance(v, list):
            clean[k] = [str(x)[:200] for x in v][:200]
        elif v is None:
            clean[k] = None
    if len(json.dumps(clean, ensure_ascii=False)) > 32 * 1024:
        raise ValueError("config too large")
    return clean


def _clean_nested(role: str, key: str, v: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(v, dict):
        for nk, nv in v.items():
            if nk in _NESTED_KEYS[key]:
                if key == "category_policy":
                    # Q02: значение — канонический ключ действия; мусор → '' (severity-лестница)
                    from app.moderation import normalize_action_ext
                    out[nk] = normalize_action_ext(nv)
                elif key in _NESTED_ENUM_VALUES:
                    candidate = str(nv)[:20] if isinstance(nv, str) else ""
                    default = ROLE_DEFAULT_CONFIGS[role][key][nk]
                    out[nk] = candidate if candidate in _NESTED_ENUM_VALUES[key] else default
                else:
                    # булевы сохраняем как bool, остальное — строкой (короткой)
                    out[nk] = bool(nv) if isinstance(nv, bool) else str(nv)[:20]
    return out


def _clamp(key: str, v: Any) -> Any:
    iv = int(v)
    if key == "mimic_strength":
        return max(0, min(100, iv))
    if key.endswith("_min") or key.endswith("_sec"):
        return max(0, min(600, iv))
    if key == "silence_sec":
        return max(5, min(600, iv))
    if key == "whisper_confidence":
        return max(0.0, min(1.0, float(v)))
    if key in ("rate", "volume"):
        return max(0.1, min(2.0, float(v)))
    if key in ("ladder_warn", "ladder_t1_min", "ladder_t2_min", "ladder_ban"):
        return max(1, min(20, iv))
    if key.endswith("_per_10min") or key == "max_per_10min":
        return max(0, min(200, iv))
    return max(0, min(100000, iv))


def load_role_config(raw_json: str | None, role: str) -> dict[str, Any]:
    """Достаёт конфиг конкретной роли из accounts.role_config_json (+дефолты)."""
    base = dict(ROLE_DEFAULT_CONFIGS.get(role, {}))
    if not raw_json:
        return base
    try:
        data = json.loads(raw_json)
        if isinstance(data, dict) and isinstance(data.get(role), dict):
            base.update(validate_role_config(role, data[role]))
    except (ValueError, TypeError) as exc:
        logger.warning("role_config parse error (%s): %s", role, exc)
    except json.JSONDecodeError as exc:
        logger.warning("role_config json error: %s", exc)
    return base


# ── §R4 PLAN_SESSION_ROLES: пресеты болтуна и копирка «как у живого» ──

# Анти-ассистент фильтр — входит во ВСЕ пресеты (владелец: «прям нормальные
# пресеты, а не вечный подсказчик»).
ANTI_ASSISTANT_RULE = (
    "Анти-ассистент правила (СТРОГО): не давай советов, если не просили; "
    "не начинай сообщение с «Ты можешь», «Стоит», «Попробуй», «Рекомендую»; "
    "никаких списков, нумерации и markdown; никогда не упоминай, что ты AI, "
    "бот или ассистент; максимум 1–2 коротких предложения; пиши как живой "
    "зритель в чате стрима, а не как помощник."
)

CHATTER_PRESETS: dict[str, dict[str, Any]] = {
    "svoi_vdosku": {
        "label": "Свой в доску",
        "prompt": (
            "Ты свой в доску зритель: сленг, коротко, без вежливости и формальностей, "
            "люблю подкалывать над стримером и чатом по-доброму. Пишу как в дискорде с пацанами."
        ),
        "examples": [
            "ахахах стрим умер, вызывайте врача",
            "ну ты и выдал, разраб",
            "база, плюсую",
            "стримера на мыло за такой клип",
        ],
    },
    "emotional": {
        "label": "Эмоциональный",
        "prompt": (
            "Ты максимально эмоциональный зритель: КАПС на эмоциях, восторг или шок, "
            "много эмоций в каждом сообщении, реагируешь на ВСЁ что происходит."
        ),
        "examples": [
            "ААААА ЧТО ЭТО БЫЛО",
            "ЭТО ЛУЧШИЙ МОМЕНТ ГОДА КАПЕЦ",
            "Я В ШОКЕ ПРОСТО АААА",
        ],
    },
    "ehidny": {
        "label": "Ехидный",
        "prompt": (
            "Ты ехидный зритель: сарказм, ирония, лёгкий троллинг стримера без токсичности "
            "и оскорблений. Никогда не переходишь на личности и не матерись грубо."
        ),
        "examples": [
            "ну конечно, мы все верили",
            "гениально, ничего не сказать",
            "так держать, чемпион",
        ],
    },
    "znatok": {
        "label": "Тихий знаток",
        "prompt": (
            "Ты редкий, но по делу зритель: пишешь нечасто, только когда есть что сказать, "
            "знаешь игру/лор стрима. Короткие информативные комментарии без воды."
        ),
        "examples": [
            "тут через дым проход free",
            "у него в прошлый раз тот же фейл был на 12:40",
            "катка проиграна, тимдиф 10к",
        ],
    },
    "memny": {
        "label": "Мемный",
        "prompt": (
            "Ты мемный зритель: отвечаешь мемами и фразами-шаблонами чата, коротко, "
            "иногда с эмодзи. Не объясняй мемы."
        ),
        "examples": [
            "это база",
            "чел не гей",
            "мода",
            "как говорится, ввввв",
        ],
    },
    "custom": {
        "label": "Свой (чистый лист)",
        "prompt": "",
        "examples": [],
    },
}


def chatter_style_block(cfg: dict[str, Any]) -> str:
    """§R4: блок стиля болтуна для system prompt.

    Приоритет: копирка (mimic_mode='copy') > стил-профиль ('profile') >
    пресет (preset_key) > дефолт (пусто). Анти-ассистент добавляется по флагу.
    Токен-бюджет: весь блок ≤ 4000 символов, примеры ≤ 200 символов каждый.
    """
    parts: list[str] = []

    mode = cfg.get("mimic_mode") or "off"
    strength = int(cfg.get("mimic_strength", 60) or 0)
    checks = cfg.get("mimic_checks") or {}

    aspects = []
    if checks.get("lexicon", True):
        aspects.append("лексику")
    if checks.get("emoji", True):
        aspects.append("эмодзи")
    if checks.get("caps", True):
        aspects.append("капс")
    if checks.get("typos", False):
        aspects.append("опечатки")
    if checks.get("length", True):
        aspects.append("длину сообщений")
    aspect_line = ", ".join(aspects) if aspects else "лексику"

    if mode == "copy":
        msgs = [str(m)[:200] for m in (cfg.get("mimic_copy_msgs") or []) if str(m).strip()]
        msgs = msgs[:50]
        if msgs:
            parts.append(
                "Говори В ТОМ ЖЕ СТИЛЕ, что и этот зритель (это копия его сообщений). "
                f"Сила подражания: {strength}/100. Копируй: {aspect_line}. "
                "НЕ копируй его смысл/темы буквально — стиль, а не содержание."
            )
            parts.append("Примеры его сообщений:\n" + "\n".join(f"- {m}" for m in msgs[:40]))
            summary = str(cfg.get("mimic_copy_summary") or "").strip()
            if summary:
                parts.append(f"Выжимка стиля: {summary}")
        else:
            return ""
    elif mode == "profile":
        profile = str(cfg.get("mimic_profile") or "").strip()
        if not profile:
            return ""
        parts.append(
            f"Твой стиль общения (сила подражания {strength}/100, копируй: {aspect_line}):\n{profile[:1500]}"
        )
    else:
        preset = CHATTER_PRESETS.get(str(cfg.get("preset_key") or ""))
        preset_found = preset is not None
        if preset and preset.get("prompt"):
            parts.append(preset["prompt"])
            exs = [str(e)[:200] for e in preset.get("examples", [])]
            if exs:
                parts.append("Примеры твоих реплик:\n" + "\n".join(f"- {e}" for e in exs))

    pool = [str(m)[:200] for m in (cfg.get("learned_pool") or []) if str(m).strip()]
    if pool:
        parts.append("Твои удачные ответы (зрители хвалили — держи этот уровень):\n"
                     + "\n".join(f"- {m}" for m in pool[-10:]))

    if cfg.get("anti_assistant", True):
        parts.append(ANTI_ASSISTANT_RULE)

    if not parts:
        return ""  # ничего не настроено (off + без пресета + без анти)

    block = "\n\n".join(parts)
    # токен-бюджет: режем хвост, сохраняя анти-ассистент
    if len(block) > 4000:
        cut = max(1000, 4000 - len(ANTI_ASSISTANT_RULE) - 40)
        block = block[:cut].rsplit("\n", 1)[0] + "\n\n" + ANTI_ASSISTANT_RULE
    return block


def learn_from_feedback(raw_json: str | None, message: str, rating: int,
                        *, pool_limit: int = 30) -> str:
    """§R4 самообучение: 👍 → ответ в learned_pool, 👎 → исключить из пула.

    Работает с nested role_config_json; возвращает обновлённый JSON (или None
    при отсутствии chatter-конфига — тогда вызывающий не трогает запись).
    """
    try:
        data = json.loads(raw_json) if raw_json else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    chatter = data.get("chatter")
    if not isinstance(chatter, dict):
        return ""  # нет конфига болтуна — нечего учить
    msg = (message or "").strip()[:200]
    if not msg:
        return ""
    pool = [str(m) for m in chatter.get("learned_pool", []) if str(m).strip()]
    if rating > 0:
        if msg not in pool:
            pool.append(msg)
        pool = pool[-pool_limit:]
    else:
        pool = [m for m in pool if m != msg]
    chatter["learned_pool"] = pool
    data["chatter"] = chatter
    return json.dumps(data, ensure_ascii=False)
