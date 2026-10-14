"""Промпт-блоки ChatAnalyzer — вынесено из app/chat_analyzer.py (P5-сплит, PLAN.md).

Mixin: _load_streamer_profile_block (профиль стримера + К3 отношение) и
_load_persona_block (персона + per-channel overrides). ChatAnalyzer наследует
этот mixin; методы перенесены как есть.
"""
import json
import logging

from app.ai_service import ai_log
from app.database import get_db

logger = logging.getLogger(__name__)


class ChatPromptBlocksMixin:
    """Mixin для ChatAnalyzer: блоки профиля/персоны для промпта."""

    async def _load_prompt_base_block(self, channel: str = "") -> str:
        """Q18 (DEC-OWNER-004): запретные темы per-канал + базовый пресет Twitch.

        Читает свой список канала (settings-kv ``banned_topics:<channel>``);
        если у канала его нет — наследует пресет ``banned_topics_preset``
        (сид: legacy-текст ``prompt_base`` или стартовый набор Twitch).
        Формат: одна запретка/правило на строку, «#»-комментарии пропускаются.

        PB-2, порядок сборки system prompt: **база → персона/личный промпт
        бота → правила подсистем**. База идёт ПЕРВОЙ, поэтому при конфликте
        содержания персональный промпт/персона сильнее (идут позже); при этом
        база — жёсткий минимум, который бот не нарушает в любом случае.
        """
        try:
            from app.channel_bans import normalize_channel, resolve_channel_bans
            raw, source = await resolve_channel_bans(channel)
            ch = normalize_channel(channel)
        except Exception as exc:  # noqa: BLE001
            logger.debug("banned topics load: %s", exc)
            return ""
        raw = (raw or "").strip()
        if not raw:
            return ""
        rules = [
            ln.strip() for ln in raw.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if not rules:
            return ""
        scope = f"канал #{ch}" if (source == "channel" and ch) else "базовый пресет Twitch"
        return (
            f"ОБЯЗАТЕЛЬНАЯ БАЗА ПРАВИЛ (запретные темы: {scope}; жёсткий минимум):\n"
            + "\n".join(f"- {r}" for r in rules)
        )

    async def _load_allowed_topics_block(self, channel: str = "") -> str:
        """Разрешённые темы и поведение ботов per-канал + базовый пресет Twitch.

        Читает свой список канала (settings-kv ``allowed_topics:<channel>``);
        если у канала его нет — наследует пресет ``allowed_topics_preset``.
        Формат: одно указание/тема на строку, строки с «#» — комментарии.
        """
        try:
            from app.channel_allowed import normalize_channel, resolve_channel_allowed
            raw, source = await resolve_channel_allowed(channel)
            ch = normalize_channel(channel)
        except Exception as exc:  # noqa: BLE001
            logger.debug("allowed topics load: %s", exc)
            return ""
        raw = (raw or "").strip()
        if not raw:
            return ""
        rules = [
            ln.strip() for ln in raw.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if not rules:
            return ""
        scope = f"канал #{ch}" if (source == "channel" and ch) else "базовый пресет Twitch"
        return (
            f"ЧТО РАЗРЕШЕНО И ПООЩРЯЕТСЯ (темы и поведение: {scope}):\n"
            + "\n".join(f"- {r}" for r in rules)
        )

    async def _load_streamer_profile_block(self, account_id: int, channel: str = "") -> str:
        """§5 PLAN_FEEDBACK_2908: компактный блок «О стримере» для промпта.

        Берёт профиль через fallback-цепочку (bot+channel → bot global →
        панельный channel → панельный global). Пустой профиль — пустой блок.
        К3 AUDIT_PLACEMENT: + строка отношения бота к стримеру (может быть
        единственным содержимым блока, если профиль пуст)."""
        try:
            from app.streamer_profile import get_streamer_profile_resolved
            p = await get_streamer_profile_resolved(account_id, channel)

            def _lst(v):
                if isinstance(v, list):
                    return [str(x).strip() for x in v if str(x).strip()]
                if isinstance(v, str) and v.strip():
                    try:
                        parsed = json.loads(v)
                        if isinstance(parsed, list):
                            return [str(x).strip() for x in parsed if str(x).strip()]
                    except Exception:
                        pass
                    return [x.strip() for x in v.split(",") if x.strip()]
                return []

            parts: list[str] = []
            if p:
                if p.get("bio"):
                    parts.append(f"О себе: {p['bio']}")
                if p.get("occupation"):
                    parts.append(f"Занятие: {p['occupation']}")
                if p.get("streaming_style"):
                    parts.append(f"Стиль стрима: {p['streaming_style']}")
                games = _lst(p.get("favorite_games"))
                interests = _lst(p.get("interests"))
                likes = _lst(p.get("likes"))
                if games:
                    parts.append("Игры: " + ", ".join(games[:8]))
                if interests:
                    parts.append("Интересы: " + ", ".join(interests[:8]))
                if likes:
                    parts.append("Любит: " + ", ".join(likes[:6]))
            # К3 AUDIT_PLACEMENT: отношение бота к стримеру (per-bot × per-channel)
            try:
                from app.streamer_attitude import get_attitude, format_attitude_line
                line = format_attitude_line(await get_attitude(account_id, channel))
                if line:
                    parts.append(line)
            except Exception as att_exc:
                logger.debug("streamer attitude line: %s", att_exc)
            if not parts:
                return ""
            return "Контекст о стримере (используй уместно, не перечисляй напрямую):\n- " + "\n- ".join(parts)
        except Exception as exc:
            logger.debug("streamer profile block error: %s", exc)
            return ""

    async def _load_persona_block(self, account_id: int, channel: str = "") -> str:
        """Читает accounts.persona_json и форматирует в блок промпта.

        v12: якщо для каналу є включений channel_override — мерджимо його
        числові поля (humor_level тощо) та observation_only в персону
        перед форматуванням, тобто поведінка бота відрізняється per-channel.
        """
        try:
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT persona_json FROM accounts WHERE id = ?", (account_id,),
                )
                row = await cursor.fetchone()
            finally:
                await db.close()
        except Exception:
            return ""
        if not row:
            return ""
        try:
            raw = row["persona_json"] if "persona_json" in row.keys() else ""
        except Exception:
            raw = ""
        if not raw:
            return ""
        from app.bot_persona import BotPersona, format_extended_persona_for_prompt
        persona = BotPersona.from_json(raw)
        ch = (channel or "").lstrip("#").lower()
        if ch:
            try:
                db = await get_db()
                try:
                    cur = await db.execute(
                        "SELECT overrides_json FROM channel_overrides "
                        "WHERE account_id = ? AND channel = ? AND enabled = 1",
                        (account_id, ch),
                    )
                    ov_row = await cur.fetchone()
                finally:
                    await db.close()
                if ov_row:
                    overrides = json.loads(ov_row["overrides_json"] or "{}")
                    changed = []
                    for k, v in overrides.items():
                        if hasattr(persona, k):
                            setattr(persona, k, v)
                            changed.append(k)
                    if changed:
                        persona.clamp()
                        await ai_log(
                            "channel_override",
                            f"Per-channel persona overrides для #{ch}: {changed}",
                            account_id, ch,
                        )
            except Exception as exc:
                logger.debug("channel override merge error: %s", exc)
        # B5 (REWORK_PLAN): расширенная персона — уровни характера реально идут в промпт
        return format_extended_persona_for_prompt(persona)
