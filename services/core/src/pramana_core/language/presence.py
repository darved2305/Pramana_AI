"""Read a presence-token answer ("K 7 Q", "kay seven queue", "के सात क्यू") into characters.

The value itself is never known to the core: the reading is sent to the simulator, which
compares it. So this only has to turn the ways people say letters and digits into the
characters they mean, and keep everything else ("the label says", "hai") out.

Kept: Latin tokens that look like a code (all capitals as transcribed, or containing a digit,
or a single letter), spoken letter and digit names in English, Hindi and Marathi, and Devanagari
digits. The reading is the last ``length`` characters, since the question asks for the last
three on the label.
"""

from __future__ import annotations

import re

from .speakable import _DIGITS, _LETTERS

_TOKEN = re.compile(r"[^\s,.;:!?।॥\"“”()\-/]+")
"""Words, with apostrophes kept inside them ("can't" is one word, not "can" and "t")."""

_EN_LETTERS: dict[str, str] = {
    "ay": "A",
    "eh": "A",
    "bee": "B",
    "cee": "C",
    "see": "C",
    "dee": "D",
    "ee": "E",
    "ef": "F",
    "eff": "F",
    "gee": "G",
    "jee": "G",
    "aitch": "H",
    "aych": "H",
    "edge": "H",
    "haitch": "H",
    "jay": "J",
    "kay": "K",
    "kai": "K",
    "kae": "K",
    "el": "L",
    "ell": "L",
    "em": "M",
    "en": "N",
    "oh": "O",
    "pee": "P",
    "queue": "Q",
    "cue": "Q",
    "kyu": "Q",
    "kew": "Q",
    "ar": "R",
    "are": "R",
    "aar": "R",
    "es": "S",
    "ess": "S",
    "tee": "T",
    "you": "U",
    "yu": "U",
    "vee": "V",
    "ex": "X",
    "eks": "X",
    "why": "Y",
    "wai": "Y",
    "vai": "Y",
    "zed": "Z",
    "zee": "Z",
}
_EN_DIGITS: dict[str, str] = {
    w: str(i)
    for i, ws in enumerate(
        [
            ["zero", "jero"],
            ["one", "won"],
            ["two", "too"],
            ["three", "tree"],
            ["four", "for"],
            ["five"],
            ["six"],
            ["seven"],
            ["eight"],
            ["nine"],
        ]
    )
    for w in ws
}
_INDIC_DIGITS: dict[str, str] = {
    w: str(i)
    for i, ws in enumerate(
        [
            ["शून्य", "सुन्ना"],
            ["एक"],
            ["दो", "दोन"],
            ["तीन"],
            ["चार"],
            ["पाँच", "पांच", "पाच"],
            ["छह", "छः", "छे", "सहा"],
            ["सात"],
            ["आठ"],
            ["नौ", "नऊ"],
        ]
    )
    for w in ws
}
_HINGLISH_DIGITS: dict[str, str] = {
    "ek": "1",
    "do": "2",
    "teen": "3",
    "char": "4",
    "chaar": "4",
    "paanch": "5",
    "panch": "5",
    "chhe": "6",
    "chheh": "6",
    "saat": "7",
    "aath": "8",
    "nau": "9",
}
_DEVANAGARI_NUMERALS = {chr(0x0966 + i): str(i) for i in range(10)}


def _spoken_names() -> dict[str, str]:
    names = dict(_EN_LETTERS) | _EN_DIGITS | _HINGLISH_DIGITS | _INDIC_DIGITS
    for table in _LETTERS.values():
        names |= {name: letter for letter, name in table.items()}
    for digit_names in _DIGITS.values():
        names |= {name: str(i) for i, name in enumerate(digit_names)}
    # Common spellings the tables do not use.
    names |= {"एफ": "F", "आय": "I", "वाय": "Y", "क्यु": "Q", "एक्स": "X", "एच": "H", "ऐच": "H"}
    return names


_NAMES = _spoken_names()
_AMBIGUOUS = {
    "ek",
    "do",
    "are",
    "you",
    "see",
    "too",
    "for",
    "won",
    "oh",
    "en",
    "el",
    "em",
    "एक",
    "दो",
}
"""Spoken names that are also common words: read only next to other code characters."""


def read_code(text: str, length: int = 3) -> str:
    """The characters a person read out, or an empty string if they read none."""
    raw = _TOKEN.findall(text)
    pieces: list[tuple[str, bool]] = []  # (characters, sure it is part of the code)
    for tok in raw:
        low = tok.casefold()
        if low in ("i", "a"):
            pieces.append((tok.upper(), False))  # English words unless next to a code
        elif low in _NAMES:
            pieces.append((_NAMES[low], low not in _AMBIGUOUS))
        elif all(c in _DEVANAGARI_NUMERALS for c in tok):
            pieces.append(("".join(_DEVANAGARI_NUMERALS[c] for c in tok), True))
        elif (
            tok.isascii()
            and tok.isalnum()
            and (tok.isupper() or any(c.isdigit() for c in tok) or len(tok) == 1)
        ):
            pieces.append((tok.upper(), True))
        else:
            pieces.append(("", False))  # an ordinary word breaks a run of code characters
    # Keep each unbroken run of code characters that has at least one certain piece in it.
    out: list[str] = []
    run: list[tuple[str, bool]] = []
    for chars, sure in [*pieces, ("", False)]:
        if chars:
            run.append((chars, sure))
            continue
        if any(s for _, s in run):
            out += [c for c, _ in run]
        run = []
    return "".join(out)[-length:] if out else ""
