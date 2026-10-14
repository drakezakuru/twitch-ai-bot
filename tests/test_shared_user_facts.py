"""Тесты выживших хелперов app.shared_user_facts (P8-C2).

Общая память удалена (8d8ec11): DB-API (ensure_table/upsert_fact/list_facts/
merge_fact_records/format_user_facts_block/filter_facts_by_confidence) больше не
существует; миграция legacy-фактов покрыта tests/test_p8_c2_per_bot_memory.py.
Здесь остаются только чистые хелперы, которые использует миграция.
"""

from __future__ import annotations

from app.shared_user_facts import normalize_fact, normalize_username


def test_normalize_username():
    assert normalize_username("@Viewer") == "viewer"
    assert normalize_username("  user  ") == "user"
    assert normalize_username("") == ""
    assert normalize_username(None) == ""  # type: ignore[arg-type]


def test_normalize_fact_truncates():
    long = "x" * 500
    out = normalize_fact(long, max_len=100)
    assert len(out) <= 100
    assert out.endswith("…")


def test_normalize_fact_strips():
    assert normalize_fact("  привет  ") == "привет"
    assert normalize_fact(None) == ""  # type: ignore[arg-type]
