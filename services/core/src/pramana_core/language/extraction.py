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


ANSWER_NO = frozenset(tokenize("nahi nahin nai na नहीं नही ना नाही"))
"""Hindi and Marathi negate after the predicate ("band nahi hai" = "is not off"). The same word
opening an answer ("nahi band hai") is the reply "no", not a negation of the next word."""

_CLAUSE = re.compile(r"[.,!?;:।॥…]+")


def clause_breaks(text: str) -> set[int]:
    """Token indices that start a new clause (after a comma, full stop, danda...).

    "नहीं, बंद है" is "No. It is off": the negation answers the question and must not negate
    the next word. Tokens are the same as ``tokenize(text)``; only the breaks are added.
    """
    breaks: set[int] = set()
    n = 0
    for part in _CLAUSE.split(text):
        if n:
            breaks.add(n)
        n += len(tokenize(part))
    return breaks


def _phrases(*items: str) -> list[tuple[str, ...]]:
    return [tuple(tokenize(i)) for i in items]


NEGATIONS = frozenset(
    tokenize(
        "not no nahi nahin nai na nahī नहीं नही ना नाही नाहीत नको dont don't doesn't isn't "
        "aren't didn't cannot can't never nothing nobody none"
    )
)
"""English negative subjects ("nothing loads") negate the verb that follows them. A phrase that
is itself an outcome ("nothing" for "off") is claimed first, so it is never read twice."""

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
    # Role and authority claims, and attempts to steer the investigation's outcome.
    "system",
    "admin",
    "you are now",
    "act as",
    "pretend",
    "close the ticket",
    "close ticket",
    "ticket close",
    "mark investigation",
    "investigation resolved",
    # Hindi and Marathi: "instructions", "forget", "ignore"; Latin and Devanagari script.
    "सूचना",
    "सूचनांकडे",
    "विसरा",
    "विसरून",
    "दुर्लक्ष",
    "निर्देश",
    "निर्देशों",
    "भूल जाओ",
    "भूल जाइए",
    "bhool jao",
    "bhul jao",
    "suchna",
    "vishara",
    "visra",
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
    "stop",
    "i want to stop",
    "stop asking",
    "thambaycha",
    "thambaycha aahe",
    "थांबायचं",
    "थांबायचे",
    "थांबा",
    "vicharu naka",
    "विचारू नका",
    "bas karo",
    "बस करो",
    "mat pucho",
    "mat poocho",
    "mat puchho",
    "फ़ोन मत करो",
    "फोन मत करो",
    "phone mat karo",
    "call mat karo",
    "मत पूछो",
    "मत पूछिए",
    # "No time now": the negation is about the person's time, not the observation.
    "वेळ नाही",
    "vel nahi",
    "time nahi",
    "time nahin",
    "samay nahi",
    "समय नहीं",
    "waqt nahi",
    "वक़्त नहीं",
    "वक्त नहीं",
    "no time",
)
# Bare agreement and refusal words, used only by the polarity rule (see ``_polar``).
AFFIRM = frozenset(tokenize("yes yeah yep yup haan haa han haanji हाँ हां हा ho hoy होय हो ji"))
DENY = frozenset(tokenize("no nope nahi nahin nai नहीं नही na नाही"))
FILLER = frozenset(tokenize("re ji bhai yaar sir madam ok please"))
POLAR = {("off", "on"): "on"}
"""Probe outcome sets a yes/no question can be about, and the outcome "yes" means."""
UNSURE = _phrases(
    "not sure",
    "no idea",
    "pata nahi",
    "pata nahin",
    "maloom nahi",
    "malum nahi",
    "hard to tell",
    "नक्की नाही",
    "nakki nahi",
    "nahi maloom",
    "nahi malum",
    "मालूम नहीं",
    "नहीं मालूम",
    "मुझे नहीं मालूम",
    "पता नहीं",
    "माहीत नाही",
    "माहित नाही",
    "माहिती नाही",
    "मला माहीत नाही",
    "mahit nahi",
    "mahiti nahi",
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

DID_NOT_CHECK = _phrases(
    "check nahi kiya",
    "check nahin kiya",
    "check नहीं किया",
    "nahi dekha",
    "dekha nahi",
    "नहीं देखा",
    "देखा नहीं",
    "बघितलं नाही",
    "बघितले नाही",
    "baghitla nahi",
    "पाहिलं नाही",
    "पाहिले नाही",
    "didn't check",
    "did not check",
    "haven't checked",
    "have not checked",
    "not checked",
)
""""I didn't check (myself)" is a statement that no observation was made, for every probe,
including the Wi-Fi list. Its negation must not become "no" (a live recording, 2026-11-05)."""

SENTENCE_INITIAL_ONLY = frozenset(tokenize("ho हो"))
"""Marathi "ho" (yes) is also the Hindi verb "to be" ("karna ho to batana"). As yes it opens
the answer ("हो, चालू आहे"); anywhere else it is read as the verb, never as an answer."""

STALE = _phrases(
    "kal raat",
    "kal subah",
    "kal",
    "yesterday",
    "last night",
    "earlier today",
    "pehle tha",
    "pehle",
    "कल",
    "कल रात",
    "पहले",
    "काल",
    "काल रात्री",
    "abhi ka nahi pata",
    "abhi ka pata nahi",
)
"""A report about an earlier time is not an observation of now (the engine has no time model)."""

EARLIER_TODAY = _phrases("subah", "सुबह", "this morning", "in the morning", "sakali", "सकाळी")
SINCE = frozenset(tokenize("se since से पासून pasun"))
"""A time of day is stale ("subah green tha") unless it marks a start ("subah se band hai")."""


def _stale_time_of_day(tokens: Sequence[str]) -> list[_Match]:
    out = []
    for m in _find(tokens, EARLIER_TODAY, "stale"):
        after = tokens[m.end] if m.end < len(tokens) else ""
        before = tokens[m.start - 1] if m.start > 0 else ""
        if after not in SINCE and before not in SINCE:
            out.append(m)
    return out


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
    "बहुतेक",
    "bahutek",
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
    "कह रहा",
    "कह रही",
    "kah raha",
    "kah rahi",
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
    # Marathi: "mitra mhanala ..." (my friend said ...), "aikla" (I heard).
    "म्हणाला",
    "म्हणाली",
    "म्हणाले",
    "म्हणतो",
    "म्हणते",
    "म्हणत होता",
    "सांगत होता",
    "ऐकलं",
    "ऐकले",
    "mhanala",
    "mhanali",
    "mhanto",
    "aikla",
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
        "opened",
        "opened fine",
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
        "network gayab",
        "network गायब",
        "network ही गायब",
        "network hi gayab",
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
        "नहीं चल रहा",
        "नहीं चल रही",
        "चल नहीं रहा",
        "चल नहीं रही",
        "नहीं खुल रहा",
        "नहीं खुल रही",
        "खुल नहीं रहा",
        "खुल नहीं रही",
        "band",
        "band hai",
        "बंद",
        "बंद है",
        "बंद हैं",
        "is down",
        "down",
        "gone",
        "is gone",
        "gaya",
        "chala gaya",
        "chali gayi",
        "nothing opens",
        "never load",
        "never loads",
        "keep spinning",
        "keeps spinning",
        "times out",
        "timed out",
        "timeout",
    ),
    "on": _phrases(
        "on",
        "chal rahi",
        "chal raha",
        "chal rahe",
        "चल रही",
        "चल रहा",
        "चल रहे",
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
        "video aa raha",
        "video aa rahi",
        "picture aa rahi",
        "लागलेत",
        "लागले आहेत",
        "laglet",
        "charging",
        "is charging",
        "it's charging",
        "charge ho raha",
        "charge hone laga",
        "charging shuru",
        "चार्ज होने लगा",
        "चार्ज हो रहा",
        "चार्ज होतोय",
        "चार्ज होत आहे",
        "light aa gayi",
        "light aayi",
        "जल गया",
        "jal gaya",
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
        "blank",
        "काळी",
        "काळा",
        "kaali",
        "काहीच दिसत नाही",
        "काहीच दिसत नाहीये",
        "nothing on it",
        "nothing on the screen",
        "not charging",
        "isn't charging",
        "is not charging",
        "charge nahi",
        "charge nahi ho raha",
        "चार्ज नहीं",
        "चार्ज नहीं हो रहा",
        "चार्ज होत नाही",
        "चार्ज होत नाहीये",
        "नहीं जला",
        "जला नहीं",
        "nahi jala",
        "jala nahi",
    ),
    "green": _phrases("green", "hara", "hari", "हरा", "हरी", "हिरवा", "हिरवे", "hirva", "hirve"),
    "amber": _phrases(
        "amber",
        "orange",
        "narangi",
        "नारंगी",
        "नारिंगी",
        "naringi",
        "yellow",
        "peela",
        "peeli",
        "पीला",
        "pivla",
        "पिवळा",
    ),
    "red": _phrases("red", "laal", "lal", "लाल"),
    "up": _phrases(
        "up", "upar", "ऊपर", "upper side", "on position", "वर आहे", "var aahe", "वरच", "varach"
    ),
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
        "देख ही नहीं",
        "dekh hi nahi",
        "not showing",
        "isn't showing",
        "isn't even showing",
        "not even showing",
        "aa hi nahi raha",
        "aa nahi raha",
        "nahi aa raha",
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
        "network gayab",
        "network गायब",
        "network ही गायब",
        "network hi gayab",
        "wifi nahi dikh",
        "isn't there",
        "not in the list",
        "isn't in the list",
        "is not in the list",
    ),
    "stuck_connecting": _phrases(
        "कनेक्ट होतंय",
        "connect hotay",
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
        "connect hi nahi ho raha",
        "connect nahi ho raha",
        "ip le raha",
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
        "कनेक्ट झालं",
        "कनेक्ट झालंय",
        "कनेक्ट झाले",
        "connect zala",
        "connect jhala",
    ),
}
FLIP = {"yes": "no", "no": "yes", "on": "off", "off": "on", "up": "tripped", "tripped": "up"}


