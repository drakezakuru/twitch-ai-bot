"""Q03: база правил модерации per-канал + пресет Twitch.

Модель по DEC-OWNER-004: у канала свой редактируемый список (moderation_channel_rules,
per-канал, НЕ глобальная таблица), канал стартует из пресета Twitch; база применяется
движком только ботам с ролью «модератор»; per-бот правило с тем же паттерном
переопределяет базу.
"""
from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import database
from app import moderation as M
from app.routes_modpanel import router as modpanel_router  # noqa: F401 (регистрирует эндпоинты)
import app.routes as routes_module  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_db, disable_auth):
    M.invalidate_cache()
    await database.init_db()
    yield
    M.invalidate_cache()


async def _make_bot(nickname: str = "bot1", bot_role: str = "chatter", **cols) -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO accounts (nickname, token, bot_role) VALUES (?, ?, ?)",
            (nickname, "oauth:tok", bot_role),
        )
        await db.commit()
        aid = cur.lastrowid
        sets = {"moderation_mode": "full", "moderation_can_timeout": 1, **cols}
        assignments = ", ".join(f"{k} = ?" for k in sets)
        await db.execute(f"UPDATE accounts SET {assignments} WHERE id = ?", (*sets.values(), aid))
        await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    return aid


async def _add_bot_rule(aid: int, pattern: str, *, action: str = "block",
                        action_ext=None, category: str = "insult") -> int:
    db = await database.get_db()
    try:
        cur = await db.execute(
            "INSERT INTO moderation_rules (account_id, channel, pattern, category, action, "
            "severity, enabled, action_ext) VALUES (?, ?, ?, ?, ?, 3, 1, ?)",
            (aid, "", pattern, category, action, action_ext),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()
        M.invalidate_cache(aid)


def _client() -> AsyncClient:
    from fastapi import FastAPI
    import app.routes_modpanel  # noqa: F401 — декорирует router из app.routes
    from app.routes import router
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─────────────────────────── схема и API ───────────────────────────


async def test_base_rules_table_created_by_init_db():
    db = await database.get_db()
    try:
        cur = await db.execute("PRAGMA table_info(moderation_channel_rules)")
        cols = {row["name"] for row in await cur.fetchall()}
        cur = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='moderation_channel_rules'"
        )
        sql = (await cur.fetchone())["sql"]
    finally:
        await db.close()
    assert {"channel", "pattern", "category", "action", "severity", "action_ext", "enabled"} <= cols
    assert "UNIQUE" in sql, "идемпотентный засев пресета опирается на UNIQUE(channel, pattern)"


async def test_api_crud_and_seed_roundtrip():
    async with _client() as c:
        r = await c.get("/api/moderation/twitch-preset")
        assert r.json()["ok"] is True
        preset_rules = r.json()["rules"]
        assert len(preset_rules) >= 5, "в пресете Twitch есть базовые запреты"

        r = await c.post("/api/moderation/base-rules", json={
            "channel": "#Chan", "pattern": "капслослово", "category": "insult",
            "action": "block", "severity": 3, "action_ext": "timeout_3600",
        })
        assert r.json()["ok"] is True

        r = await c.get("/api/moderation/base-rules?channel=chan")
        rules = r.json()["rules"]
        assert len(rules) == 1 and rules[0]["action_ext"] == "timeout_3600"
        rule_id = rules[0]["id"]

        r = await c.put(f"/api/moderation/base-rules/{rule_id}", json={"enabled": False})
        assert r.json()["ok"] is True
        r = await c.get("/api/moderation/base-rules?channel=chan")
        assert r.json()["rules"][0]["enabled"] == 0

        r = await c.delete(f"/api/moderation/base-rules/{rule_id}")
        assert r.json()["ok"] is True
        r = await c.get("/api/moderation/base-rules?channel=chan")
        assert r.json()["rules"] == []


async def test_api_rejects_bad_action_ext_and_empty_channel():
    async with _client() as c:
        r = await c.post("/api/moderation/base-rules", json={
            "channel": "", "pattern": "слово", "action": "block",
        })
        assert r.json()["ok"] is False

        r = await c.post("/api/moderation/base-rules", json={
            "channel": "chan", "pattern": "слово", "action": "block", "action_ext": "banana",
        })
        assert r.json()["ok"] is False
        assert "Расширенное действие" in r.json()["error"]


