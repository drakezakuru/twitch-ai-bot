"""v9 AQ — tests for app/word_stats.py."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.word_stats import (
    cooling,
    count_words,
    tokenize_for_stats,
    top_n,
    trending,
    ALL_STOPWORDS,
)


# ---------- Tokenization ----------

def test_tokenize_empty():
    assert tokenize_for_stats("") == []
    assert tokenize_for_stats(None) == []


def test_tokenize_short_excluded():
    # слова <3 символов отбрасываются
    toks = tokenize_for_stats("ok no")
    assert "ok" not in toks
    assert "no" not in toks


def test_tokenize_url_removed():
    toks = tokenize_for_stats("заходи на https://example.com сегодня")
    assert "example" not in " ".join(toks)


def test_tokenize_mention_removed():
    toks = tokenize_for_stats("@streamer как игра?")
    assert "streamer" not in toks
    assert "игра" in toks


def test_tokenize_lowercases():
    toks = tokenize_for_stats("ДОТА это PEAK")
    assert all(t == t.lower() for t in toks)


def test_tokenize_keeps_russian():
    toks = tokenize_for_stats("играю в дотку весь день")
    assert "играю" in toks
    assert "дотку" in toks


# ---------- count_words ----------

def test_count_words_basic():
    msgs = ["играем в доту", "опять дота лагает"]
    c = count_words(msgs)
    assert c["доту"] >= 1
    assert c["дота"] >= 1


def test_count_words_stopwords_filtered():
    c = count_words(["я и ты в доме"])
    # все stopwords отфильтрованы; "доме" может остаться
    for stop in ("я", "и", "ты", "в"):
        assert c[stop] == 0


def test_count_words_chat_noise_filtered():
    c = count_words(["KEKW LUL Pog играем"])
    assert c["kekw"] == 0  # noise
    assert c["играем"] == 1


def test_count_words_extra_stopwords():
    c = count_words(["играем в доту"], extra_stopwords={"доту"})
    assert c["доту"] == 0


def test_count_words_digits_filtered():
    c = count_words(["123 456 валим"])
    assert c["123"] == 0
    assert c["валим"] == 1


def test_count_words_multiple_messages():
    msgs = ["патч новый", "патч слабый", "патч топ"]
    c = count_words(msgs)
    assert c["патч"] == 3


def test_count_words_empty_messages():
    c = count_words([])
    assert len(c) == 0


# ---------- top_n ----------

def test_top_n_returns_pairs():
    c = Counter({"a": 5, "b": 3, "c": 1})
    res = top_n(c, n=2)
    assert len(res) == 2
    assert res[0] == ("a", 5)


def test_top_n_default_50():
    c = Counter({f"w{i}": i for i in range(100)})
    res = top_n(c)
    assert len(res) == 50


def test_top_n_n_larger_than_counter():
    c = Counter({"a": 1, "b": 2})
    res = top_n(c, n=10)
    assert len(res) == 2


# ---------- trending ----------

def test_trending_new_word():
    cur = Counter({"патч": 10, "игра": 5})
    base = Counter({"игра": 5})
    rows = trending(cur, base, min_current=3)
    # «патч» — новое слово в current, должно быть выше в trending
    words = [r["word"] for r in rows]
    assert "патч" in words
    # Должно быть первым по score
    assert rows[0]["word"] == "патч"


def test_trending_min_current_filter():
    cur = Counter({"a": 2, "b": 5})
    base = Counter()
    rows = trending(cur, base, min_current=3)
    # «a» отфильтровано (2 < 3), «b» включено
    words = [r["word"] for r in rows]
    assert "a" not in words
    assert "b" in words


def test_trending_includes_score_and_delta():
    cur = Counter({"x": 10})
    base = Counter()
    rows = trending(cur, base, min_current=3)
    assert "score" in rows[0]
    assert "delta" in rows[0]
    assert "current" in rows[0]
    assert "baseline" in rows[0]


def test_trending_sorted_by_score():
    cur = Counter({"a": 100, "b": 5})
    base = Counter({"a": 1, "b": 1})
    rows = trending(cur, base, min_current=3)
    assert rows[0]["score"] >= rows[-1]["score"]


def test_trending_word_present_in_baseline():
    cur = Counter({"патч": 50})
    base = Counter({"патч": 10})
    rows = trending(cur, base, min_current=3)
    assert rows[0]["word"] == "патч"
    assert rows[0]["baseline"] == 10
    assert rows[0]["current"] == 50


def test_trending_handles_empty_baseline():
    cur = Counter({"новость": 5})
    base = Counter()
    rows = trending(cur, base, min_current=3)
    assert len(rows) == 1
    assert rows[0]["word"] == "новость"


def test_trending_handles_empty_current():
    cur = Counter()
    base = Counter({"старое": 100})
    rows = trending(cur, base, min_current=3)
    assert rows == []


# ---------- cooling ----------

def test_cooling_word_dropped():
    # «патч» был популярен в baseline, исчез в current
    cur = Counter({"новость": 50, "игра": 50})
    base = Counter({"патч": 100, "игра": 50, "новость": 50})
    rows = cooling(cur, base, min_baseline=3)
    words = [r["word"] for r in rows]
    assert "патч" in words
    # «патч» — самое значимое падение
    assert rows[0]["word"] == "патч"
    assert rows[0]["score"] < 0


def test_cooling_min_baseline_filter():
    cur = Counter()
    base = Counter({"редкое": 2, "частое": 50})
    rows = cooling(cur, base, min_baseline=3)
    words = [r["word"] for r in rows]
    assert "редкое" not in words
    assert "частое" in words


def test_cooling_sorted_ascending():
    cur = Counter({"a": 1, "b": 10})
    base = Counter({"a": 100, "b": 100})
    rows = cooling(cur, base, min_baseline=3)
    # Самое сильное падение first
    assert rows[0]["score"] <= rows[-1]["score"]


# ---------- ALL_STOPWORDS ----------

def test_all_stopwords_includes_common():
    # должны быть и RU и EN общие
    assert "и" in ALL_STOPWORDS
    assert "the" in ALL_STOPWORDS
    assert "kekw" in ALL_STOPWORDS  # chat noise
