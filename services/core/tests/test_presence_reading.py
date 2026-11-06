"""Reading a presence-token answer (typed or transcribed) into the characters people meant."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pramana_core.language.presence import read_code
from pramana_core.language.speakable import speakable


@pytest.mark.parametrize(
    ("text", "reading"),
    [
        ("K7Q", "K7Q"),
        ("k7q", "K7Q"),
        ("K 7 Q", "K7Q"),
        ("it says K-7-Q", "K7Q"),
        ("The label says AF5.", "AF5"),
        ("kay seven queue", "K7Q"),
        ("ef aitch nine", "FH9"),
        ("last three are X Y 4", "XY4"),
        ("label pe K7Q likha hai", "K7Q"),
        ("के सात क्यू", "K7Q"),
        ("ए एफ़ पाँच", "AF5"),
        ("एक्स वाय नऊ", "XY9"),  # Marathi
        ("के ७ क्यू", "K7Q"),  # Devanagari numerals
        ("saat aath nau", "789"),
        ("AB-12-K7Q", "K7Q"),  # only the last three are asked for
    ],
)
def test_readings(text: str, reading: str) -> None:
    assert read_code(text) == reading


@pytest.mark.parametrize(
    "text",
    [
        "I can't see any label",
        "pata nahi, label nahi dikh raha",
        "मुझे नहीं पता",
        "मला दिसत नाही",
        "",
        "do you want me to go there?",
    ],
)
def test_non_readings_give_no_three_character_code(text: str) -> None:
    """Saying you cannot see it is not a reading. (One stray letter may survive, like the "I"
    in "I can't", but never a full code, so the check fails as it should.)"""
    assert len(read_code(text)) < 3


def test_repeated_a_code_letters_are_speakable_and_readable() -> None:
    spoken = speakable("AAA", "en")
    assert spoken == "ay ay ay"
    assert read_code(spoken) == "AAA"


@given(st.text(alphabet="AFHKLMQRXY345679", min_size=3, max_size=3))
def test_a_value_spoken_by_our_own_speech_text_reads_back(value: str) -> None:
    """What Timbre is given for a code in Hindi or Marathi reads back to the same code, so a
    person repeating the speech form ("के सात क्यू") passes."""
    for lang in ("hi", "mr", "en", "hi-en"):
        assert read_code(speakable(value, lang)) == value, (lang, speakable(value, lang))


ALPHABET = "AFHKLMQRXY345679"
_EN = {"A": "ay", "F": "eff", "H": "aitch", "K": "kay", "L": "el", "M": "em", "Q": "cue"}
_EN |= {"R": "are", "X": "ex", "Y": "why", "3": "three", "4": "four", "5": "five"}
_EN |= {"6": "six", "7": "seven", "9": "nine"}


@given(st.text(alphabet=ALPHABET, min_size=3, max_size=3))
def test_every_code_reads_back_however_it_is_typed_or_said(value: str) -> None:
    """Typed in small letters on a phone, read out with spaces, said as English letter names
    (including codes made only of names that are also words, like "el em are"), or transcribed
    in capitals that happen to spell a letter name ("KAY"): an honest reading passes."""
    for text in (
        value,
        value.lower(),
        " ".join(value),
        " ".join(value.lower()),
        " ".join(_EN[c] for c in value),
        f"the label says {' '.join(value)}",
    ):
        assert read_code(text) == value, text