async def test_seed_from_preset_is_idempotent():
    async with _client() as c:
        r = await c.post("/api/moderation/base-rules/seed", json={"channel": "test_channel"})
        assert r.json()["ok"] is True
        first = r.json()["added"]
        assert first > 0, "пресет непустой — при первом засеве что-то добавилось"

        r = await c.post("/api/moderation/base-rules/seed", json={"channel": "#TEST_CHANNEL"})
        assert r.json()["added"] == 0, "повторный засев ничего не дублирует"

        r = await c.get("/api/moderation/base-rules?channel=test_channel")
        assert len(r.json()["rules"]) == first


async def test_seed_from_russian_preset():
    async with _client() as c:
        r = await c.post("/api/moderation/base-rules/seed", json={"channel": "ruchan", "preset": "ru"})
        assert r.json()["ok"] is True
        added = r.json()["added"]
        assert added >= 20, "русский пресет содержит больше 20 правил"

        rules_res = await c.get("/api/moderation/base-rules?channel=ruchan")
        rules = rules_res.json()["rules"]
        patterns = [x["pattern"] for x in rules]
        assert any("негр" in p for p in patterns)
        assert any("убью" in p for p in patterns)
        assert any("казино" in p for p in patterns)



# ─────────────────────────── движок ───────────────────────────


async def test_moderator_bot_punishes_by_channel_base_rule():
    aid = await _make_bot("modbot", bot_role="moderator")
    async with _client() as c:
        await c.post("/api/moderation/base-rules", json={
            "channel": "chan", "pattern": "каналслово", "category": "insult",
            "action": "block", "severity": 3, "action_ext": "timeout_86400",
        })

    verdicts = await M.check_message(aid, "#Chan", "spammer", "ну ты каналслово")

    assert verdicts[0].action == "timeout"
    assert verdicts[0].duration_sec == 86400
    assert verdicts[0].rule_name.startswith("base:")


async def test_non_moderator_bot_ignores_channel_base():
    """Ключевое требование Q03: не-модератор бот по базе канала не наказывает."""
    aid = await _make_bot("chatty", bot_role="chatter")
    async with _client() as c:
        await c.post("/api/moderation/base-rules", json={
            "channel": "chan", "pattern": "каналслово", "category": "insult",
            "action": "block", "severity": 3,
        })

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты каналслово")

    assert verdicts == []


async def test_bot_rule_with_same_pattern_overrides_base():
    aid = await _make_bot("modbot", bot_role="moderator")
    async with _client() as c:
        await c.post("/api/moderation/base-rules", json={
            "channel": "chan", "pattern": "общеслово", "category": "insult",
            "action": "block", "severity": 3,
        })
    await _add_bot_rule(aid, "общеслово", action="block", action_ext="ban")

    verdicts = await M.check_message(aid, "chan", "spammer", "ну ты общеслово")

    assert len(verdicts) == 1, "базовый дубликат не даёт второй вердикт"
    assert verdicts[0].action == "ban", "per-бот правило переопределяет базу"
    assert not verdicts[0].rule_name.startswith("base:")


async def test_base_rules_are_per_channel():
    aid = await _make_bot("modbot", bot_role="moderator")
    async with _client() as c:
        await c.post("/api/moderation/base-rules", json={
            "channel": "chan_a", "pattern": "толькоздесь", "category": "spam",
            "action": "block", "severity": 3,
        })

    verdicts_a = await M.check_message(aid, "chan_a", "spammer", "толькоздесь")
    verdicts_b = await M.check_message(aid, "chan_b", "spammer", "толькоздесь")

    assert len(verdicts_a) == 1
    assert verdicts_b == []


async def test_disabled_base_rule_not_applied():
    aid = await _make_bot("modbot", bot_role="moderator")
    async with _client() as c:
        await c.post("/api/moderation/base-rules", json={
            "channel": "chan", "pattern": "выключено", "category": "spam",
            "action": "block", "severity": 3,
        })
        r = await c.get("/api/moderation/base-rules?channel=chan")
        rule_id = r.json()["rules"][0]["id"]
        await c.put(f"/api/moderation/base-rules/{rule_id}", json={"enabled": False})

    verdicts = await M.check_message(aid, "chan", "spammer", "выключено")

    assert verdicts == []


