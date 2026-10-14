"""Wave 7 (owner survey Q34/Q35: М): общее ядро распознавания эмодзи.

`emoji-leaderboard` (рейтинг) и `emoji-chat` (лента) остаются разными
виджетами со своими карточками и URL, но «что считается эмодзи» описано один
раз в `app/emoji_core.py`; фронтенд ленты берёт тот же паттерн через
`/api/widgets/public/emoji-core`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from app.emoji_core import EMOJI_PATTERN, count_emojis, extract_emojis, has_emoji, tokenize

ROOT = Path(__file__).resolve().parents[1]


def test_counting_matches_extraction():
    text = "привет 😀🔥 мир ❤️"
    assert count_emojis(text) == len(extract_emojis(text))
    assert count_emojis("просто текст") == 0
    assert count_emojis("") == 0
    assert has_emoji(text) and not has_emoji("просто текст")


def test_tokenize_splits_emotes_emoji_and_text():
    tokens = tokenize("hi KEKW 😀 bye", emote_codes=("KEKW",))
    assert ("emote", "KEKW") in tokens
    assert ("emoji", "😀") in tokens
    assert "".join(value for _kind, value in tokens) == "hi KEKW 😀 bye"


def test_longer_emote_codes_win():
    """KEKW не должен съедаться более коротким кодом KEK."""
    tokens = tokenize("KEKW", emote_codes=("KEK", "KEKW"))
    assert tokens == [("emote", "KEKW")]


def test_tokenize_without_emotes_still_finds_emoji():
    assert tokenize("a😀b") == [("text", "a"), ("emoji", "😀"), ("text", "b")]
    assert tokenize("") == []


def test_widgets_module_delegates_to_the_core():
    """widgets._count_emojis не должен снова заводить свою регулярку."""
    from app.widgets import _count_emojis
    src = (ROOT / "app" / "widgets.py").read_text(encoding="utf-8")
    assert "_EMOJI_RE" not in src, "локальная копия паттерна вернулась в widgets.py"
    for text in ("😀🔥🔥", "нет эмодзи", "", "❤️"):
        assert _count_emojis(text) == count_emojis(text)


@pytest.mark.asyncio
async def test_emoji_core_endpoint_serves_the_same_pattern(tmp_db, disable_auth):
    from app.database import init_db
    from app.widgets import ensure_widgets_schema, public_router
    from fastapi import FastAPI
    await init_db()
    await ensure_widgets_schema()
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        body = (await c.get("/api/widgets/public/emoji-core")).json()
    assert body["pattern"] == EMOJI_PATTERN
    assert "u" in body["flags"], "фронтенду нужен unicode-флаг для не-BMP эмодзи"
    # паттерн должен быть валидной регуляркой и ловить те же эмодзи
    compiled = re.compile(body["pattern"])
    assert compiled.findall("a😀b❤️") == extract_emojis("a😀b❤️")


def test_chat_widget_consumes_the_shared_pattern():
    html = (ROOT / "widgets" / "emoji-chat" / "index.html").read_text(encoding="utf-8")
    assert "/api/widgets/public/emoji-core" in html, "лента не берёт общее ядро"
    assert "loadEmojiCore()" in html, "ядро не загружается при старте виджета"


def test_both_emoji_widgets_keep_their_cards():
    from app.widget_inventory import WIDGET_INVENTORY
    slugs = {item.slug for item in WIDGET_INVENTORY}
    assert {"emoji-chat", "emoji-leaderboard"} <= slugs, "владелец просил сохранить оба вида"
