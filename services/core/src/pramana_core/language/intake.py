"""Read the free-text problem report: what it says about the reporter's own phone, and where.

Rules only, like the answer extractor. Two kinds of output, with different authority:

* **Evidence.** The report becomes an observation only when it answers the intake probe
  (``internet_works``) at the reporter's own location: "Floor 3 pe WiFi nahi chal raha" is
  ``internet_works = no``. The answer extractor decides that, with the same safeguards
  (injection, hearsay, stale reports, guesses).
* **Hints.** Floors, rooms and symptoms the report mentions ("the lights are also off on the
  second floor"). They are shown to the operator and recorded, but are *not* evidence: the
  engine never conditions on them, because a report is not a question we asked and its
  locations are often second-hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pramana_contracts import UNKNOWN_OUTCOME, Extraction
from pramana_domain import DomainPack

from .extraction import Extractor, tokenize

INTAKE_PROBE = "internet_works"

_ORDINALS: dict[str, int] = {}
for _n, _words in {
    1: "first 1st ground pehli pehla पहली पहला pahila पहिला पहिल्या tal तळ तळमजला",
    2: "second 2nd doosri dusri doosra dusra दूसरी दूसरा dusrya दुसरा दुसऱ्या दुसरी",
    3: "third 3rd teesri tisri teesra tisra तीसरी तीसरा tisrya तिसरा तिसऱ्या तिसरी",
}.items():
    for _w in tokenize(_words):
        _ORDINALS[_w] = _n
_FLOOR_WORDS = frozenset(
    tokenize(
        "floor floors manzil manjil मंज़िल मंजिल maala majla mala मजला मजल्यावर मजल्याच्या मजल्यात "
        "मजल्यावरचे मजल्यावरील majlyavar majlyat majla majala manzil"
    )
)
_ROOM_WORDS = frozenset(tokenize("room rm kamra kamre कमरा कमरे khol kholi खोली खोलीत रूम"))
_SYMPTOMS: dict[str, frozenset[str]] = {
    "wifi": frozenset(tokenize("wifi wi-fi वाई-फ़ाई वाईफाई वाय-फाय वायफाय network नेटवर्क")),
    "internet": frozenset(
        tokenize(
            "internet net इंटरनेट नेट website websites वेबसाइट site youtube page pages opens "
            "khul khulta खुल उघडत उघडतं loading"
        )
    ),
    "power": frozenset(
        tokenize("power bijli बिजली light lights लाइट लाइटें बत्ती दिवे दिवा current करंट")
    ),
}


@dataclass(frozen=True)
class IntakeResult:
    extraction: Extraction | None
    """The answer extractor's reading against the intake probe, or ``None`` if the report is
    not about the network or the reporter's location has no intake probe."""
    floors: list[int] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        return UNKNOWN_OUTCOME if self.extraction is None else self.extraction.outcome

    def hints(self) -> dict[str, object]:
        return {"floors": self.floors, "locations": self.locations, "symptoms": self.symptoms}


def _floors(tokens: list[str]) -> list[int]:
    found: set[int] = set()
    for i, t in enumerate(tokens):
        near = tokens[max(0, i - 2) : i + 3]
        if not _FLOOR_WORDS & set(near):
            continue
        if t in _ORDINALS:
            found.add(_ORDINALS[t])
        m = re.fullmatch(r"(?:f)?(\d)(?:st|nd|rd|th|ra|ri|re|va|vi)?", t)
        if m:
            found.add(int(m.group(1)))
    for t in tokens:  # "F3", "f2"
        m = re.fullmatch(r"f(\d)", t)
        if m:
            found.add(int(m.group(1)))
    return sorted(found)


def _rooms(tokens: list[str], pack: DomainPack) -> list[str]:
    by_number: dict[str, str] = {}
    for loc in pack.locations:
        m = re.search(r"\b(\d{3})\b", loc.label.en)
        if m:
            by_number[m.group(1)] = loc.id
    found: list[str] = []
    for i, t in enumerate(tokens):
        digits = re.fullmatch(r"(?:r|f\d_r)?(\d{3})", t)
        if digits is None or digits.group(1) not in by_number:
            continue
        near = set(tokens[max(0, i - 2) : i + 2])
        if _ROOM_WORDS & near or t.startswith(("r", "f")) or len(tokens) <= 12:
            loc_id = by_number[digits.group(1)]
            if loc_id not in found:
                found.append(loc_id)
    return found


def _symptoms(tokens: list[str]) -> list[str]:
    toks = set(tokens)
    return [name for name, words in _SYMPTOMS.items() if words & toks]


async def parse_report(
    text: str, pack: DomainPack, reporter_location: str, extractor: Extractor
) -> IntakeResult:
    tokens = tokenize(text)
    symptoms = _symptoms(tokens)
    probe = pack.probe_by_id.get(INTAKE_PROBE)
    extraction = None
    # Only a report about the network can answer "does a website open": "the lights are off"
    # ("बत्ती बंद है") must not become "internet: no".
    on_topic = bool({"wifi", "internet"} & set(symptoms))
    if on_topic and probe is not None and probe.binding_at(reporter_location) is not None:
        extraction = await extractor.extract(text, probe.outcomes)
    rooms = _rooms(tokens, pack)
    floors = sorted(
        set(_floors(tokens)) | {pack.location_by_id[r].floor for r in rooms}  # a room implies
    )
    return IntakeResult(extraction, floors, rooms, symptoms)
