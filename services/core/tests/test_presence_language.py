from __future__ import annotations

import pytest

from pramana_core.language.presence import normalize_presence_answer


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("K 7 Q", "K7Q"),
        ("ACF", "ACF"),
        ("acf", "ACF"),
        ("k seven q", "K7Q"),
        ("के सात क्यू", "K7Q"),
        ("के सेव्हन क्यू", "K7Q"),
        ("kay saat queue", "K7Q"),
        ("K, ७, Q!", "K7Q"),
        ("क ७ क्यू", "K7Q"),
    ],
)
def test_presence_answer_normalizes_supported_scripts_and_languages(
    spoken: str, expected: str
) -> None:
    assert normalize_presence_answer(spoken, expected_length=3) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("I cannot see a label", None),
        ("I can't see the label; it says K 7 Q", None),
        ("can't K 7", None),
        ("can’t K 7", None),
        ("K five Q", "K5Q"),
        ("के पांच क्यू", "K5Q"),
        ("के पाच क्यू", "K5Q"),
        ("K 55 Q", None),
        ("the light is green", None),
        ("", None),
    ],
)
def test_presence_answer_rejects_refusals_wrong_lengths_and_unrelated_speech(
    spoken: str, expected: str | None
) -> None:
    assert normalize_presence_answer(spoken, expected_length=3) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("ay bee see", "ABC"),
        ("डी ई एफ", "DEF"),
        ("जी एच जे", "GHJ"),
        ("kay el em", "KLM"),
        ("en pee cue", "NPQ"),
        ("आर एस टी", "RST"),
        ("यू वी डब्ल्यू", "UVW"),
        ("एक्स वाई ज़ेड", "XYZ"),
    ],
)
def test_letter_name_vocabulary_is_exhaustive_for_supported_alphabets(
    spoken: str, expected: str
) -> None:
    assert normalize_presence_answer(spoken, expected_length=3) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    list(
        zip(
            [
                "ay",
                "bee",
                "see",
                "dee",
                "ee",
                "eff",
                "gee",
                "aitch",
                "eye",
                "jay",
                "kay",
                "el",
                "em",
                "en",
                "oh",
                "pee",
                "queue",
                "are",
                "ess",
                "tee",
                "you",
                "vee",
                "doubleyou",
                "ex",
                "why",
                "zed",
            ],
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            strict=True,
        )
    ),
)
def test_every_english_letter_name_normalizes(spoken: str, expected: str) -> None:
    assert normalize_presence_answer(spoken, expected_length=1) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    list(
        zip(
            [
                "ए",
                "बी",
                "सी",
                "डी",
                "ई",
                "एफ",
                "जी",
                "एच",
                "आई",
                "जे",
                "के",
                "एल",
                "एम",
                "एन",
                "ओ",
                "पी",
                "क्यू",
                "आर",
                "एस",
                "टी",
                "यू",
                "वी",
                "डब्ल्यू",
                "एक्स",
                "वाई",
                "ज़ेड",
            ],
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            strict=True,
        )
    ),
)
def test_every_devanagari_letter_name_normalizes(spoken: str, expected: str) -> None:
    assert normalize_presence_answer(spoken, expected_length=1) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    list(
        zip(
            ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
            "0123456789",
            strict=True,
        )
    ),
)
def test_every_english_digit_name_normalizes(spoken: str, expected: str) -> None:
    assert normalize_presence_answer(spoken, expected_length=1) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    list(
        zip(
            ["शून्य", "एक", "दो", "तीन", "चार", "पांच", "छह", "सात", "आठ", "नौ"],
            "0123456789",
            strict=True,
        )
    ),
)
def test_every_hindi_digit_name_normalizes(spoken: str, expected: str) -> None:
    assert normalize_presence_answer(spoken, expected_length=1) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    list(
        zip(
            ["शून्य", "एक", "दोन", "तीन", "चार", "पाच", "सहा", "सात", "आठ", "नऊ"],
            "0123456789",
            strict=True,
        )
    ),
)
def test_every_marathi_digit_name_normalizes(spoken: str, expected: str) -> None:
    assert normalize_presence_answer(spoken, expected_length=1) == expected