def _polar(question: str | None, outcomes: Sequence[str]) -> str | None:
    """The outcome a bare "yes" affirms, if the question was a yes/no question about it.

    Rule: "Does the ceiling light come on?" names one outcome, so it is a yes/no question
    about it: "yes" means on and "no" means off. "Is the screen on or off?" names both, so a
    bare "yes" does not say which and stays ``unknown``. Without the question text there is
    no polarity. (A word test for "or" cannot work: Hindi "की" is both "or" in Marathi and the
    possessive "of" in "छत की लाइट".)
    """
    key = tuple(sorted(outcomes))
    if question is None or key not in POLAR:
        return None
    q = tokenize(question)
    named = {o for o in outcomes if _find(q, OUTCOME_LEXICON.get(o, []), o)}
    return POLAR[key] if len(named) <= 1 else None


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
    async def extract(
        self, text: str, outcomes: Sequence[str], *, question: str | None = None
    ) -> Extraction: ...


class RuleExtractor:
    """Deterministic, zero-latency extractor. Conservative: ambiguity yields ``unknown``."""

    async def extract(
        self, text: str, outcomes: Sequence[str], *, question: str | None = None
    ) -> Extraction:
        return self.extract_sync(text, outcomes, question=question)

    def extract_sync(
        self, text: str, outcomes: Sequence[str], *, question: str | None = None
    ) -> Extraction:
        tokens = tokenize(text)
        taken = [False] * len(tokens)
        meta = _claim(
            _find(tokens, INJECTION, "injection")
            + _find(tokens, STOP, "stop")
            + _find(tokens, UNSURE, "unsure")
            + _find(tokens, PROBABLE, "probable")
            + _find(tokens, HEARSAY, "hearsay")
            + _find(tokens, ASSUMPTION, "assumption")
            + ([] if "no_network" in outcomes else _find(tokens, NOT_OBSERVED, "not_observed"))
            + _find(tokens, DID_NOT_CHECK, "not_observed")
            + _find(tokens, STALE, "stale")
            + _stale_time_of_day(tokens),
            taken,
        )
        labels = {m.label for m in meta}
        evidence = [f"{m.label}:" + " ".join(tokens[m.start : m.end]) for m in meta]

        allowed = set(outcomes)
        candidates = [m for o in outcomes for m in _find(tokens, OUTCOME_LEXICON.get(o, []), o)]
        # "Opens the answer": the first word not already read as a hedge, a report or a
        # filler ("kadachit ho, chalu aahe"), or the start of a new clause.
        first = next((i for i, t in enumerate(tokens) if not taken[i] and t not in FILLER), 0)
        starts = clause_breaks(text) | {first}
        candidates = [
            m
            for m in candidates
            if not (m.end - m.start == 1 and tokens[m.start] in SENTENCE_INITIAL_ONLY)
            or m.start in starts
        ]
        matches = _claim(candidates, taken)

        found: set[str] = set()
        breaks = clause_breaks(text)
        for m in matches:
            if (
                m.end in breaks
                and m.end < len(tokens)
                and tokens[m.end] in NEGATIONS
                and any(o.start > m.end for o in matches)
            ):
                # A self-correction: "red, no wait, it's green". The later answer stands.
                evidence.append("corrected:" + " ".join(tokens[m.start : m.end]))
                continue
            # A negation applies within its clause only ("nahi, band hai" is "no: it is off").
            after = (
                tokens[m.end]
                if m.end < len(tokens) and not taken[m.end] and m.end not in breaks
                else ""
            )
            before = (
                tokens[m.start - 1]
                if m.start > 0
                and not taken[m.start - 1]
                and m.start not in breaks
                and not (m.start == 1 and tokens[0] in ANSWER_NO)
                else ""
            )
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

        polar = _polar(question, outcomes)
        if not found and polar is not None:
            free = [t for t, used in zip(tokens, taken, strict=True) if not used]
            said = {t for t in free if t not in FILLER}
            if said and said <= AFFIRM:
                found.add(polar)
                evidence.append(f"{polar}<-polar yes")
            elif said and said <= DENY:
                found.add(FLIP[polar])
                evidence.append(f"{FLIP[polar]}<-polar no")

        injection = "injection" in labels
        blocked = injection or "not_observed" in labels or "stale" in labels
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
