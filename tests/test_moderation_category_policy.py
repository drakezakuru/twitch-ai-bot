"""Q02: политика «категория → действие» в роли «модератор» — применение движком.

Политика хранится в accounts.role_config_json (moderator.category_policy) и применяется
в check_message поверх severity-лестницы. Явное действие правила (action_ext из Q01)
важнее политики роли. Режимы (log_only и т.п.) деградируют политику как обычно.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio

from app import database
from app import moderation as M

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_db, disable_auth):
    M.invalidate_cache()
    await database.init_db()
    yield
    M.invalidate_cache()


async def _make_moderator(category_policy: dict | None = None, **cols) -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO accounts (nickname, token, bot_role, role_config_json) "
            "VALUES (?, ?, 'moderator', ?)",
            ("bot1", "oauth:tok", "{}"),
        )
        await db.commit()
        aid = cur.lastrowid
        sets = {"moderation_mode": "full", "moderation_can_timeout": 1, **cols}
        assignments = ", ".join(f"{k} = ?" for k in sets)
        await db.execute(
            f"UPDATE accounts SET {assignments} WHERE id = ?", (*sets.values(), aid)
        )
        if category_policy is not None:
            await db.execute(
                "UPDATE accounts SET role_config_json = ? WHERE id = ?",
                (json.dumps({"moderator": {"category_policy": category_policy}}), aid),
            )
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    return aid


async def _add_rule(aid: int, pattern: str = "плохослово", *, action: str = "block",
                    severity: int = 3, action_ext=None, category: str = "insult") -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_rules (account_id, channel, pattern, category, action, "
            "severity, enabled, action_ext) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (aid, "", pattern, category, action, severity, action_ext),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()
        M.invalidate_cache(aid)


async def test_policy_overrides_severity_ladder_for_custom_rule():
    """Правило «block sev3» + политика insult→«таймаут 1 день» = таймаут 86400."""
    aid = await _make_moderator({"insult": "timeout_86400"})
    await _add_rule(aid, category="insult")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    v = verdicts[0]
    assert v.action == "timeout"
    assert v.duration_sec == 86400
    assert v.action_ext == "timeout_86400"


async def test_policy_applies_to_builtin_dictionary_verdicts():
    """Встроенные словари не имеют action_ext — политика роль-левел применяется напрямую."""
    aid = await _make_moderator({"hate": "ban"})
    from app.moderation import builtin_rules
    hate_rules = [r for r in builtin_rules() if r.category == "hate"]
    assert hate_rules, "во встроенных словарях есть hate-правила"
    word = hate_rules[0].pattern

    verdicts = await M.check_message(aid, "chan", "spammer", word)

    assert verdicts[0].action == "ban"


async def test_explicit_rule_action_ext_beats_role_policy():
    """Явное действие правила (маска) важнее политики роли (бан)."""
    aid = await _make_moderator({"insult": "ban"})
    await _add_rule(aid, action_ext="mask")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "replace"
    assert verdicts[0].masked_text is not None


async def test_empty_or_unknown_policy_value_keeps_ladder():
    aid = await _make_moderator({"insult": ""})
    await _add_rule(aid)

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "block"
    assert verdicts[0].action_ext == ""


async def test_garbage_policy_value_is_normalized_away():
    """Опечатка в значении не должна ни ломать движок, ни менять поведение."""
    aid = await _make_moderator({"insult": "banana"})

    policy = await M.get_category_policy(aid)
    assert policy == {}
    await _add_rule(aid)
    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")
    assert verdicts[0].action == "block"


async def test_policy_only_for_configured_categories():
    aid = await _make_moderator({"hate": "ban"})
    await _add_rule(aid, category="insult")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "block"


async def test_policy_degrades_in_log_only_mode():
    aid = await _make_moderator({"insult": "ban"}, moderation_mode="log_only")
    await _add_rule(aid)

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "log"


async def test_bot_without_policy_stays_on_ladder():
    """Бот без role_config (или не-модератор) — прежнее поведение."""
    aid = await _make_moderator(None)
    await _add_rule(aid)

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")

    assert verdicts[0].action == "block"


async def test_policy_ban_reaches_maybe_punish_via_verdict():
    """Политика → вердикт ban → maybe_punish зовёт Helix-бан (POST без duration)."""
    aid = await _make_moderator({"insult": "ban"})
    await _add_rule(aid)

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты плохослово")
    assert verdicts[0].action == "ban"

    # предохранитель: спаммер не защищён, но без токена наказание skipped,
    # а с токеном и рубильником — применилось бы. Проверяем стык контрактов:
    status = await M.maybe_punish(aid, "chan", "spammer", verdicts[0], token="", bot_nickname="bot1")
    assert status == M.PUNISH_SKIPPED


async def test_normalize_action_ext_canonical_keys():
    assert M.normalize_action_ext(None) == ""
    assert M.normalize_action_ext("") == ""
    assert M.normalize_action_ext("auto") == ""
    assert M.normalize_action_ext("BAN") == "ban"
    assert M.normalize_action_ext("timeout_86400") == "timeout_86400"
    assert M.normalize_action_ext("banana") == ""
