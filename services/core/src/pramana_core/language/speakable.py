"""Normalize display text for natural, deterministic speech synthesis.

The participant-visible question is kept as written. This module produces only the text sent to
Timbre, and intentionally leaves ordinary number formatting to Timbre's language-aware rules.
"""

from __future__ import annotations

import re

from pramana_contracts import TemplateLanguage

_LETTER_NAMES: dict[TemplateLanguage, dict[str, str]] = {
    "en": {letter: letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    "hi-en": {letter: letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    "hi": {
        "A": "ए",
        "B": "बी",
        "C": "सी",
        "D": "डी",
        "E": "ई",
        "F": "एफ",
        "G": "जी",
        "H": "एच",
        "I": "आई",
        "J": "जे",
        "K": "के",
        "L": "एल",
        "M": "एम",
        "N": "एन",
        "O": "ओ",
        "P": "पी",
        "Q": "क्यू",
        "R": "आर",
        "S": "एस",
        "T": "टी",
        "U": "यू",
        "V": "वी",
        "W": "डब्ल्यू",
        "X": "एक्स",
        "Y": "वाई",
        "Z": "ज़ेड",
    },
    "mr": {
        "A": "ए",
        "B": "बी",
        "C": "सी",
        "D": "डी",
        "E": "ई",
        "F": "एफ",
        "G": "जी",
        "H": "एच",
        "I": "आय",
        "J": "जे",
        "K": "के",
        "L": "एल",
        "M": "एम",
        "N": "एन",
        "O": "ओ",
        "P": "पी",
        "Q": "क्यू",
        "R": "आर",
        "S": "एस",
        "T": "टी",
        "U": "यू",
        "V": "वी",
        "W": "डब्ल्यू",
        "X": "एक्स",
        "Y": "वाय",
        "Z": "झेड",
    },
}

_DIGIT_NAMES: dict[TemplateLanguage, tuple[str, ...]] = {
    "en": ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"),
    "hi-en": (
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
    ),
    "hi": ("ज़ीरो", "वन", "टू", "थ्री", "फोर", "फाइव", "सिक्स", "सेवन", "एट", "नाइन"),
    "mr": ("झिरो", "वन", "टू", "थ्री", "फोर", "फाइव्ह", "सिक्स", "सेव्हन", "एट", "नाइन"),
}

_WIFI: dict[TemplateLanguage, str] = {
    "en": "Wi-Fi",
    "hi-en": "Wi-Fi",
    "hi": "वाई-फ़ाई",
    "mr": "वाय-फाय",
}
_GATEWAY: dict[TemplateLanguage, str] = {
    "en": "gateway",
    "hi-en": "gateway",
    "hi": "गेटवे",
    "mr": "गेटवे",
}
_NAVA_WIFI: dict[TemplateLanguage, str] = {
    "en": "Nava Wi-Fi",
    "hi-en": "NAVA Wi-Fi",
    "hi": "नावा वाई-फ़ाई",
    "mr": "नावा वाय-फाय",
}
_ABBREVIATIONS: dict[str, dict[TemplateLanguage, str]] = {
    "IP": {"en": "I P", "hi-en": "I P", "hi": "आई पी", "mr": "आय पी"},
    "CCTV": {
        "en": "C C T V",
        "hi-en": "C C T V",
        "hi": "सी सी टी वी",
        "mr": "सी सी टी व्ही",
    },
    "ONT": {"en": "O N T", "hi-en": "O N T", "hi": "ओ एन टी", "mr": "ओ एन टी"},
    "PON": {"en": "P O N", "hi-en": "P O N", "hi": "पी ओ एन", "mr": "पी ओ एन"},
}

_NAVA_WIFI_PATTERN = re.compile(r"(?<!\w)NAVA[-\s]+Wi-?Fi(?!\w)", re.IGNORECASE)
_WIFI_PATTERN = re.compile(r"(?<!\w)Wi-?Fi(?!\w)", re.IGNORECASE)
_IDENTIFIER_PATTERN = re.compile(
    r"(?<!\w)(?P<identifier>(?:[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)+|[A-Z]{2,}\d+))(?!\w)"
)
_IPV4_PATTERN = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w|\.\d)")
_QUOTED_NAME_PATTERN = re.compile(r"(?<!\w)['‘](?P<name>[^'’]+)['’](?!\w)")
_DOUBLE_QUOTED_NAME_PATTERN = re.compile(r'(?<!\w)"(?P<name>[^"]+)"(?!\w)')
_GATEWAY_PATTERN = re.compile(r"(?<!\w)GATEWAY(?!\w)", re.IGNORECASE)
_ABBREVIATION_PATTERNS = {
    word: re.compile(rf"(?<!\w){word}(?!\w)", re.IGNORECASE) for word in _ABBREVIATIONS
}


def _identifier_words(identifier: str, language: TemplateLanguage) -> str:
    names = _LETTER_NAMES[language]
    digits = _DIGIT_NAMES[language]
    parts = re.findall(r"[A-Z]+|[0-9]+", identifier.upper())
    words = [
        names[char] if part.isalpha() else digits[int(char)] for part in parts for char in part
    ]
    return " ".join(words)


def speakable(text: str, language: TemplateLanguage) -> str:
    """Return text for Timbre, with deterministic pronunciation for site labels and acronyms.

    Timbre already expands normal numbers, so room numbers stay numeric (for example, ``room
    205``). IDs are spelled character by character, and language-sensitive terms use the
    participant's selected language explicitly.
    """
    result = _QUOTED_NAME_PATTERN.sub(lambda match: match.group("name"), text)
    result = _DOUBLE_QUOTED_NAME_PATTERN.sub(lambda match: match.group("name"), result)
    result = result.replace("“", "").replace("”", "")

    def replace_ip_address(match: re.Match[str]) -> str:
        dot = "डॉट" if language in ("hi", "mr") else "dot"
        return f" {dot} ".join(
            " ".join(_DIGIT_NAMES[language][int(digit)] for digit in octet)
            for octet in match.group().split(".")
        )

    result = _IPV4_PATTERN.sub(replace_ip_address, result)
    result = _NAVA_WIFI_PATTERN.sub(_NAVA_WIFI[language], result)
    result = _WIFI_PATTERN.sub(_WIFI[language], result)
    result = _GATEWAY_PATTERN.sub(_GATEWAY[language], result)

    for acronym, by_language in _ABBREVIATIONS.items():
        result = _ABBREVIATION_PATTERNS[acronym].sub(by_language[language], result)

    result = _IDENTIFIER_PATTERN.sub(
        lambda match: _identifier_words(match.group("identifier"), language), result
    )
    result = re.sub(r"(?:\.{3,}|…+)", ",", result)
    result = re.sub(r"\s+([,;:.?!])", r"\1", result)
    result = re.sub(r",\s*([?!])", r"\1", result)
    result = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", result)
    result = re.sub(r"([?!])[?!]+", r"\1", result)
    result = re.sub(r"\s+", " ", result)
    return result.strip()
