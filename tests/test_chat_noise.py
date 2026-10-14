"""Тест на эвристику _is_noise_message в chat_analyzer.

Чисто-эмодзи / реакции / коротенькие подобия не должны попадать в "содержательный"
блок контекста, который смотрит AI.
"""
from app.chat_analyzer import _is_noise_message


def test_empty_or_short():
    assert _is_noise_message("")
    assert _is_noise_message("a")
    assert _is_noise_message("?")
    assert _is_noise_message("+1")


def test_emote_spam():
    assert _is_noise_message("KEKW")
    assert _is_noise_message("LULW Pog OMEGALUL")
    assert _is_noise_message("KEKW LULW")
    assert _is_noise_message("Kappa")


def test_reactions():
    assert _is_noise_message("лол")
    assert _is_noise_message("ахах")
    assert _is_noise_message("ор")
    assert _is_noise_message("F")


def test_substantive_messages_pass():
    assert not _is_noise_message("кто этот стример?")
    assert not _is_noise_message("какая видяха у него?")
    assert not _is_noise_message("KEKW согласен но граната была в кусты")
    assert not _is_noise_message("давай в апекс")
    assert not _is_noise_message("я бы ливнул из этой команды")


def test_punctuation_only():
    assert _is_noise_message("!!!")
    assert _is_noise_message("...")
    assert _is_noise_message("???!")
