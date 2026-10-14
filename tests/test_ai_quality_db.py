"""v8 integration tests: app/ai_quality_db.py — БД-связки."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _setup(tmp_db, account_ids=(1,)):
    from app import database
    from app import ai_quality_db
    await database.init_db()
    db = await database.get_db()
    for aid in account_ids:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, ?)",
            (aid, f"acc{aid}", "tok"),
        )
    await db.commit()
    return ai_quality_db, database


# ====== KB CRUD ======


async def test_kb_add_list_update_delete(tmp_db):
    aiq, _ = await _setup(tmp_db)
    new_id = await aiq.add_kb(1, "стрим", "стрим начинаю в 19:00", "расписание", priority=8)
    assert new_id > 0

    items = await aiq.list_kb(1)
    assert len(items) == 1
    assert items[0]["topic"] == "стрим"
    assert items[0]["priority"] == 8

    ok = await aiq.update_kb(1, new_id, content="стрим в 20:00", priority=9)
    assert ok is True

    items = await aiq.list_kb(1)
    assert items[0]["content"] == "стрим в 20:00"
    assert items[0]["priority"] == 9

    await aiq.delete_kb(1, new_id)
    items = await aiq.list_kb(1)
    assert items == []


async def test_kb_isolated_per_account(tmp_db):
    aiq, _ = await _setup(tmp_db, account_ids=(1, 2))
    await aiq.add_kb(1, "topic1", "content1")
    await aiq.add_kb(2, "topic2", "content2")
    items1 = await aiq.list_kb(1)
    items2 = await aiq.list_kb(2)
    assert len(items1) == 1
    assert len(items2) == 1
    assert items1[0]["topic"] == "topic1"
    assert items2[0]["topic"] == "topic2"


async def test_kb_retrieve_for_query(tmp_db):
    aiq, _ = await _setup(tmp_db)
    await aiq.add_kb(1, "расписание", "стрим вечером в 19:00 пн-чт")
    await aiq.add_kb(1, "discord", "discord.gg/example")
    await aiq.add_kb(1, "сетап", "i7 12700K + RTX 4080")

    res = await aiq.retrieve_kb_for_query(1, "когда стрим расписание", top_k=2)
    assert len(res) >= 1
    # Должно найти "расписание"
    topics = [r["topic"] for r in res]
    assert "расписание" in topics


async def test_kb_disabled_excluded_from_retrieval(tmp_db):
    aiq, _ = await _setup(tmp_db)
    kb_id = await aiq.add_kb(1, "тест", "тестовый контент про стрим")
    await aiq.update_kb(1, kb_id, enabled=0)
    res = await aiq.retrieve_kb_for_query(1, "стрим тест", top_k=5)
    assert res == []


# ====== Style examples ======


async def test_style_examples_crud(tmp_db):
    aiq, _ = await _setup(tmp_db)
    new_id = await aiq.add_style_example(1, "ну да, харош", channel="streamerchan", note="мой стиль")
    assert new_id > 0
    items = await aiq.list_style_examples(1)
    assert len(items) == 1
    assert items[0]["message"] == "ну да, харош"

    await aiq.delete_style_example(1, new_id)
    assert await aiq.list_style_examples(1) == []


async def test_pick_style_examples_random_subset(tmp_db):
    aiq, _ = await _setup(tmp_db)
    for i in range(5):
        await aiq.add_style_example(1, f"пример {i}")
    picked = await aiq.pick_style_examples(1, count=3)
    assert len(picked) == 3


async def test_style_examples_are_scoped_to_channel_with_global_fallback(tmp_db):
    aiq, _ = await _setup(tmp_db)
    await aiq.add_style_example(1, "alpha style", channel="alpha")
    await aiq.add_style_example(1, "beta style", channel="beta")
    await aiq.add_style_example(1, "global style")

    listed = await aiq.list_style_examples(1, channel="#alpha")
    assert {item["message"] for item in listed} == {"alpha style", "global style"}
    picked = await aiq.pick_style_examples(1, channel="alpha", count=10)
    assert {item["message"] for item in picked} == {"alpha style", "global style"}


# ====== Banned topics ======


async def test_banned_topics_crud(tmp_db):
    aiq, _ = await _setup(tmp_db)
    new_id = await aiq.add_banned_topic(1, "политика", fallback="давайте о игре", mode="fallback")
    items = await aiq.list_banned_topics(1)
    assert len(items) == 1
    assert items[0]["pattern"] == "политика"
    assert items[0]["mode"] == "fallback"

    await aiq.update_banned_topic(1, new_id, mode="silent")
    items = await aiq.list_banned_topics(1)
    assert items[0]["mode"] == "silent"

    await aiq.delete_banned_topic(1, new_id)
    assert await aiq.list_banned_topics(1) == []


async def test_check_banned_topics_db_match(tmp_db):
    aiq, _ = await _setup(tmp_db)
    await aiq.add_banned_topic(1, "политика", fallback="о игре", mode="fallback")
    hit = await aiq.check_banned_topics_db(1, "обсуждаем политика")
    assert hit is not None
    assert hit.fallback == "о игре"


async def test_check_banned_topics_db_no_match(tmp_db):
    aiq, _ = await _setup(tmp_db)
    await aiq.add_banned_topic(1, "spam", mode="silent")
    assert await aiq.check_banned_topics_db(1, "ham") is None


async def test_check_banned_topics_disabled_skipped(tmp_db):
    aiq, _ = await _setup(tmp_db)
    new_id = await aiq.add_banned_topic(1, "spam", mode="silent")
    await aiq.update_banned_topic(1, new_id, enabled=0)
    assert await aiq.check_banned_topics_db(1, "spam spam") is None


# ====== Account-scoped A/B prompt variants ======


async def test_variant_crud(tmp_db):
    aiq, _ = await _setup(tmp_db)
    vid = await aiq.add_variant(1, "A", "промпт A", weight=70)
    assert vid > 0
    items = await aiq.list_variants(1)
    assert len(items) == 1 and items[0]["account_id"] == 1 and items[0]["weight"] == 70
    await aiq.update_variant(1, vid, weight=30)
    assert (await aiq.list_variants(1))[0]["weight"] == 30
    assert await aiq.increment_variant_count(1, vid) is True
    assert (await aiq.list_variants(1))[0]["count"] == 1
    assert await aiq.increment_variant_count(2, vid) is False
    assert (await aiq.list_variants(1))[0]["count"] == 1
    await aiq.delete_variant(1, vid)
    assert await aiq.list_variants(1) == []


async def test_pick_variant_for_account_returns_one(tmp_db):
    aiq, _ = await _setup(tmp_db)
    await aiq.add_variant(1, "A", "promptA", weight=50)
    await aiq.add_variant(1, "B", "promptB", weight=50)
    chosen = await aiq.pick_variant_for_account(1)
    assert chosen is not None and chosen["label"] in ("A", "B")


async def test_pick_variant_for_unknown_account_returns_none(tmp_db):
    aiq, _ = await _setup(tmp_db)
    assert await aiq.pick_variant_for_account(99999) is None


# ====== Feedback ======


async def test_submit_feedback_and_summary(tmp_db):
    aiq, _ = await _setup(tmp_db)
    from app import database
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (1, 'c', 'bot', 'msg', 1)"
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM chat_log LIMIT 1")
        log_id = (await cursor.fetchone())["id"]
    finally:
        await db.close()

    await aiq.submit_feedback(1, log_id, 1, note="хорошо")
    await aiq.submit_feedback(1, log_id, -1, note="плохо")

    res = await aiq.get_feedback_for_log(1, log_id)
    assert res is not None
    assert res["likes"] == 1
    assert res["dislikes"] == 1


async def test_feedback_summary_empty(tmp_db):
    aiq, _ = await _setup(tmp_db)
    summary = await aiq.feedback_summary(account_id=1, days=30)
    # Должен возвращать структуру даже если пусто
    assert isinstance(summary, dict)


async def test_feedback_bumps_variant_stats(tmp_db):
    aiq, _ = await _setup(tmp_db)
    from app import database
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (1, 'c', 'bot', 'm', 1)"
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM chat_log LIMIT 1")
        log_id = (await cursor.fetchone())["id"]
    finally:
        await db.close()

    vid = await aiq.add_variant(1, "A", "promptA", weight=50)
    await aiq.submit_feedback(1, log_id, 1, prompt_variant_id=vid)

    items = await aiq.list_variants(1)
    assert items[0]["likes"] == 1


async def test_row_mutations_reject_foreign_account(tmp_db):
    aiq, _ = await _setup(tmp_db, account_ids=(1, 2))
    kb_id = await aiq.add_kb(1, "owned", "content")
    style_id = await aiq.add_style_example(1, "owned style")
    topic_id = await aiq.add_banned_topic(1, "owned topic")
    variant_id = await aiq.add_variant(1, "A", "owned prompt")

    assert await aiq.update_kb(2, kb_id, content="stolen") is False
    assert await aiq.delete_kb(2, kb_id) is False
    assert await aiq.delete_style_example(2, style_id) is False
    assert await aiq.update_banned_topic(2, topic_id, pattern="stolen") is False
    assert await aiq.delete_banned_topic(2, topic_id) is False
    assert await aiq.update_variant(2, variant_id, system_prompt="stolen") is False
    assert await aiq.delete_variant(2, variant_id) is False

    assert (await aiq.list_kb(1))[0]["content"] == "content"
    assert (await aiq.list_style_examples(1))[0]["message"] == "owned style"
    assert (await aiq.list_banned_topics(1))[0]["pattern"] == "owned topic"
    assert (await aiq.list_variants(1))[0]["system_prompt"] == "owned prompt"


async def test_feedback_rejects_foreign_log_and_variant(tmp_db):
    aiq, database = await _setup(tmp_db, account_ids=(1, 2))
    db = await database.get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) "
            "VALUES (1, 'c', 'bot', 'owned', 1)"
        )
        await db.commit()
        log_id = cursor.lastrowid
    finally:
        await db.close()
    variant_id = await aiq.add_variant(1, "A", "owned prompt")

    assert await aiq.submit_feedback(2, log_id, 1) == 0
    assert await aiq.submit_feedback(1, log_id, 1, prompt_variant_id=await aiq.add_variant(2, "B", "foreign")) == 0
    assert await aiq.get_feedback_for_log(2, log_id) is None
    assert await aiq.get_feedback_for_log(1, log_id) == {"likes": 0, "dislikes": 0}
    assert (await aiq.list_variants(1))[0]["likes"] == 0
    assert (await aiq.list_variants(1))[0]["id"] == variant_id


# ====== Conversation memory ======


async def test_fetch_recent_channel_msgs(tmp_db):
    aiq, _ = await _setup(tmp_db)
    from app import database
    db = await database.get_db()
    try:
        for i in range(5):
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (1, 'streamer', ?, ?, 0)",
                (f"user{i}", f"msg{i}"),
            )
        await db.commit()
    finally:
        await db.close()
    msgs = await aiq.fetch_recent_channel_msgs(1, "streamer", limit=3)
    assert len(msgs) == 3
    # Возвращаем в порядке от старых к новым (после reversed)
    assert msgs[-1].message == "msg4"


async def test_fetch_user_bot_pairs(tmp_db):
    aiq, _ = await _setup(tmp_db)
    from app import database
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (1, 'c', 'alice', 'Q1', 0)"
        )
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (1, 'c', 'bot', 'A1', 1)"
        )
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (1, 'c', 'alice', 'Q2', 0)"
        )
        await db.execute(
            "INSERT INTO chat_log (account_id, channel, author, message, is_bot) VALUES (1, 'c', 'bot', 'A2', 1)"
        )
        await db.commit()
    finally:
        await db.close()

    pairs = await aiq.fetch_user_bot_pairs(1, "c", "alice", limit_pairs=5)
    assert len(pairs) == 2
    assert pairs[0][0].message == "Q1"
    assert pairs[0][1].message == "A1"


async def test_build_full_conversation_context_empty(tmp_db):
    aiq, _ = await _setup(tmp_db)
    block = await aiq.build_full_conversation_context(1, "empty_channel")
    assert block == ""


async def test_classify_message_db_basic(tmp_db):
    aiq, _ = await _setup(tmp_db)
    decision = await aiq.classify_message_db(
        1, "channel", "Эй botName, привет!", bot_nickname="botName", min_confidence=0.4
    )
    assert decision.should_reply is True


async def test_classify_message_db_with_trigger(tmp_db):
    aiq, _ = await _setup(tmp_db)
    from app import database
    db = await database.get_db()
    try:
        await db.execute(
            "INSERT INTO triggers (account_id, keyword, response, use_ai, enabled) VALUES (1, 'дота', '', 0, 1)"
        )
        await db.commit()
    finally:
        await db.close()

    decision = await aiq.classify_message_db(
        1, "c", "когда патч в дота?", min_confidence=0.4
    )
    assert decision.should_reply is True


# ====== Topic cooldown ======


async def test_topic_cooldown_no_recent(tmp_db):
    aiq, _ = await _setup(tmp_db)
    res = await aiq.check_topic_cooldown(1, "c", "новый патч в доте 2 наконец вышел")
    assert res is None


async def test_topic_cooldown_records_and_detects_overlap(tmp_db):
    aiq, _ = await _setup(tmp_db)
    await aiq.record_bot_topic(1, "c", "новый патч в доте обсуждаем сейчас")
    res = await aiq.check_topic_cooldown(1, "c", "патч в доте классный сегодня", min_shared=2)
    # Темы пересекаются (патч/доте)
    assert res is not None
    assert "патч" in res["topic"] or "доте" in res["topic"]


async def test_topic_cooldown_different_topic_passes(tmp_db):
    aiq, _ = await _setup(tmp_db)
    await aiq.record_bot_topic(1, "c", "патч в доте 2 крутой")
    res = await aiq.check_topic_cooldown(1, "c", "пицца с грибами вкуснее")
    assert res is None


async def test_record_bot_topic_empty_text(tmp_db):
    aiq, _ = await _setup(tmp_db)
    # Не должно крашнуться
    await aiq.record_bot_topic(1, "c", "")
    res = await aiq.check_topic_cooldown(1, "c", "test")
    assert res is None