async def test_preset_seeded_channel_punishes_right_away():
    """«Канал со свежим пресетом наказывает по нему» — сценарий готово-когда."""
    aid = await _make_bot("modbot", bot_role="moderator")
    async with _client() as c:
        r = await c.get("/api/moderation/twitch-preset")
        preset = r.json()["rules"]
        await c.post("/api/moderation/base-rules/seed", json={"channel": "fresh"})

    # берём паттерн из пресета, который реально матчится стемом (не re:)
    plain = [r for r in preset if not r["pattern"].startswith("re:")]
    assert plain, "в пресете есть стем-паттерны"
    word = plain[0]["pattern"]

    verdicts = await M.check_message(aid, "fresh", "spammer", word)

    assert verdicts, "свежий канал с пресетом наказывает по нему"
    assert verdicts[0].rule_name.startswith("base:")


async def test_base_rules_export():
    """Экспорт правил канала отдаёт валидный JSON со списком правил."""
    async with _client() as c:
        await c.post("/api/moderation/base-rules", json={
            "channel": "myexport", "pattern": "слово1", "category": "custom", "action": "block", "severity": 3,
        })
        await c.post("/api/moderation/base-rules", json={
            "channel": "myexport", "pattern": "слово2", "category": "insult", "action": "timeout", "severity": 4,
        })

        r = await c.get("/api/moderation/base-rules/export?channel=myexport")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        assert "mod-rules-myexport.json" in r.headers.get("content-disposition", "")
        data = r.json()
        assert data["channel"] == "myexport"
        assert data["count"] == 2
        assert len(data["rules"]) == 2
        patterns = [x["pattern"] for x in data["rules"]]
        assert "слово1" in patterns and "слово2" in patterns


async def test_base_rules_import():
    """Импорт правил из JSON и списка строк корректно сохраняет их в БД канала."""
    async with _client() as c:
        payload = {
            "channel": "myimport",
            "rules": [
                {"pattern": "запрет1", "category": "custom", "action": "block", "severity": 3},
                {"pattern": "запрет2", "category": "hate", "action": "timeout", "severity": 5},
                "простое_слово",
            ],
        }
        r = await c.post("/api/moderation/base-rules/import", json=payload)
        assert r.status_code == 200
        res = r.json()
        assert res["ok"] is True
        assert res["imported"] == 3

        # Проверяем, что правила теперь в базе
        list_res = await c.get("/api/moderation/base-rules?channel=myimport")
        assert list_res.status_code == 200
        db_rules = list_res.json()["rules"]
        assert len(db_rules) == 3
        patterns = {x["pattern"] for x in db_rules}
        assert {"запрет1", "запрет2", "простое_слово"} <= patterns


async def test_base_rules_clear():
    """Очистка всех правил канала удаляет только правила этого канала."""
    async with _client() as c:
        # Добавляем правила для двух каналов
        await c.post("/api/moderation/base-rules", json={
            "channel": "ch_to_clear", "pattern": "слово_а", "category": "custom", "action": "block", "severity": 3,
        })
        await c.post("/api/moderation/base-rules", json={
            "channel": "ch_to_clear", "pattern": "слово_б", "category": "custom", "action": "block", "severity": 3,
        })
        await c.post("/api/moderation/base-rules", json={
            "channel": "ch_to_keep", "pattern": "слово_сохранить", "category": "custom", "action": "block", "severity": 3,
        })

        # Очищаем правила первого канала
        r = await c.delete("/api/moderation/base-rules/clear?channel=ch_to_clear")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["deleted"] == 2

        # Проверяем, что у ch_to_clear правил 0
        r_cleared = await c.get("/api/moderation/base-rules?channel=ch_to_clear")
        assert len(r_cleared.json()["rules"]) == 0

        # Проверяем, что у ch_to_keep правило осталось
        r_kept = await c.get("/api/moderation/base-rules?channel=ch_to_keep")
        assert len(r_kept.json()["rules"]) == 1


