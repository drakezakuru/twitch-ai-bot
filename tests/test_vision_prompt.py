"""Tests for app/vision_prompt.py — promptbuilder + reasoning-leak stripper.

Реальные сэмплы взяты из боевых логов пользователя (см. session-notes к
v10.4.8): модели ``nemotron-...-reasoning`` сливают chain-of-thought в
ответ, и нужно вычищать его перед публикацией в чат.
"""

from app.vision_prompt import (
    _cyrillic_ratio,
    _looks_like_english_meta,
    build_vision_prompt,
    strip_reasoning,
)


# ---------- build_vision_prompt -----------------------------------------------


def test_build_prompt_basic_style_uses_short_prompt():
    p = build_vision_prompt(style="basic", channel_info=None, include_stream_info=False)
    assert "Кратко опиши" in p
    assert "split-screen" not in p


def test_build_prompt_detailed_style_mentions_pip_and_split_screen():
    p = build_vision_prompt(style="detailed", channel_info=None, include_stream_info=False)
    # Detailed промпт обязан явно просить о split-screen / PiP.
    assert "split-screen" in p.lower() or "pip" in p.lower()
    # И о реакции стримера отдельно.
    assert "стример" in p.lower()


def test_build_prompt_includes_channel_info_when_enabled():
    info = {"title": "RAW! Cup Grand Final", "game_name": "Counter-Strike 2"}
    p = build_vision_prompt(channel_info=info, include_stream_info=True)
    assert "Counter-Strike 2" in p
    assert "RAW! Cup Grand Final" in p


def test_build_prompt_skips_channel_info_when_disabled():
    info = {"title": "T", "game_name": "G"}
    p = build_vision_prompt(channel_info=info, include_stream_info=False)
    assert "T" not in p
    assert "G" not in p


def test_build_prompt_uses_override_when_provided():
    override = "Опиши кадр в стиле Шекспира."
    p = build_vision_prompt(override=override, channel_info=None, include_stream_info=False)
    assert p == override


def test_build_prompt_override_still_gets_channel_info_prefix():
    override = "Опиши кадр кратко."
    info = {"game_name": "Dota 2", "title": "ranked"}
    p = build_vision_prompt(override=override, channel_info=info, include_stream_info=True)
    assert "Dota 2" in p
    assert override in p


def test_build_prompt_handles_missing_fields_in_channel_info():
    # Нет game_name — только title.
    info = {"title": "Just chatting", "game_name": ""}
    p = build_vision_prompt(channel_info=info, include_stream_info=True)
    assert "Just chatting" in p


def test_build_prompt_truncates_very_long_title():
    long_title = "X" * 500
    info = {"title": long_title, "game_name": "G"}
    p = build_vision_prompt(channel_info=info, include_stream_info=True)
    assert "..." in p
    assert "X" * 500 not in p


# ---------- helpers -----------------------------------------------------------


def test_cyrillic_ratio():
    assert _cyrillic_ratio("Привет") == 1.0
    assert _cyrillic_ratio("Hello") == 0.0
    assert 0.4 < _cyrillic_ratio("Привет hello") < 0.6
    assert _cyrillic_ratio("") == 0.0
    assert _cyrillic_ratio("12345 !@#") == 0.0


def test_looks_like_english_meta():
    assert _looks_like_english_meta("We need to respond with...")
    assert _looks_like_english_meta("Let's parse the question...")
    assert _looks_like_english_meta("The streamer is doing X")
    assert not _looks_like_english_meta("Стример играет в КС")
    assert not _looks_like_english_meta("")


# ---------- strip_reasoning ---------------------------------------------------


