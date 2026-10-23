"""Нормализация текста: транслит, гомоглифы, leet, казахские буквы, цитаты из оригинала."""

from __future__ import annotations

import pytest

from pruf.normalize.text import normalize_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rozygrysh", "розыгрыш"),
        ("Razygryvaem priz", "разыгрываем приз"),
        ("Shchuka", "щука"),
        ("Passivnyi dohod", "пассивный доход"),
        ("Kazino zerkalo", "казино зеркало"),
        ("vzhuh", "вжух"),
        ("Yasno", "ясно"),
        ("pishi v lichku", "пиши в личку"),
    ],
)
def test_translit_latin_to_cyrillic(raw: str, expected: str) -> None:
    # Act
    folded = normalize_text(raw).folded

    # Assert
    assert folded == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pозыгрыш", "розыгрыш"),  # латинская p внутри кириллического слова
        ("kaзинo", "казино"),  # k и o латиницей
        ("ПPИЗ", "приз"),  # заглавная латинская P
        ("BЫИГPЫШ", "выигрыш"),  # заглавные B и P
    ],
)
def test_homoglyphs_inside_cyrillic_words_are_folded(raw: str, expected: str) -> None:
    assert normalize_text(raw).folded == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("р0зыгрыш", "розыгрыш"),
        ("3аработок", "заработок"),
        ("ka$ino", "касино"),
    ],
)
def test_leet_digits_inside_words_are_folded(raw: str, expected: str) -> None:
    assert normalize_text(raw).folded == expected


def test_at_sign_leet_inside_word_is_folded() -> None:
    assert normalize_text("к@зино").folded == "казино"


def test_mentions_are_kept_verbatim() -> None:
    assert normalize_text("@Kazino_Bot").folded == "@kazino_bot"


def test_leet_is_not_applied_to_amounts_and_numbers() -> None:
    # Arrange
    raw = "5000тг 300 2026"

    # Act
    folded = normalize_text(raw).folded

    # Assert
    assert folded == "5000тг 300 2026"


def test_kazakh_cyrillic_letters_are_preserved_and_lowercased() -> None:
    assert normalize_text("Ұтыс ойыны! Қатысу тегін, Жеңімпаз").folded == "ұтыс ойыны! қатысу тегін, жеңімпаз"


def test_kazakh_latin_2021_letters_map_to_kazakh_cyrillic() -> None:
    # Act
    folded = normalize_text("Qatysu 1000 teńge, ǵ ú ü ó á ı").folded

    # Assert
    assert folded == "қатысу 1000 теңге, ғ ұ ү ө ә ы"


def test_yo_is_folded_to_ye() -> None:
    assert normalize_text("Ещё отбил").folded == "еще отбил"


def test_urls_and_phones_are_kept_verbatim_lowercased() -> None:
    # Arrange
    raw = "Сайт Vulkan-KZ.top и +7(701)2345678"

    # Act
    folded = normalize_text(raw).folded

    # Assert
    assert "vulkan-kz.top" in folded
    assert "+7(701)2345678" in folded


def test_fullwidth_text_is_nfkc_normalized() -> None:
    assert normalize_text("ｒｏｚｙｇｒｙｓｈ").folded == "розыгрыш"


def test_empty_and_none_input_produce_empty_text() -> None:
    # Act
    empty = normalize_text("")
    none = normalize_text(None)  # type: ignore[arg-type]

    # Assert
    assert empty.folded == "" and empty.spans == ()
    assert none.folded == ""
    assert empty.quote(0, 3) == ""


def test_spans_length_matches_folded_text_even_when_translit_expands() -> None:
    # Arrange: x → «кс» даёт два символа на один исходный
    norm = normalize_text("x500  Shchuka")

    # Assert
    assert len(norm.spans) == len(norm.folded)
    assert norm.folded.startswith("кс500")


def test_quote_maps_folded_match_back_to_original_text() -> None:
    # Arrange
    norm = normalize_text("Ура! Р0ЗЫГРЫШ iPhone сегодня")
    start = norm.folded.index("розыгрыш")

    # Act
    quote = norm.quote(start, start + len("розыгрыш"))

    # Assert
    assert quote == "Р0ЗЫГРЫШ"


def test_quote_with_context_extends_to_whole_words() -> None:
    # Arrange
    norm = normalize_text("Ура! Р0ЗЫГРЫШ iPhone сегодня")
    start = norm.folded.index("розыгрыш")

    # Act
    quote = norm.quote(start, start + 3, context=2)

    # Assert
    assert quote == "Ура! Р0ЗЫГРЫШ"


def test_quote_of_translit_multichar_maps_to_full_source_letters() -> None:
    # Arrange
    norm = normalize_text("Shchuka")

    # Act
    quote = norm.quote(0, 1)  # «щ» в свёрнутом тексте

    # Assert
    assert quote == "Shch"
    assert norm.original_span(0, 1) == (0, 4)


def test_quote_returns_empty_for_empty_range() -> None:
    norm = normalize_text("розыгрыш")
    assert norm.quote(3, 3) == ""


@pytest.mark.parametrize("invisible", ["\u200b", "­", "‍", "﻿"])
def test_invisible_characters_do_not_break_words(invisible: str) -> None:
    # Arrange
    raw = f"Ро{invisible}зыгрыш"

    # Act
    folded = normalize_text(raw).folded

    # Assert
    assert "розыгрыш" in folded
