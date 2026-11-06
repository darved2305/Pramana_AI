"""Turn on-screen question text into text that Timbre reads the way a person would say it.

The screen keeps the text exactly as written ("network closet IDF-2", "breaker C2-7"), because
that is what is printed on the equipment. Spoken aloud, the same codes come out wrong: a speech
model may read "IDF" as a word, "DB-C2" as "dee-bee minus cee-two", or skip Latin letters in a
Devanagari sentence. ``speakable`` rewrites only equipment codes and labels:

- a code is a token with at least two capital letters, or capitals and digits, optionally
  joined by hyphens: ``IDF-2``, ``DB-C2``, ``C2-7``, ``MAIN-1``, ``ONT``, ``CCTV``,
  ``NAVA-WiFi``;
- parts that are real words (``GATEWAY``, ``INTERNET``, ``MAIN``) are read as words;
- other capital runs are spelled letter by letter, and digits inside a code are read one by one
  ("C2-7" is "C 2 7", never "C twenty-seven");
- in Hindi and Marathi, letters and digits of a code are written as their English names in
  Devanagari ("आई डी एफ टू"), which is how codes are said aloud in Indian offices, so the
  speech model never has to switch script mid-sentence.

Plain numbers outside codes ("room 205", "breaker number 7") and ordinary words are left as they
are. The function is pure and deterministic: the same text always gives the same speech text,
so synthesised audio stays cacheable.
"""

from __future__ import annotations

import re

from pramana_contracts import TemplateLanguage

_CODE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?![A-Za-z0-9])")
_RUNS = re.compile(r"[A-Z]+|[a-z]+|[0-9]+")

_DEVANAGARI = ("hi", "mr")

_WORDS: dict[str, dict[str, str]] = {
    # Code parts that are words people say as words, not letters.
    "GATEWAY": {"en": "gateway", "hi-en": "gateway", "hi": "गेटवे", "mr": "गेटवे"},
    "INTERNET": {"en": "internet", "hi-en": "internet", "hi": "इंटरनेट", "mr": "इंटरनेट"},
    "MAIN": {"en": "main", "hi-en": "main", "hi": "मेन", "mr": "मेन"},
    "NAVA": {"en": "Nava", "hi-en": "Nava", "hi": "नवा", "mr": "नवा"},
    "WIFI": {"en": "Wi-Fi", "hi-en": "WiFi", "hi": "वाई-फ़ाई", "mr": "वाय-फाय"},
}

_LETTERS: dict[str, dict[str, str]] = {
    "hi": dict(
        zip(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            [
                "ए",
                "बी",
                "सी",
                "डी",
                "ई",
                "एफ़",
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
            strict=True,
        )
    ),
    "mr": dict(
        zip(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            [
                "ए",
                "बी",
                "सी",
                "डी",
                "ई",
                "एफ",
                "जी",
                "एच",
                "आय",
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
                "व्ही",
                "डब्ल्यू",
                "एक्स",
                "वाय",
                "झेड",
            ],
            strict=True,
        )
    ),
}

_DIGITS: dict[str, list[str]] = {
    "hi": ["ज़ीरो", "वन", "टू", "थ्री", "फ़ोर", "फ़ाइव", "सिक्स", "सेवन", "एट", "नाइन"],
    "mr": ["झिरो", "वन", "टू", "थ्री", "फोर", "फाइव्ह", "सिक्स", "सेव्हन", "एट", "नाइन"],
}


_ORDINAL = re.compile(r"[0-9]+(?:st|nd|rd|th)", re.IGNORECASE)


def is_code(token: str) -> bool:
    """True for an equipment code or label that needs rewriting before it is spoken."""
    if _ORDINAL.fullmatch(token):
        return False  # "2nd" is a word, not a code
    capitals = sum(c.isupper() for c in token)
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    return capitals >= 2 or (capitals >= 1 and has_digit) or (has_digit and has_alpha)


def _letters(run: str, language: TemplateLanguage) -> list[str]:
    if language in _DEVANAGARI:
        return [_LETTERS[language][c] for c in run.upper()]
    return ["ay" if c == "A" else c for c in run.upper()]


def _digits(run: str, language: TemplateLanguage) -> list[str]:
    if language in _DEVANAGARI:
        return [_DIGITS[language][int(c)] for c in run]
    return list(run)


def _speak_part(part: str, language: TemplateLanguage) -> list[str]:
    word = _WORDS.get(part.upper())
    if word is not None and (part.isupper() or part.upper() == "WIFI"):
        return [word[language]]
    if part.isdigit():
        # A bare number between hyphens ("MAIN-1"): one digit at a time in a code.
        return _digits(part, language)
    out: list[str] = []
    for run in _RUNS.findall(part):
        if run.isdigit():
            out += _digits(run, language)
        elif run.isupper():
            out += _letters(run, language)
        elif out and language in _DEVANAGARI:
            # Lower-case letters inside a code ("WiFi" was handled above): spell them too, so
            # no Latin is left in a Devanagari sentence.
            out += _letters(run, language)
        else:
            out.append(run)
    return out


def _needs_rewrite(token: str, language: TemplateLanguage) -> bool:
    if language in _DEVANAGARI and any(c.isupper() for c in token):
        return True  # even one Latin capital ("block C") is read as a letter name
    if not is_code(token):
        return False
    parts = token.split("-")
    # "Wi-Fi" is a word with capitals, not a code: no digit, no part is a code or a known word.
    return any(c.isdigit() for c in token) or any(is_code(p) or p.upper() in _WORDS for p in parts)


def _rewrite(match: re.Match[str], language: TemplateLanguage) -> str:
    token = match.group(0)
    if not _needs_rewrite(token, language):
        return token
    parts = token.split("-")
    spoken: list[str] = []
    for part in parts:
        spoken += _speak_part(part, language)
    return " ".join(spoken)


def speakable(text: str, language: TemplateLanguage) -> str:
    """The text to send to speech synthesis for ``text`` shown in ``language``."""
    return _CODE.sub(lambda m: _rewrite(m, language), text)


RAW_CODE = re.compile(r"[A-Z]{2,}|[A-Za-z][0-9]|[0-9][A-Za-z]|[A-Za-z0-9]-[0-9]|[0-9]-[A-Za-z]")
"""What must never reach speech synthesis: capital runs and letter-digit codes."""
