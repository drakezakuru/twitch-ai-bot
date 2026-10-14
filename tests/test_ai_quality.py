"""v8 unit tests: чистые функции из app/ai_quality.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ai_quality import (
    BannedTopicHit,
    ChatMsg,
    ClassifierDecision,
    FilterReport,
    HallucinationCheck,
    build_conversation_block,
    check_banned_topics,
    check_hallucination,
    classify_message,
    decay_facts,
    extract_topic_tokens,
    filter_output_heuristic,
    format_facts_for_prompt,
    format_few_shot_block,
    format_kb_block,
    merge_fact,
    normalize_fact_entry,
    pick_variant,
    retrieve_kb,
    score_kb_entry,
    topics_overlap,
    variant_score,
)


# ====== conversation_memory ======


def test_chatmsg_to_line_user_and_bot():
    user_msg = ChatMsg(author="alice", message="привет", is_bot=False)
    bot_msg = ChatMsg(author="botName", message="прив", is_bot=True)
    assert "alice: привет" in user_msg.to_line()
    assert "🤖" in bot_msg.to_line()


def test_build_conversation_block_empty():
    assert build_conversation_block([]) == ""


def test_build_conversation_block_only_channel():
    msgs = [ChatMsg("a", "msg1", False), ChatMsg("b", "msg2", False)]
    block = build_conversation_block(msgs)
    assert "Последние сообщения чата" in block
    assert "msg1" in block
    assert "msg2" in block
    assert "История твоих ответов" not in block


def test_build_conversation_block_with_pairs():
    chan = [ChatMsg("a", "общий чат", False)]
    pairs = [
        (ChatMsg("alice", "Q1", False), ChatMsg("bot", "A1", True)),
    ]
    block = build_conversation_block(chan, pairs)
    assert "общий чат" in block
    assert "Q1" in block
    assert "A1" in block


def test_build_conversation_block_caps_at_max():
    msgs = [ChatMsg("u", f"msg{i}", False) for i in range(20)]
    block = build_conversation_block(msgs, max_channel=5)
    # Только последние 5 должны быть
    assert "msg15" in block
    assert "msg19" in block
    assert "msg14" not in block


# ====== pre_classifier ======


def test_classify_empty_message():
    d = classify_message("")
    assert d.should_reply is False
    assert d.confidence == 0.0


def test_classify_explicit_mention():
    d = classify_message("Эй botName, привет!", bot_nickname="botName", min_confidence=0.4)
    assert d.should_reply is True
    assert d.confidence >= 0.4
    assert "mention" in d.reason


def test_classify_question_alone_below_threshold():
    d = classify_message("кто-нибудь живой?", min_confidence=0.4)
    # Только вопрос даёт +0.25, ниже порога 0.4
    assert d.confidence < 0.4
    assert d.should_reply is False


def test_classify_question_plus_trigger():
    d = classify_message("когда стрим?", trigger_keywords=["стрим"], min_confidence=0.4)
    # 0.25 + 0.30 = 0.55
    assert d.should_reply is True
    assert d.confidence >= 0.4


def test_classify_require_mention_blocks_others():
    d = classify_message("привет всем!", bot_nickname="bot", require_mention=True)
    assert d.should_reply is False


def test_classify_long_chat_gap_helps():
    d_no_gap = classify_message("чо там по доте", trigger_keywords=["дот"], min_confidence=0.5)
    d_with_gap = classify_message("чо там по доте", trigger_keywords=["дот"],
                                   seconds_since_last_chat_msg=120, chat_gap_threshold=30,
                                   min_confidence=0.5)
    assert d_with_gap.confidence > d_no_gap.confidence


def test_classify_too_short_penalty():
    d = classify_message("?", min_confidence=0.1)
    # Только вопрос (4-) и слишком короткое — итог должен быть низкий
    assert d.confidence < 0.25 + 0.001  # либо 0 (т.к. <4 символа) или с штрафом


def test_classify_only_url_penalty():
    d = classify_message("https://example.com/x", min_confidence=0.0)
    assert "only_url" in d.reason


def test_classifier_decision_dataclass_fields():
    d = ClassifierDecision(should_reply=True, confidence=0.7, reason="mention")
    assert d.should_reply is True
    assert d.confidence == 0.7
    assert d.reason == "mention"


# ====== topic extractor ======


def test_extract_topic_tokens_basic():
    tokens = extract_topic_tokens("новый патч в Доте 2 наконец-то вышел")
    # все стоп-слова должны быть выброшены
    assert "новый" in tokens or "патч" in tokens
    assert "и" not in tokens
    assert "в" not in tokens
    assert len(tokens) <= 3


def test_extract_topic_tokens_empty():
    assert extract_topic_tokens("") == []
    assert extract_topic_tokens("  ") == []


def test_extract_topic_tokens_only_stopwords():
    # Все слова — стоп-слова
    assert extract_topic_tokens("и в на") == []


def test_topics_overlap_match():
    assert topics_overlap(["патч", "дота", "новый"], ["патч", "дота"], min_shared=2) is True


def test_topics_overlap_no_match():
    assert topics_overlap(["патч", "дота"], ["перец", "соль"]) is False


def test_topics_overlap_empty():
    assert topics_overlap([], ["патч"]) is False
    assert topics_overlap(["патч"], []) is False


# ====== banned_topics ======


def test_check_banned_topics_keyword_match():
    banned = [{"id": 1, "pattern": "политика", "fallback": "давайте о игре", "mode": "fallback", "enabled": 1}]
    hit = check_banned_topics("обсуждаем политика страны", banned)
    assert hit is not None
    assert hit.pattern_id == 1
    assert hit.fallback == "давайте о игре"


def test_check_banned_topics_multi_keyword_all_must_match():
    banned = [{"id": 2, "pattern": "стример;кринж", "fallback": "", "mode": "silent", "enabled": 1}]
    # Только одно слово — не триггер
    assert check_banned_topics("стример классный", banned) is None
    # Оба — триггер
    hit = check_banned_topics("стример какой-то кринж", banned)
    assert hit is not None


def test_check_banned_topics_regex():
    banned = [{"id": 3, "pattern": "re:\\bзапрет\\w*\\b", "fallback": "", "mode": "silent", "enabled": 1}]
    hit = check_banned_topics("это запретное слово", banned)
    assert hit is not None


def test_check_banned_topics_disabled_skipped():
    banned = [{"id": 1, "pattern": "spam", "fallback": "", "mode": "silent", "enabled": 0}]
    assert check_banned_topics("spam spam spam", banned) is None


def test_check_banned_topics_empty_text():
    banned = [{"id": 1, "pattern": "x", "enabled": 1}]
    assert check_banned_topics("", banned) is None


def test_check_banned_topics_invalid_regex_skipped():
    banned = [{"id": 1, "pattern": "re:[invalid(", "enabled": 1}]
    # Не должно крашнуться, просто пропустить
    assert check_banned_topics("test", banned) is None


# ====== hallucination_guard ======


def test_check_hallucination_no_phrases_safe():
    res = check_hallucination("Привет, как дела?")
    assert res.safe is True
    assert res.matches == []


def test_check_hallucination_phrase_no_evidence_strict_cuts():
    res = check_hallucination("Помнишь, ты сказал что любишь Доту? Привет!", strict=True)
    assert res.safe is False
    assert any("ты сказал" in m.lower() for m in res.matches)
    # Удалено как минимум одно предложение с галлюцинацией
    assert "ты сказал" not in res.cleaned_text.lower()


def test_check_hallucination_with_evidence_safe():
    res = check_hallucination(
        "Помнишь, ты говорил что играешь в Доту?",
        user_facts=["играет в Доту регулярно"],
    )
    # Есть facts → не вырезаем
    assert res.matches  # фразы найдены, но safe потому что есть evidence
    assert res.safe is True


def test_check_hallucination_empty_input():
    res = check_hallucination("")
    assert res.safe is True


def test_check_hallucination_english_phrases():
    res = check_hallucination("Yesterday you said you would play CS?", strict=True)
    assert res.matches
    assert res.safe is False


# ====== output_filter ======


def test_filter_output_normal_text_safe():
    r = filter_output_heuristic("Обычный ответ нормальной длины.")
    assert r.safe is True
    assert r.suggested == "Обычный ответ нормальной длины."


def test_filter_output_empty():
    r = filter_output_heuristic("")
    assert r.safe is False
    assert r.suggested == ""


def test_filter_output_too_long_trims():
    long_text = "x" * 600
    r = filter_output_heuristic(long_text, max_length=100)
    # trimmed — soft, всё ещё safe
    assert r.safe is True
    assert "trimmed" in r.reasons
    assert len(r.suggested) <= 100


def test_filter_output_caps_lowercased():
    r = filter_output_heuristic("ЭТО ПОЛНОСТЬЮ КАПС-СООБЩЕНИЕ ОЧЕНЬ ДЛИННОЕ", max_caps_pct=0.5)
    assert any("caps" in x for x in r.reasons)
    assert r.suggested != "ЭТО ПОЛНОСТЬЮ КАПС-СООБЩЕНИЕ ОЧЕНЬ ДЛИННОЕ"


def test_filter_output_short_caps_allowed():
    # Короткое сообщение (<=12 letters) с капсом — не триггерит
    r = filter_output_heuristic("LOL OMG")
    assert r.safe is True


def test_filter_output_links_stripped_when_forbid():
    r = filter_output_heuristic("посмотри https://example.com/x", forbid_links=True)
    assert "links_stripped" in r.reasons
    assert "[ссылка]" in r.suggested
    assert r.safe is True


def test_filter_output_slur_blocked():
    r = filter_output_heuristic("это f4ggot слово")
    assert r.safe is False
    assert "slur_detected" in r.reasons
    assert r.suggested == ""


def test_filter_report_dataclass_fields():
    r = FilterReport(safe=True, reasons=["x"], suggested="text")
    assert r.safe is True


# ====== streamer_kb retrieval ======


def test_score_kb_entry_match():
    e = {"topic": "расписание стримов", "content": "стрим начинаю в 19:00 пн-чт", "tags": "", "priority": 7}
    s = score_kb_entry(e, "когда стрим расписание")
    assert s > 0


def test_score_kb_entry_empty_query():
    e = {"topic": "x", "content": "y"}
    assert score_kb_entry(e, "") == 0.0


def test_retrieve_kb_returns_top_k():
    entries = [
        {"id": 1, "topic": "стрим", "content": "стрим в 19", "tags": "", "priority": 5, "enabled": 1},
        {"id": 2, "topic": "discord", "content": "discord.gg/x", "tags": "", "priority": 5, "enabled": 1},
        {"id": 3, "topic": "никнейм", "content": "никнейм xyz", "tags": "", "priority": 5, "enabled": 1},
    ]
    res = retrieve_kb("когда стрим начинается?", entries, top_k=2)
    assert len(res) <= 2
    if res:
        assert res[0].get("_score") is not None


def test_retrieve_kb_ignores_disabled():
    entries = [
        {"id": 1, "topic": "стрим", "content": "ну стрим вечером", "enabled": 0, "priority": 5},
    ]
    res = retrieve_kb("стрим", entries)
    assert res == []


def test_format_kb_block_empty():
    assert format_kb_block([]) == ""


def test_format_facts_respects_count_and_character_limits():
    facts = [{"fact": f"fact-{i}", "priority": 100 - i, "confidence": 1} for i in range(20)]
    formatted = format_facts_for_prompt(facts, max_facts=3, max_chars=14)
    assert formatted == "fact-0; fact-1"


def test_format_kb_block_renders():
    entries = [{"topic": "стрим", "content": "вечером в 19"}]
    block = format_kb_block(entries)
    assert "стрим" in block
    assert "вечером" in block


# ====== few-shot ======


def test_format_few_shot_block_empty():
    assert format_few_shot_block([]) == ""


def test_format_few_shot_block_caps_at_max():
    examples = [{"message": f"пример {i}"} for i in range(10)]
    block = format_few_shot_block(examples, max_examples=3)
    assert "пример 0" in block
    assert "пример 9" not in block


def test_format_few_shot_block_skips_empty():
    examples = [{"message": ""}, {"message": "ok"}]
    block = format_few_shot_block(examples)
    assert "ok" in block


# ====== A/B variant ======


def test_pick_variant_no_enabled_returns_none():
    variants = [{"id": 1, "weight": 50, "enabled": 0}]
    assert pick_variant(variants) is None


def test_pick_variant_picks_one():
    variants = [
        {"id": 1, "label": "A", "weight": 50, "enabled": 1, "system_prompt": "a"},
        {"id": 2, "label": "B", "weight": 50, "enabled": 1, "system_prompt": "b"},
    ]
    chosen = pick_variant(variants)
    assert chosen is not None
    assert chosen["id"] in (1, 2)


def test_pick_variant_all_zero_weight():
    variants = [{"id": 1, "weight": 0, "enabled": 1}, {"id": 2, "weight": 0, "enabled": 1}]
    assert pick_variant(variants) is None


def test_variant_score_basic():
    v = {"likes": 10, "dislikes": 2, "count": 100}
    assert variant_score(v) > 0


def test_variant_score_negative():
    v = {"likes": 1, "dislikes": 10, "count": 50}
    assert variant_score(v) < 0


# ====== facts: confidence + decay ======


def test_normalize_fact_from_string():
    f = normalize_fact_entry("играет в дота")
    assert f["fact"] == "играет в дота"
    assert 0.0 < f["confidence"] <= 1.0
    assert f["source_msg_id"] is None


def test_normalize_fact_from_dict():
    f = normalize_fact_entry({"fact": "из Москвы", "confidence": 0.6, "source_msg_id": 42})
    assert f["fact"] == "из Москвы"
    assert f["confidence"] == 0.6
    assert f["source_msg_id"] == 42


def test_decay_facts_recent_unchanged():
    facts = [{"fact": "новый", "confidence": 0.9, "last_seen": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}]
    res = decay_facts(facts, half_life_days=30)
    assert len(res) == 1
    assert res[0]["confidence"] >= 0.85  # почти без затухания


def test_decay_facts_old_dropped():
    old_date = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")
    facts = [{"fact": "старый", "confidence": 0.5, "last_seen": old_date}]
    res = decay_facts(facts, half_life_days=30, drop_below=0.1)
    # 0.5 * 0.5^(400/30) ≈ 0.5 * 1e-4 → дропнуто
    assert res == []


def test_decay_facts_empty_input():
    assert decay_facts([]) == []


def test_merge_fact_new():
    facts = []
    res = merge_fact(facts, "играет в дота")
    assert len(res) == 1
    assert res[0]["fact"] == "играет в дота"


def test_merge_fact_bumps_confidence():
    facts = [{"fact": "играет в Дота", "confidence": 0.5, "last_seen": "2024-01-01 00:00:00"}]
    res = merge_fact(facts, "играет в Дота 2")
    assert len(res) == 1
    # Confidence должна вырасти
    assert res[0]["confidence"] > 0.5


def test_merge_fact_empty_input():
    res = merge_fact([], "")
    assert res == []


def test_format_facts_for_prompt_filters_low_confidence():
    facts = [
        {"fact": "high", "confidence": 0.8},
        {"fact": "low", "confidence": 0.1},
    ]
    res = format_facts_for_prompt(facts, min_confidence=0.3)
    assert "high" in res
    assert "low" not in res


def test_format_facts_for_prompt_handles_non_dict():
    res = format_facts_for_prompt(["plain string", {"fact": "ok", "confidence": 0.9}])
    # plain string должна быть пропущена (т.к. не dict)
    assert "ok" in res
