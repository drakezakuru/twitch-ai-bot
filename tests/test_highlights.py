"""Тесты Feature W: highlight / clip detector."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.highlights import detect_highlights, _count_reactions, DEFAULT_REACTION_TOKENS


def _ts(base: datetime, sec_offset: int) -> str:
    return (base + timedelta(seconds=sec_offset)).strftime("%Y-%m-%d %H:%M:%S")


def _row(ts: str, channel: str, author: str, message: str) -> dict:
    return {"timestamp": ts, "channel": channel, "author": author, "message": message}


def test_no_highlights_when_chat_is_quiet():
    """Если каждые 30 секунд по одному сообщению — нет всплесков."""
    base = datetime(2025, 5, 1, 18, 0, 0)
    rows = [_row(_ts(base, i * 30), "stream", f"u{i}", "hi") for i in range(20)]
    assert detect_highlights(rows, min_count=8, spike_factor=2.0) == []


def test_detects_obvious_spike():
    """30 сообщений в одну минуту после 10 минут спокойствия — должен быть хайлайт."""
    base = datetime(2025, 5, 1, 18, 0, 0)
    rows: list[dict] = []
    # 10 минут «нормального» чата: 2 сообщения в минуту
    for minute in range(10):
        for j in range(2):
            rows.append(_row(_ts(base, minute * 60 + j * 20), "stream", f"u{minute}_{j}", "hi"))
    # на 11-й минуте — 30 сообщений-спам
    spike_min = base + timedelta(minutes=11)
    for j in range(30):
        rows.append(_row(_ts(spike_min, j), "stream", f"hype{j}", "KEKW KEKW LUL"))

    highlights = detect_highlights(rows, min_count=8, spike_factor=2.0)
    assert len(highlights) >= 1
    h = highlights[0]
    assert h.channel == "stream"
    assert h.count >= 30
    assert h.spike_factor >= 2.0
    # Должны посчитать KEKW и LUL
    emote_dict = dict(h.top_emotes)
    assert emote_dict.get("kekw", 0) >= 30
    assert emote_dict.get("lul", 0) >= 30
    assert h.reaction_count >= 60


def test_merges_adjacent_minutes():
    """Два соседних горячих окна должны слиться в один highlight."""
    base = datetime(2025, 5, 1, 19, 0, 0)
    rows: list[dict] = []
    # 10 минут спокойствия
    for minute in range(10):
        rows.append(_row(_ts(base, minute * 60), "stream", "lurker", "hi"))
    # минуты 11 и 12 — обе горячие
    for j in range(15):
        rows.append(_row(_ts(base + timedelta(minutes=11), j * 2), "stream", f"u{j}", "OMEGALUL"))
    for j in range(15):
        rows.append(_row(_ts(base + timedelta(minutes=12), j * 2), "stream", f"u{j}", "OMEGALUL"))

    highlights = detect_highlights(rows, min_count=8, spike_factor=2.0)
    assert len(highlights) == 1
    h = highlights[0]
    assert (h.end_ts - h.start_ts).total_seconds() == 60
    assert h.count == 30


def test_isolated_per_channel():
    """Всплеск в одном канале не должен влиять на другой."""
    base = datetime(2025, 5, 1, 20, 0, 0)
    rows: list[dict] = []
    for minute in range(10):
        rows.append(_row(_ts(base, minute * 60), "alpha", "u", "hi"))
        rows.append(_row(_ts(base, minute * 60), "beta", "u", "hi"))
    spike_min = base + timedelta(minutes=11)
    for j in range(20):
        rows.append(_row(_ts(spike_min, j), "alpha", f"u{j}", "kek"))

    highlights = detect_highlights(rows, min_count=8, spike_factor=2.0)
    channels = {h.channel for h in highlights}
    assert channels == {"alpha"}


def test_filters_by_min_count():
    """min_count отсекает мелкие всплески даже если они выше baseline."""
    base = datetime(2025, 5, 1, 21, 0, 0)
    rows: list[dict] = []
    # Очень тихий канал: 1 сообщение каждые 5 минут
    for minute in range(0, 30, 5):
        rows.append(_row(_ts(base, minute * 60), "ch", "u", "hi"))
    # На 31-й минуте — 5 сообщений (выше baseline=1, но < min_count=8)
    spike_min = base + timedelta(minutes=31)
    for j in range(5):
        rows.append(_row(_ts(spike_min, j), "ch", f"u{j}", "kek"))

    highlights = detect_highlights(rows, min_count=8, spike_factor=2.0)
    assert highlights == []


def test_sample_messages_prefer_reactions():
    """В sample_messages должны попасть сообщения с максимальной плотностью реакций."""
    base = datetime(2025, 5, 1, 22, 0, 0)
    rows: list[dict] = []
    for minute in range(10):
        rows.append(_row(_ts(base, minute * 60), "ch", "u", "hi"))

    spike_min = base + timedelta(minutes=11)
    for j in range(15):
        rows.append(_row(_ts(spike_min, j * 2), "ch", f"u{j}", "обычное сообщение"))
    rows.append(_row(_ts(spike_min, 31), "ch", "hyper", "KEKW KEKW KEKW LUL OMEGALUL"))

    highlights = detect_highlights(rows, min_count=8, spike_factor=2.0)
    assert len(highlights) >= 1
    sample_authors = [s["author"] for s in highlights[0].sample_messages]
    assert "hyper" in sample_authors


def test_count_reactions_helper():
    """Хелпер находит и токенизированные эмоуты, и emoji-like."""
    reaction_set = {t.lower() for t in DEFAULT_REACTION_TOKENS}
    cnt, found = _count_reactions("Pog kekw KEKW lul lul +1", reaction_set)
    assert cnt == 6
    assert found.count("kekw") == 2
    assert found.count("lul") == 2
    assert "+1" in found

    cnt, _ = _count_reactions("просто текст без эмоутов", reaction_set)
    assert cnt == 0


def test_to_dict_serialisation():
    """Highlight.to_dict() даёт сериализуемый JSON-friendly вид."""
    base = datetime(2025, 5, 1, 22, 0, 0)
    rows: list[dict] = []
    for minute in range(10):
        rows.append(_row(_ts(base, minute * 60), "ch", "u", "hi"))
    spike_min = base + timedelta(minutes=11)
    for j in range(20):
        rows.append(_row(_ts(spike_min, j), "ch", f"u{j}", "KEKW"))

    highlights = detect_highlights(rows, min_count=8, spike_factor=2.0)
    assert highlights
    d = highlights[0].to_dict()
    assert isinstance(d["start_ts"], str) and "T" in d["start_ts"]
    assert isinstance(d["top_emotes"], list)
    assert isinstance(d["sample_messages"], list)
    import json
    json.dumps(d)  # не должно бросать
