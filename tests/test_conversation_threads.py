"""Tests for v10.4.7 Wave 4.2 — conversation threads."""

import time

from app.conversation_threads import (
    ConversationThread,
    ThreadTracker,
    _tokenize,
    _tf,
    cosine,
    format_thread_context,
)


def test_tokenize_drops_stopwords():
    toks = _tokenize("это и в Elden Ring сложный босс")
    assert "elden" in toks
    assert "ring" in toks
    assert "босс" in toks
    assert "и" not in toks
    assert "в" not in toks


def test_tf_normalized():
    toks = ["a", "a", "b"]
    tf = _tf(toks)
    assert abs(tf["a"] + tf["b"] - 1.0) < 1e-6
    assert tf["a"] == 2 / 3


def test_cosine_same_topic():
    a = _tf(_tokenize("Elden Ring сложный босс"))
    b = _tf(_tokenize("Elden Ring трудный босс"))
    assert cosine(a, b) > 0.5


def test_cosine_different_topics():
    a = _tf(_tokenize("Elden Ring босс"))
    b = _tf(_tokenize("DOTA mid лейн руны"))
    assert cosine(a, b) < 0.3


def test_tracker_creates_new_thread():
    tr = ThreadTracker()
    thr = tr.feed("user_a", "Elden Ring какой билд", now=1000.0)
    assert thr is not None
    assert "user_a" in thr.participants


def test_tracker_groups_same_topic():
    tr = ThreadTracker(similarity_threshold=0.15)
    t1 = tr.feed("user_a", "Elden Ring сложный босс", now=1000.0)
    t2 = tr.feed("user_b", "Elden Ring какой билд", now=1010.0)
    assert t1.thread_id == t2.thread_id
    assert {"user_a", "user_b"} <= t2.participants


def test_tracker_separates_topics():
    tr = ThreadTracker(similarity_threshold=0.3)
    t1 = tr.feed("user_a", "Elden Ring боссы душнят", now=1000.0)
    t2 = tr.feed("user_b", "DOTA mid лейн руны", now=1010.0)
    assert t1.thread_id != t2.thread_id


def test_tracker_marks_bot_interventions():
    tr = ThreadTracker(similarity_threshold=0.15)
    tr.feed("user_a", "Elden Ring guide boss", now=1000.0)
    tr.feed("bot1", "Elden Ring guide для босса", now=1005.0, is_bot_response=True)
    # тот же тред должен матчиться
    thrs = list(tr.threads.values())
    assert len(thrs) == 1
    assert thrs[0].bot_interventions >= 1
    assert "bot1" not in thrs[0].participants  # bot не считается participant


def test_tracker_stale_archiving():
    tr = ThreadTracker(stale_after_sec=60)
    tr.feed("user_a", "Elden Ring какой билд", now=1000.0)
    assert len(tr.threads) == 1
    tr.feed("user_b", "DOTA mid", now=1200.0)  # > stale_after
    # старый тред должен быть архивирован
    assert len(tr.archived) >= 1
    assert len(tr.threads) == 1


def test_tracker_caps_active():
    tr = ThreadTracker(max_active_threads=2, similarity_threshold=0.9)
    for i in range(5):
        tr.feed(f"u{i}", f"тема номер {i} уникальная штука", now=1000.0 + i)
    assert len(tr.threads) <= 2


def test_find_thread_for():
    tr = ThreadTracker(similarity_threshold=0.15)
    tr.feed("user_a", "Elden Ring боссы", now=1000.0)
    thr = tr.find_thread_for("Elden Ring какой урон", now=1010.0)
    assert thr is not None


def test_find_thread_returns_none_for_unrelated():
    tr = ThreadTracker(similarity_threshold=0.4)
    tr.feed("user_a", "Elden Ring боссы", now=1000.0)
    thr = tr.find_thread_for("у меня сегодня день рождения собака", now=1010.0)
    assert thr is None


def test_format_thread_context():
    t = ConversationThread(
        thread_id="thr_1",
        started_at=1000.0,
        last_at=2200.0,
        centroid={"elden": 0.5, "ring": 0.5},
        participants={"user_a", "user_b"},
        bot_interventions=1,
        n_messages=3,
        top_keywords=["elden", "ring"],
        messages=[(1000.0, "user_a", "elden ring guide"), (1500.0, "user_b", "какой билд")],
    )
    txt = format_thread_context(t)
    assert "Тема" in txt
    assert "elden" in txt.lower()
    assert "20 мин" in txt or "Длится" in txt


def test_format_thread_context_empty_messages():
    t = ConversationThread(thread_id="x", started_at=0, last_at=0)
    assert format_thread_context(t) == ""


def test_snapshot_format():
    tr = ThreadTracker()
    tr.feed("user_a", "Elden Ring", now=1000.0)
    snap = tr.snapshot()
    assert "active" in snap
    assert len(snap["active"]) >= 1
    assert "archived_count" in snap
