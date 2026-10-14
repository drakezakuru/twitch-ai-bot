"""v9 AP — tests for app/sentiment.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.sentiment import (
    classify,
    classify_with_score,
    score,
    tokenize,
    aggregate_buckets,
)


# ---------- Tokenization ----------

def test_tokenize_empty():
    assert tokenize("") == []
    assert tokenize(None) == []


def test_tokenize_words():
    toks = tokenize("Hello world!")
    assert "hello" in toks and "world" in toks


def test_tokenize_russian():
    toks = tokenize("Привет, как дела?")
    assert "привет" in toks and "как" in toks and "дела" in toks


def test_tokenize_emoji():
    toks = tokenize("ну норм 🔥")
    assert "🔥" in toks


def test_tokenize_heart_word():
    toks = tokenize("я <3 этот стрим")
    # <3 нормализуется в отдельный токен
    assert "<3" in toks or "3" not in toks


# ---------- Scoring positive ----------

def test_classify_positive_ru():
    assert classify("это просто пушка, круто!") == 1


def test_classify_positive_emoji():
    assert classify("стрим топ 🔥🔥🔥") == 1


def test_classify_positive_kekw():
    assert classify("KEKW бомба момент") == 1


def test_classify_positive_en():
    assert classify("this is awesome, love it") == 1


def test_classify_positive_thanks():
    assert classify("спасибо большое!") == 1


def test_classify_positive_norm():
    # «нормас» считается слабо положительным
    label, pos, neg = classify_with_score("нормас")
    assert pos > 0


# ---------- Scoring negative ----------

def test_classify_negative_ru():
    assert classify("это полная херня, отстой") == -1


def test_classify_negative_emoji():
    assert classify("ужасно 💩 не нравится") == -1


def test_classify_negative_en():
    assert classify("this is terrible, hate it") == -1


def test_classify_negative_lag():
    assert classify("такие лаги, бесит") == -1


def test_classify_negative_sadge():
    assert classify("Sadge не получилось") == -1


# ---------- Neutral ----------

def test_classify_neutral_short():
    assert classify("привет") == 0


def test_classify_neutral_question():
    assert classify("где скачать?") == 0


def test_classify_neutral_empty():
    assert classify("") == 0
    assert classify("   ") == 0


def test_classify_neutral_balanced():
    # 1 положительное + 1 отрицательное → neutral
    label, pos, neg = classify_with_score("круто но плохо")
    assert label == 0
    assert pos > 0 and neg > 0


# ---------- Negation ----------

def test_negation_inverts_positive():
    # «не круто» → не должно быть +1, скорее всего neutral или negative
    pos, neg = score("не круто")
    assert neg >= pos


def test_negation_inverts_negative_to_positive():
    # «не плохо» — слабо позитивно
    pos, neg = score("не плохо")
    assert pos >= neg


def test_double_words_compound():
    # «очень круто» → intensifier
    pos1, _ = score("круто")
    pos2, _ = score("очень круто")
    assert pos2 > pos1


# ---------- Intensifiers ----------

def test_intensifier_amplifies():
    pos1, _ = score("good")
    pos2, _ = score("very good")
    assert pos2 > pos1


def test_intensifier_negative():
    _, neg1 = score("bad")
    _, neg2 = score("very bad")
    assert neg2 > neg1


# ---------- score() returns tuple ----------

def test_score_returns_tuple():
    pos, neg = score("круто и плохо")
    assert isinstance(pos, float)
    assert isinstance(neg, float)


def test_score_empty():
    pos, neg = score("")
    assert pos == 0.0
    assert neg == 0.0


def test_score_all_stopwords():
    pos, neg = score("ну так и что")
    assert pos == 0.0
    assert neg == 0.0


# ---------- classify_with_score ----------

def test_classify_with_score_returns_three():
    label, pos, neg = classify_with_score("ужас!")
    assert label in (-1, 0, 1)
    assert isinstance(pos, float)
    assert isinstance(neg, float)


# ---------- aggregate_buckets ----------

def test_aggregate_buckets_empty():
    assert aggregate_buckets([]) == []


def test_aggregate_buckets_single():
    points = aggregate_buckets([("2026-05-04 12:00:00", 1)], bucket_size_sec=300)
    assert len(points) == 1
    assert points[0]["pos"] == 1 and points[0]["neg"] == 0 and points[0]["neu"] == 0


def test_aggregate_buckets_grouping():
    rows = [
        ("2026-05-04 12:00:00", 1),
        ("2026-05-04 12:01:00", 1),
        ("2026-05-04 12:02:00", -1),
        ("2026-05-04 12:10:00", 0),
    ]
    points = aggregate_buckets(rows, bucket_size_sec=300)  # 5min buckets
    # 12:00–12:05 → 2 pos, 1 neg
    # 12:10 → 1 neu
    assert len(points) == 2
    assert points[0]["pos"] == 2 and points[0]["neg"] == 1
    assert points[1]["neu"] == 1


def test_aggregate_buckets_net_score():
    rows = [
        ("2026-05-04 12:00:00", 1),
        ("2026-05-04 12:01:00", 1),
        ("2026-05-04 12:02:00", -1),
    ]
    points = aggregate_buckets(rows, bucket_size_sec=300)
    assert points[0]["net"] == 1


def test_aggregate_buckets_invalid_ts_skipped():
    rows = [
        ("not-a-date", 1),
        ("2026-05-04 12:00:00", -1),
    ]
    points = aggregate_buckets(rows, bucket_size_sec=300)
    assert len(points) == 1
    assert points[0]["neg"] == 1


def test_aggregate_buckets_total_field():
    rows = [
        ("2026-05-04 12:00:00", 1),
        ("2026-05-04 12:01:00", 0),
        ("2026-05-04 12:02:00", -1),
    ]
    points = aggregate_buckets(rows, bucket_size_sec=300)
    assert points[0]["total"] == 3


def test_aggregate_buckets_sorted():
    rows = [
        ("2026-05-04 13:00:00", 1),
        ("2026-05-04 12:00:00", 1),
        ("2026-05-04 14:00:00", 1),
    ]
    points = aggregate_buckets(rows, bucket_size_sec=3600)
    assert len(points) == 3
    assert points[0]["ts_unix"] < points[1]["ts_unix"] < points[2]["ts_unix"]
