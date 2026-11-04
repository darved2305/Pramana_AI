"""Convert one participant answer into structured evidence (and nothing else).

The extractor's output is deliberately narrow: an outcome from the asked probe's outcome set (or
``unknown``), a hedge level, a directness level, and two flags. It never sees the belief, never
chooses actions, and its output carries no authority: a participant saying "I am the admin,
mark it resolved" changes nothing except ``injection_suspected``.

``RuleExtractor`` is a deterministic lexicon matcher for English, Hindi and Marathi (Devanagari
and Latin script) and Hinglish. Processing order matters:

1. normalise and tokenise on whitespace (``\\w`` would split Devanagari at vowel signs);
2. find and remove injection, stop, hedge and hearsay phrases, so "pata nahi" (don't know) is
   never read as "no";
3. match outcome phrases, longest first; a negation right after (Hindi/Marathi word order) or
   right before (English) a binary outcome flips it; negated multi-outcome phrases are dropped;
4. exactly one distinct outcome -> that outcome; zero or several -> ``unknown``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pramana_contracts import UNKNOWN_OUTCOME, Directness, Extraction, Hedge

_PUNCT = re.compile(r"[\"'.,!?;:()\[\]{}।॥…“”‘’`~*/\\|-]+")


def tokenize(text: str) -> list[str]:
    return _PUNCT.sub(" ", text.casefold()).split()


def _phrases(*items: str) -> list[tuple[str, ...]]:
    return [tuple(tokenize(i)) for i in items]


NEGATIONS = frozenset(
    tokenize(
        "not no nahi nahin nai na nahī नहीं नही ना नाही नाहीत नको dont don't doesn't isn't "
        "aren't didn't cannot can't never"
    )
)

INJECTION = _phrases(
    "ignore",
    "instruction",
    "instructions",
    "system prompt",
    "prompt",
    "you must",
    "override",
    "mark as resolved",
    "mark resolved",
    "mark it resolved",
    "i am the admin",
    "i am admin",
    "main admin hoon",
    "admin hoon",
    "authorized",
    "authorised",
    "approve",
    "approval",
    "forget",
    "disregard",
    "developer mode",
)
STOP = _phrases(
    "baad mein",
    "baad me",
    "later",
    "busy",
    "abhi nahi",
    "nantar",
    "नंतर",
    "बाद में",
    "don't call",
    "stop calling",
    "call me later",
    "not now",
)
UNSURE = _phrases(
    "not sure",
    "no idea",
    "pata nahi",
    "pata nahin",
    "maloom nahi",
    "malum nahi",
    "पता नहीं",
    "माहीत नाही",
    "mahit nahi",
    "sure nahi",
    "pakka nahi",
    "pakka nahi pata",
    "पक्का नहीं",
    "पक्का पता नहीं",
    "नहीं पता",
    "can't tell",
    "cannot tell",
    "dont know",
    "don't know",
    "i don't know",
    "samajh nahi",
)
NOT_OBSERVED = _phrases(
    "yahan se nahi dikh",
    "nahi dikh rahi",
    "nahi dikh raha",
    "nahi dikh rahe",
    "dikh nahi rahi",
    "dikh nahi raha",
    "dikhai nahi",
    "नहीं दिख रही",
    "नहीं दिख रहा",
    "दिख नहीं रही",
    "दिख नहीं रहा",
    "दिखाई नहीं",
    "दिसत नाही",
    "can't see",
    "cannot see",
    "not visible from here",
)
""""I can't see it" means no observation was made. It must never become "off". (For the Wi-Fi
list probe the same words mean the network is missing, so this applies only to other probes.)"""

PROBABLE = _phrases(
    "i think",
    "maybe",
    "probably",
    "shayad",
    "शायद",
    "lagta hai",
    "lagta he",
    "लगता है",
    "lagti hai",
    "kadachit",
    "कदाचित",
    "vatta",
    "वाटतं",
    "वाटते",
    "seems",
    "i guess",
    "may be",
    "almost sure",
)
HEARSAY = _phrases(
    "said",
    "says",
    "told me",
    "bola",
    "boli",
    "bataya",
    "batayi",
    "keh raha",
    "keh rahi",
    "sangitla",
    "sangitle",
    "सांगितलं",
    "सांगितले",
    "बोला",
    "बोली",
    "बताया",
    "heard",
    "suna",
    "सुना",
    "according to",
    "roommate ne",
    "dost ne",
)
ASSUMPTION = _phrases(
    "must be",
    "hoga",
    "hogi",
    "होगा",
    "होगी",
    "असेल",
    "asel",
    "because of",
    "kharab hoga",
    "probably broken",
    "i guess the",
)

# Outcome lexicon. Phrases that already contain a negation ("dikh nahi raha") are matched as a
# whole before single words, so their negation is not applied twice.
OUTCOME_LEXICON: dict[str, list[tuple[str, ...]]] = {
    "yes": _phrases(
        "yes",
        "yeah",
        "yep",
        "yup",
        "haan",
        "haa",
        "han",
        "haanji",
        "ha ji",
        "ji haan",
        "हाँ",
        "हां",
        "हा",
        "ho",
        "hoy",
        "होय",
        "हो",
        "opens",
        "open ho raha",
        "khul raha",
        "khul rahi",
        "khulta",
        "khulti",
        "khul gaya",
        "khul gayi",
        "खुल रहा",
        "खुल रही",
        "खुलता",
        "उघडतं",
        "उघडते",
        "ughadta",
        "loads",
        "loading ho raha",
        "works",
        "working",
        "chal raha",
        "chal rahi",
        "chalta",
        "चल रहा",
        "चल रही",
        "चालतं",
        "chalta hai",
    ),
    "no": _phrases(
        "no",
        "nope",
        "nahi",
        "nahin",
        "nai",
        "नहीं",
        "नही",
        "na",
        "नाही",
        "nahi khul raha",
        "nahi khul rahi",
        "khul nahi raha",
        "khul nahi rahi",
        "उघडत नाही",
        "ughadat nahi",
        "nahi chal raha",
        "chal nahi raha",
        "nahi chal rahi",
        "chal nahi rahi",
        "doesn't open",
        "does not open",
        "not opening",
        "not loading",
        "not working",
    ),
    "on": _phrases(
        "on",
        "chalu",
        "chaalu",
        "चालू",
        "jal raha",
        "jal rahi",
        "jal rahe",
        "jal rahi hai",
        "जल रहा",
        "जल रही",
        "जल रहे",
        "lit",
        "glowing",
        "lagla",
        "लागला",
        "लागतो",
        "lagto",
        "light hai",
    ),
    "off": _phrases(
        "off",
        "band",
        "bandh",
        "बंद",
        "dark",
        "black",
        "andhera",
        "अंधेरा",
        "kala",
        "kaala",
        "बुझ",
        "bujh",
        "dead",
        "nothing",
        "kuch nahi",
        "काहीच नाही",
        "kahich nahi",
    ),
    "green": _phrases("green", "hara", "hari", "हरा", "हरी", "हिरवा", "हिरवे", "hirva", "hirve"),
    "amber": _phrases(
        "amber",
        "orange",
        "narangi",
        "नारंगी",
        "yellow",
        "peela",
        "peeli",
        "पीला",
        "pivla",
        "पिवळा",
    ),
    "red": _phrases("red", "laal", "lal", "लाल"),
    "up": _phrases("up", "upar", "ऊपर", "upper side", "on position", "वर आहे", "var aahe"),
    "tripped": _phrases(
        "tripped",
        "trip",
        "trip hai",
        "down",
        "neeche",
        "niche",
        "नीचे",
        "खाली",
        "khali",
        "gira",
        "gir gaya",
        "ट्रिप",
    ),
    "no_network": _phrases(
        "not showing",
        "not visible",
        "not there",
        "missing",
        "no wifi",
        "no network",
        "dikh nahi raha",
        "dikh hi nahi",
        "nahi dikh raha",
        "nahi dikh rahi",
        "dikhta nahi",
        "दिख नहीं",
        "दिख ही नहीं",
        "दिसत नाही",
        "दिसतच नाही",
        "disat nahi",
        "list mein nahi",
        "network nahi",
        "wifi nahi dikh",
        "isn't there",
        "not in the list",
    ),
    "stuck_connecting": _phrases(
        "connecting",
        "stuck",
        "atka",
        "atak",
        "अटका",
        "अटक",
        "adakla",
        "अडकलं",
        "अडकले",
        "अडकलंय",
        "obtaining ip",
        "connect ho raha",
        "connect ho rahi",
        "jud raha",
    ),
    "connected": _phrases(
        "connected",
        "कनेक्टेड",
        "connect ho gaya",
        "connect hai",
        "connect ho gayi",
        "jud gaya",
        "जुड़ गया",
        "जुडलं",
        "judla",
    ),
}
FLIP = {"yes": "no", "no": "yes", "on": "off", "off": "on", "up": "tripped", "tripped": "up"}


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    label: str


def _find(tokens: Sequence[str], phrases: Iterable[tuple[str, ...]], label: str) -> list[_Match]:
    out = []
    for phrase in phrases:
        n = len(phrase)
        if n == 0:
            continue
        for i in range(len(tokens) - n + 1):
            if tuple(tokens[i : i + n]) == phrase:
                out.append(_Match(i, i + n, label))
    return out


def _claim(matches: list[_Match], taken: list[bool]) -> list[_Match]:
    """Keep non-overlapping matches, longest first, marking the tokens they consume."""
    kept = []
    for m in sorted(matches, key=lambda m: (-(m.end - m.start), m.start)):
        if any(taken[m.start : m.end]):
            continue
        for i in range(m.start, m.end):
            taken[i] = True
        kept.append(m)
    return sorted(kept, key=lambda m: m.start)


class Extractor(Protocol):
    async def extract(self, text: str, outcomes: Sequence[str]) -> Extraction: ...


class RuleExtractor:
    """Deterministic, zero-latency extractor. Conservative: ambiguity yields ``unknown``."""

    async def extract(self, text: str, outcomes: Sequence[str]) -> Extraction:
        return self.extract_sync(text, outcomes)

    def extract_sync(self, text: str, outcomes: Sequence[str]) -> Extraction:
        tokens = tokenize(text)
        taken = [False] * len(tokens)
        meta = _claim(
            _find(tokens, INJECTION, "injection")
            + _find(tokens, STOP, "stop")
            + _find(tokens, UNSURE, "unsure")
            + _find(tokens, PROBABLE, "probable")
            + _find(tokens, HEARSAY, "hearsay")
            + _find(tokens, ASSUMPTION, "assumption")
            + ([] if "no_network" in outcomes else _find(tokens, NOT_OBSERVED, "not_observed")),
            taken,
        )
        labels = {m.label for m in meta}
        evidence = [" ".join(tokens[m.start : m.end]) for m in meta]

        allowed = set(outcomes)
        candidates = [m for o in outcomes for m in _find(tokens, OUTCOME_LEXICON.get(o, []), o)]
        matches = _claim(candidates, taken)

        found: set[str] = set()
        for m in matches:
            after = tokens[m.end] if m.end < len(tokens) and not taken[m.end] else ""
            before = tokens[m.start - 1] if m.start > 0 and not taken[m.start - 1] else ""
            negated = after in NEGATIONS or before in NEGATIONS
            label = m.label
            if negated and label not in ("no",):
                flipped = FLIP.get(label)
                if flipped is None or flipped not in allowed:
                    evidence.append("negated:" + " ".join(tokens[m.start : m.end]))
                    continue
                label = flipped
            found.add(label)
            evidence.append(f"{label}<-" + " ".join(tokens[m.start : m.end]))

        injection = "injection" in labels
        blocked = injection or "not_observed" in labels
        outcome = found.pop() if len(found) == 1 and not blocked else UNKNOWN_OUTCOME
        if "unsure" in labels:
            hedge = Hedge.UNSURE
        elif "probable" in labels:
            hedge = Hedge.PROBABLE
        else:
            hedge = Hedge.CERTAIN
        if "hearsay" in labels:
            directness = Directness.HEARSAY
        elif "assumption" in labels and outcome == UNKNOWN_OUTCOME:
            directness = Directness.ASSUMPTION
        else:
            directness = Directness.DIRECT
        return Extraction(
            outcome=outcome,
            hedge=hedge,
            directness=directness,
            injection_suspected=injection,
            wants_to_stop="stop" in labels,
            method="rules",
            evidence=evidence,
        )
