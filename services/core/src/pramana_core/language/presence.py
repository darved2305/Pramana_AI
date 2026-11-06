"""Normalize spoken or typed alphanumeric answers to a location challenge."""

from __future__ import annotations

import re
import unicodedata

_TOKEN = re.compile(r"[a-z]+|[0-9]+|[\u0966-\u096f]+|[\u0900-\u097f]+", re.IGNORECASE)
_REFUSAL = frozenset(
    {
        "cannot",
        "can't",
        "cant",
        "couldnt",
        "couldn't",
        "unable",
        "nahi",
        "nahin",
        "nahī",
        "नहीं",
        "नही",
        "नाही",
        "नाहीत",
        "unsure",
        "unknown",
        "असमर्थ",
    }
)
_REFUSAL_PATTERN = re.compile(r"\b(?:can(?:not|['’]?t)|could(?:not|['’]?t))\b")
_LETTER_NAMES: dict[str, str] = {}


def _add(letter: str, *names: str) -> None:
    for name in names:
        _LETTER_NAMES[name.casefold()] = letter


_add("A", "a", "ay", "ए")
_add("B", "b", "bee", "be", "बी")
_add("C", "c", "cee", "see", "sea", "सी")
_add("D", "d", "dee", "डी")
_add("E", "e", "ee", "ई")
_add("F", "f", "eff", "ef", "एफ")
_add("G", "g", "gee", "जी")
_add("H", "h", "aitch", "haitch", "एच")
_add("I", "i", "eye", "aye", "आई", "आय")
_add("J", "j", "jay", "जे")
_add("K", "k", "kay", "के", "क")
_add("L", "l", "el", "एल")
_add("M", "m", "em", "एम")
_add("N", "n", "en", "एन")
_add("O", "o", "oh", "ओ")
_add("P", "p", "pee", "पी")
_add("Q", "q", "cue", "queue", "क्यू")
_add("R", "r", "are", "आर")
_add("S", "s", "ess", "एस")
_add("T", "t", "tee", "टी")
_add("U", "u", "you", "यू")
_add("V", "v", "vee", "वी")
_add("W", "w", "doubleyou", "doubleu", "डब्ल्यू")
_add("X", "x", "ex", "एक्स")
_add("Y", "y", "why", "वाई", "वाय")
_add("Z", "z", "zee", "zed", "ज़ेड", "जेड", "झेड")

_DIGIT_NAMES: dict[str, str] = {}


def _add_digit(value: str, *names: str) -> None:
    for name in names:
        _DIGIT_NAMES[name.casefold()] = value


_add_digit("0", "zero", "शून्य", "शुन्य", "झिरो", "shunya", "shoonya")
_add_digit("1", "one", "एक", "एक", "ek", "वन")
_add_digit("2", "two", "दो", "दोन", "do", "don", "टू")
_add_digit("3", "three", "तीन", "teen", "tin", "थ्री")
_add_digit("4", "four", "चार", "chaar", "char", "फोर")
_add_digit("5", "five", "पांच", "पाँच", "पाच", "paanch", "panch", "फाइव", "फाइव्ह")
_add_digit("6", "six", "छह", "छे", "सहा", "chhe", "che", "saha", "सिक्स")
_add_digit("7", "seven", "सात", "सात", "saat", "sat", "सेवन", "सेव्हन")
_add_digit("8", "eight", "आठ", "aath", "ath", "एट")
_add_digit("9", "nine", "नौ", "नऊ", "नव", "nau", "nao", "नाइन")


def _digits(token: str) -> str | None:
    try:
        return "".join(str(unicodedata.digit(char)) for char in token)
    except (TypeError, ValueError):
        return None


def normalize_presence_answer(text: str, expected_length: int = 3) -> str | None:
    """Return uppercase ASCII characters only when the complete answer has the expected length.

    The recognizer often returns either letter names (``kay saat queue``) or Devanagari
    transliterations (``के सात क्यू``). Unknown filler is ignored, while refusals and incomplete,
    overlong or unrelated answers return ``None``.
    """
    if expected_length < 1:
        raise ValueError("expected_length must be positive")
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    tokens = _TOKEN.findall(normalized)
    if (
        not tokens
        or _REFUSAL_PATTERN.search(normalized) is not None
        or any(token in _REFUSAL for token in tokens)
    ):
        return None

    output: list[str] = []
    for token in tokens:
        numeric = _digits(token)
        if numeric is not None:
            output.extend(numeric)
        elif token in _DIGIT_NAMES:
            output.append(_DIGIT_NAMES[token])
        elif token in _LETTER_NAMES:
            output.append(_LETTER_NAMES[token])
        if len(output) > expected_length:
            return None

    if len(output) != expected_length:
        return None
    return "".join(output)


def presence_answer_keyterms() -> list[str]:
    """All supported spoken character names and digit names for question-conditioned STT."""
    return sorted(set(_LETTER_NAMES) | set(_DIGIT_NAMES))


__all__ = ["normalize_presence_answer", "presence_answer_keyterms"]