REAL_LEAK_SAMPLE = (
    "We need to respond with a concise description of what's happening on the "
    "stream: a stitched view showing a stitched view of a stitched view? Let's "
    "parse the question: \"Briefly describe what is happening on the stream on "
    "Russian (1-2 sentences). What is visible: game, scene, actions of the "
    "streamer.\" So we need to describe the stream content. The stream shows a "
    "stage with a group of people (presumably a team) wearing \"Delalite\" "
    "shirts, a host presenting something, a \"RAW! CUP\" sign, confetti on the "
    "floor, and a scoreboard indicating \"1 3\". There are also picture-in-"
    "picture windows showing other participants (maybe streamers). So we "
    "describe: a live awards ceremony or competition stage where a team is "
    "being recognized, with a host, confetti, and a scoreboard. The picture-in-"
    "picture windows show other streamers reacting. So answer: \"На стриме "
    "проходит церемония награждения/соревнования: команда в черных футболках "
    "«Delalite» стоит на сцене, получает приз, а ведущий в светлом костюме "
    "держит табличку «RAW! CUP», при этом на сцене разбросаны конфетти, а в "
    "правом верхнем углу виден счет 1 – 3 и окна с другими участниками "
    "стрима.\" That's 2 sentences. Let's"
)


def test_strip_reasoning_real_leak_extracts_russian_answer():
    out = strip_reasoning(REAL_LEAK_SAMPLE)
    # Должны получить только русское описание.
    assert "На стриме проходит церемония" in out
    # English chain-of-thought должен быть вычищен.
    assert "We need to respond" not in out
    assert "Let's parse" not in out
    assert "That's 2 sentences" not in out
    # И должно быть >50% кириллицы.
    assert _cyrillic_ratio(out) > 0.7


def test_strip_reasoning_handles_think_tags():
    text = "<think>I need to figure out what to say</think>Стример играет в CS."
    out = strip_reasoning(text)
    assert "<think>" not in out
    assert "Стример играет в CS." in out


def test_strip_reasoning_handles_reasoning_tags():
    text = "<reasoning>analyzing image...</reasoning>На экране бой за башню."
    out = strip_reasoning(text)
    assert "<reasoning>" not in out
    assert "На экране бой за башню." in out


def test_strip_reasoning_handles_unclosed_think():
    text = "Стример выиграл!<think>but why did they..."
    out = strip_reasoning(text)
    assert "<think>" not in out
    assert "Стример выиграл!" in out


def test_strip_reasoning_handles_answer_marker_with_quote():
    text = (
        "Let me think about this. The streamer is excited. "
        "Answer: \"Стример в шоке от внезапной победы.\""
    )
    out = strip_reasoning(text)
    assert "Стример в шоке от внезапной победы." in out
    assert "Let me think" not in out


def test_strip_reasoning_handles_so_answer_marker():
    text = "Lots of reasoning. So answer: На стриме идёт CS2."
    out = strip_reasoning(text)
    assert "На стриме идёт CS2." in out
    assert "Lots of reasoning" not in out


def test_strip_reasoning_handles_russian_answer_marker():
    text = "Анализирую изображение. Ответ: Стример играет в Dota."
    out = strip_reasoning(text)
    assert "Стример играет в Dota." in out


def test_strip_reasoning_leaves_clean_russian_unchanged():
    text = "Стример играет в Counter-Strike, только что взял килл с AWP."
    out = strip_reasoning(text)
    assert out == text


def test_strip_reasoning_handles_empty_input():
    assert strip_reasoning("") == ""
    assert strip_reasoning(None) is None


def test_strip_reasoning_strips_trailing_english_meta():
    text = "Стример показывает свою реакцию. That's a good description."
    out = strip_reasoning(text)
    assert "That's a good description" not in out
    assert "Стример показывает свою реакцию." in out


def test_strip_reasoning_strips_english_meta_start_keeps_russian():
    text = (
        "We need to analyze the image carefully. Looking at the image, the "
        "streamer is excited. На экране идёт финал турнира — команда празднует."
    )
    out = strip_reasoning(text)
    assert "На экране идёт финал турнира" in out
    # Длинный английский префикс должен быть отрезан.
    assert "We need to analyze" not in out


def test_strip_reasoning_does_not_destroy_text_without_russian():
    # Edge case: ответ полностью на английском (модель проигнорировала запрос на ru).
    # Парсер должен вернуть оригинал, а не пусто.
    text = "Streamer is playing CS2 right now and just got a kill."
    out = strip_reasoning(text)
    assert out
    assert "Streamer is playing" in out