async def test_base_rules_bulk_toggle():
    """Массовое включение и выключение всех правил канала."""
    async with _client() as c:
        # Добавляем 2 правила
        await c.post("/api/moderation/base-rules", json={
            "channel": "ch_bulk", "pattern": "слово_1", "category": "custom", "action": "block", "severity": 3,
        })
        await c.post("/api/moderation/base-rules", json={
            "channel": "ch_bulk", "pattern": "слово_2", "category": "custom", "action": "block", "severity": 3,
        })

        # Выключаем все
        r_off = await c.post("/api/moderation/base-rules/bulk-toggle", json={
            "channel": "ch_bulk", "enabled": False,
        })
        assert r_off.status_code == 200
        data_off = r_off.json()
        assert data_off["ok"] is True
        assert data_off["updated"] == 2
        assert data_off["enabled"] is False

        # Проверяем статус в списке
        r_list = await c.get("/api/moderation/base-rules?channel=ch_bulk")
        rules = r_list.json()["rules"]
        assert len(rules) == 2
        assert all(r["enabled"] == 0 for r in rules)

        # Включаем все обратно
        r_on = await c.post("/api/moderation/base-rules/bulk-toggle", json={
            "channel": "ch_bulk", "enabled": True,
        })
        assert r_on.status_code == 200
        data_on = r_on.json()
        assert data_on["ok"] is True
        assert data_on["updated"] == 2
        assert data_on["enabled"] is True

        r_list2 = await c.get("/api/moderation/base-rules?channel=ch_bulk")
        rules2 = r_list2.json()["rules"]
        assert all(r["enabled"] == 1 for r in rules2)


async def test_bot_rules_bulk_toggle():
    """Массовое включение и выключение всех правил бота."""
    aid = await _make_bot("test_mod_bot", bot_role="moderator")
    await _add_bot_rule(aid, "правило_1")
    await _add_bot_rule(aid, "правило_2")

    async with _client() as c:
        # Выключаем все правила бота
        r_off = await c.post(f"/api/accounts/{aid}/moderation/rules/bulk-toggle", json={"enabled": False})
        assert r_off.status_code == 200
        data_off = r_off.json()
        assert data_off["ok"] is True
        assert data_off["updated"] == 2
        assert data_off["enabled"] is False

        r_list = await c.get(f"/api/accounts/{aid}/moderation/rules")
        rules = r_list.json()["rules"]
        assert len(rules) == 2
        assert all(r["enabled"] == 0 for r in rules)

        # Включаем все правила бота
        r_on = await c.post(f"/api/accounts/{aid}/moderation/rules/bulk-toggle", json={"enabled": True})
        assert r_on.status_code == 200
        data_on = r_on.json()
        assert data_on["ok"] is True
        assert data_on["updated"] == 2
        assert data_on["enabled"] is True

        r_list2 = await c.get(f"/api/accounts/{aid}/moderation/rules")
        rules2 = r_list2.json()["rules"]
        assert all(r["enabled"] == 1 for r in rules2)


async def test_moderation_sandbox_test_phrase():
    """Песочница модерации проверяет фразу без применения реального наказания."""
    aid = await _make_bot("sandbox_bot", bot_role="moderator")
    await _add_bot_rule(aid, "запретное_слово", action="block")

    async with _client() as c:
        # Добавляем также базовое правило канала
        await c.post("/api/moderation/base-rules", json={
            "channel": "sandbox_chan", "pattern": "базовый_бан", "category": "insult", "action": "timeout", "severity": 4,
        })

        # 1. Чистая фраза
        r_clean = await c.post("/api/moderation/test", json={
            "text": "Привет, отличный стрим!", "channel": "sandbox_chan", "account_id": aid,
        })
        assert r_clean.status_code == 200
        data_clean = r_clean.json()
        assert data_clean["ok"] is True
        assert data_clean["matched"] is False
        assert len(data_clean["verdicts"]) == 0

        # 2. Фраза с правилом бота
        r_bot = await c.post("/api/moderation/test", json={
            "text": "Тут есть запретное_слово в тексте", "channel": "sandbox_chan", "account_id": aid,
        })
        assert r_bot.status_code == 200
        data_bot = r_bot.json()
        assert data_bot["ok"] is True
        assert data_bot["matched"] is True
        assert data_bot["primary_verdict"]["rule_name"] == "запретное_слово"
        assert data_bot["primary_verdict"]["match"] == "запретное_слово"

        # 3. Фраза с правилом канала (без указания account_id)
        r_chan = await c.post("/api/moderation/test", json={
            "text": "Вот тебе базовый_бан за спам", "channel": "sandbox_chan",
        })
        assert r_chan.status_code == 200
        data_chan = r_chan.json()
        assert data_chan["ok"] is True
        assert data_chan["matched"] is True
        assert data_chan["primary_verdict"]["rule_name"] == "базовый_бан"
