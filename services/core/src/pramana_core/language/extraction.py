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
    "नियम छोड़ो",
    "नियम छोड़ दो",
    "नियम सोड",
    "नियम सोडा",
    "नियम बाजूला ठेव",
    "नियम बाजूला ठेवा",
    "rules chhodo",
    "rules chhod do",
    "rules side me rakho",
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
    "मुझे नहीं पता",
    "mujhe nahi pata",
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
    "can't make out",
    "cannot make out",
    "couldn't make out",
    "can't read",
    "cannot read",
    "couldn't read",
    "can't find",
    "cannot find",
    "couldn't find",
    "could not find",
    "mil nahi raha",
    "mil nahi rahi",
    "mil hi nahi raha",
    "mil hi nahi rahi",
    "mera phone abhi mere paas nahi hai",
    "mera फोन अभी मेरे पास नहीं है",
    "मेरा फोन अभी मेरे पास नहीं है",
    "मेरा फ़ोन अभी मेरे पास नहीं है",
    "my phone is not with me",
    "my phone isn't with me",
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
    "check nahi ki",
    "check nahin ki",
    "website check nahi ki",
    "website check nahin ki",
    "website test nahi ki",
    "website test nahin ki",
    "have not tested",
    "haven't tested",
    "did not test",
    "didn't test",
    "haven't looked at mine",
    "have not looked at mine",
    "didn't look at mine",
    "did not look at mine",
    "haven't checked mine",
    "have not checked mine",
    "didn't check mine",
    "did not check mine",
    "haven't checked my phone",
    "have not checked my phone",
)
""""I didn't check (myself)" is a statement that no observation was made, for every probe,
including the Wi-Fi list. Its negation must not become "no" (a live recording, 2026-11-05)."""

SENTENCE_INITIAL_ONLY = frozenset(tokenize("ho हो"))

PHONE_TALK = _phrases(
    "haan haan bolo",
    "haan bolo",
    "haan ji bolo",
    "haan boliye",
    "haan ji boliye",
    "हाँ हाँ बोलो",
    "हाँ बोलो",
    "हाँ बोलिए",
    "हाँ जी बोलिए",
    "हां बोलो",
    "हां बोलिए",
    "हो बोला",
    "हो सांगा",
    "ho bola",
    "haan hello",
    "हाँ hello",
    "हाँ हेलो",
    "हां hello",
    "hello hello",
    "hello",
    "हेलो",
    "हॅलो",
    "sunai de raha hai",
    "sunai de rahi hai",
    "awaaz aa rahi hai",
    "आवाज़ आ रही है",
    "आवाज आ रही है",
)
"""Picking up a call and checking the line ("haan bolo" is "yes, go on"): not an answer."""

PRESENCE_TALK = _phrases(
    "यहीं हूँ",
    "यहीं हूं",
    "यहाँ हूँ",
    "यहां हूं",
    "yahin hoon",
    "yahin hu",
    "yahan hoon",
    "yahan hu",
    "i am here",
    "i'm here",
    "im here",
    "इथेच आहे",
    "इथे आहे",
    "ithech aahe",
)
"""Saying where one is. A bare "haan" next to it answers "are you there?", not the question."""

OBJECTS: dict[str, list[tuple[str, ...]]] = {
    "phone": _phrases(
        "wifi",
        "wi fi",
        "वाई फ़ाई",
        "वाई फाई",
        "वाय फाय",
        "internet",
        "इंटरनेट",
        "website",
        "वेबसाइट",
        "वेबसाइट",
        "page",
        "पेज",
        "पान",
        "net",
    ),
    "corridor": _phrases("corridor", "कॉरिडोर", "कॉरिडॉर", "gallery", "गैलरी"),
    "screen": _phrases("screen", "स्क्रीन", "recorder", "रिकॉर्डर", "रेकॉर्डर", "cctv", "सीसीटीवी"),
    "socket": _phrases("socket", "सॉकेट", "charger", "चार्जर", "charging", "plug"),
    "router": _phrases("router", "राउटर", "gateway", "गेटवे"),
    "fibre": _phrases("fibre", "fiber", "फ़ाइबर", "फायबर", "ont", "pon"),
    "breaker": _phrases("breaker", "ब्रेकर", "mcb"),
    "box": _phrases("box", "डिब्बा", "डबा"),
    "ceiling": _phrases("ceiling", "chhat", "छत", "छताचा", "छताला"),
}
"""Things a question can be about. An answer clause that names only other things is about
something else ("corridor ki lights on hain" does not answer "is the CCTV screen on?")."""
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
ASSUMPTION_CONNECTORS = frozenset(
    tokenize("so therefore hence because isliye तभी तो toh म्हणून mhanun")
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
        "charge hone lagta",
        "charging shuru",
        "चार्ज होने लगा",
        "चार्ज होने लगता",
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
        "charge icon did not appear",
        "charging icon did not appear",
        "charging symbol did not appear",
        "charge icon didn't appear",
        "charging icon didn't appear",
        "charging ka nishaan nahi aaya",
        "charging ka nishan nahi aaya",
        "charge ka nishaan nahi aaya",
        "charge ka icon nahi aaya",
        "चार्जिंग का निशान नहीं आया",
        "चार्जिंग का चिन्ह नहीं आया",
        "चार्जिंगचं चिन्ह नाही आलं",
        "चार्जिंग चिन्ह आलं नाही",
        "not charging",
        "isn't charging",
        "is not charging",
        "charge nahi",
        "charge nahi ho raha",
        "चार्ज नहीं",
        "चार्ज नहीं हो रहा",
        "चार्ज नहीं होता",
        "charge nahi hota",
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
    return POLAR[key] if len(named_outcomes(question, outcomes)) <= 1 else None


def named_outcomes(question: str, outcomes: Sequence[str]) -> set[str]:
    """The outcomes a question names as possible answers ("on or off?" names both)."""
    q = tokenize(question)
    return {o for o in outcomes if _find(q, OUTCOME_LEXICON.get(o, []), o)}


def _groups(tokens: Sequence[str]) -> set[str]:
    """Things named in ``tokens``. One-word names also match the start of a word, since Hindi
    and Marathi attach endings to it ("कॉरिडॉरमध्ये" is "in the corridor")."""
    out = set()
    for g, phrases in OBJECTS.items():
        if _find(tokens, phrases, g) or any(
            len(p) == 1 and len(p[0]) >= 3 and t.startswith(p[0]) and not p[0].isascii()
            for p in phrases
            for t in tokens
        ):
            out.add(g)
    return out


def _bare_polar(tokens: Sequence[str], m: _Match) -> bool:
    """A one-word yes or no ("haan", "हो", "nahi"), as opposed to "khul raha hai"."""
    return m.end - m.start == 1 and m.label in ("yes", "no")


def _about_the_question(
    text: str, tokens: Sequence[str], matches: list[_Match], question: str
) -> tuple[list[_Match], list[str]]:
    """Drop answers given in a clause that names only things the question is not about.

    What the question is about is read from the question itself (the CCTV screen, the corridor,
    the wall socket), so this works in every language without a table per probe. A clause that
    names nothing is kept: "band hai" answers whatever was asked.
    """
    asked = _groups(tokenize(question))
    if not asked:
        return matches, []
    starts = sorted(clause_breaks(text) | {0})
    kept, dropped = [], []
    for m in matches:
        lo = max(b for b in starts if b <= m.start)
        hi = min((b for b in starts if b > m.start), default=len(tokens))
        named = _groups(tokens[lo:hi])
        if named and not named & asked:
            dropped.append(f"other_object:{','.join(sorted(named))}")
        else:
            kept.append(m)
    return kept, dropped


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


_INDICATOR_NOUNS = frozenset(
    tokenize(
        "light lights lamp lamps indicator indicators led leds bulb bulbs "
        "लाइट लाइटें लाइट्स बत्ती बत्तियां बत्तियाँ इंडिकेटर इंडिकेटर्स बल्ब "
        "दिवा दिवे दिव्याचा दिव्याची दिव्याचे दिव्याचं दिव्याला दिव्यावरचा "
        "दिव्यावरची दिव्यावरचे रोशनी दीप"
    )
)
_INDICATOR_STEMS = ("दिव", "बत्त", "लाइट", "इंडिकेटर", "बल्ब", "दीप")
_OTHER_INDICATOR_CUES = frozenset(
    tokenize(
        "other another neighboring neighbour adjacent beside separate different "
        "दूसरी दूसरा दूसरे दुसरी दुसरा दुसरे वेगळा वेगळी वेगळे शेजारचा शेजारची"
    )
)
_INDICATOR_REFERENCE_RELATIONS = frozenset(
    tokenize(
        "above below over under beside besides near nearby next between behind infront "
        "front outside inside across around away from दूर पास ऊपर नीचे बगल बाजूला जवळ "
        "मध्ये मागे समोर पुढे केपास केबगल upar neeche paas bagal samne piche aage "
        "my your his her their our mera meri mere maza mazi maze माझा माझी माझे माझ्या "
        "मेरा मेरी मेरे bahar baher बाहर बाहेर बाहेरचा बाहेरची बाहेरचे"
    )
)
_NON_INDICATOR_LABEL_NOUNS = frozenset(
    tokenize(
        "label labels sticker stickers tag tags marking markings inscription writing "
        "लेबल स्टिकर टैग नाम लिखा लिखी लिखे लेबल्स नाव लिहिले लिहिली लिहिलेले टॅग"
    )
)
_INDICATOR_LABEL_STOP = (
    frozenset(
        tokenize(
            "the a an of in at on to for from is are was were be been being its it this that "
            "all every each both entire whole "
            "my your his her their our and or but while whereas as if then there here "
            "marked labelled labeled called named written says "
            "की का के को चा ची चे चं च्या मध्ये और या तथा क्या कौन कहाँ सब सभी सारी सारे हर प्रत्येक "
            "some any कोई कोईसा कोईसी koi "
            "i think probably maybe perhaps shayad "
            "सगळे सगळ्या सगळी सर्व दोन्ही "
            "आणि किंवा है हैं था थी थे में पर वाला वाली वाले "
            "लिखा लिखी लिखे असं असा अशी आहे आहेत aur ya lekin hai hain ho gaya wali wale wala "
            "sab sabhi saari saare har "
            "small smaller smallest little tiny big large pitch solid steady stable "
            "छोटा छोटी छोटे लहान लहानसा लहानशी लहानसे वरचा वरची वरचे छतावरच्या डब्यावरचा "
            "पोर्टचे पोर्टचा पोर्टची "
            "छोटा छोटा सा छोटी छोटी सी छोटे छोटे से "
            "छोटा सा छोटी सी उस उसे उसका उसकी इसके इससे यह वहां वहाँ "
            "दिसतोय दिसतायत दिसतात दिसतो दिसते दिसताय "
        )
    )
    | {"one"}
    | NEGATIONS
    | FILLER
    | frozenset(word for phrase in (*PROBABLE, *UNSURE, *ASSUMPTION) for word in phrase)
)
_INDICATOR_LABEL_BREAKS = frozenset(
    tokenize("and or but while whereas aur lekin और तथा लेकिन परंतु आणि पण")
)
_INDICATOR_REFERENCE_MARKERS = frozenset(tokenize("wali wala wale वाली वाला वाले वालीं"))
_INDICATOR_WORDS = frozenset(
    token for token in _INDICATOR_NOUNS if token not in _INDICATOR_LABEL_STOP
)
_INDICATOR_STATE_OUTCOMES = frozenset({"green", "red", "amber", "off", "on", "up", "tripped"})
_INDICATOR_STATE_WORDS = frozenset(
    word
    for outcome in _INDICATOR_STATE_OUTCOMES
    for phrase in OUTCOME_LEXICON.get(outcome, [])
    for word in phrase
)
_LABEL_CONTEXT_SKIP = (
    _INDICATOR_LABEL_STOP | _INDICATOR_STATE_WORDS | _INDICATOR_WORDS | _NON_INDICATOR_LABEL_NOUNS
)
_EXPLICIT_LABEL = re.compile(r"(?:[A-Z]{2,}|[A-Z0-9]*\d+[A-Z0-9]*)\Z")
_CONTEXT_TARGET_GROUPS = frozenset({"corridor", "screen"})


@dataclass(frozen=True)
class _IndicatorReference:
    position: int
    labels: frozenset[str]
    marked_other: bool = False
    non_indicator: bool = False


def _is_indicator_noun(token: str) -> bool:
    return token in _INDICATOR_NOUNS or token.startswith(_INDICATOR_STEMS)


def _raw_tokens(text: str) -> list[str]:
    """Keep original casing so uppercase and alphanumeric labels stay detectable."""
    return _PUNCT.sub(" ", text).split()


def _clause_bounds(index: int, tokens: Sequence[str], breaks: set[int]) -> tuple[int, int]:
    start = max((boundary for boundary in breaks if boundary <= index), default=0)
    end = min((boundary for boundary in breaks if boundary > index), default=len(tokens))
    return start, end


def _context_label_group(tokens: Sequence[str], index: int, start: int, end: int) -> frozenset[str]:
    """Read a nearby noun phrase as an arbitrary label, stopping at clause conjunctions."""
    labels: set[str] = set()
    for indices in (
        reversed(range(max(start, index - 5), index)),
        range(index + 1, min(end, index + 6)),
    ):
        for current in indices:
            token = tokens[current]
            if (
                token in _INDICATOR_LABEL_BREAKS | _INDICATOR_REFERENCE_RELATIONS
                or _is_indicator_noun(token)
            ):
                break
            if current > index and any(
                _is_indicator_noun(tokens[following])
                for following in range(current + 1, min(end, current + 4))
            ):
                break
            if token not in _LABEL_CONTEXT_SKIP:
                labels.add(token)
    return frozenset(labels)


def _indicator_label_group(
    tokens: Sequence[str], raw: Sequence[str], index: int, start: int, end: int
) -> frozenset[str]:
    candidate_ids = [
        (abs(current - index), current, tokens[current])
        for current in range(max(start, index - 5), min(end, index + 6))
        if current != index
        and abs(current - index) <= 3
        and _EXPLICIT_LABEL.fullmatch(raw[current])
        and tokens[current] not in _INDICATOR_STATE_WORDS
        and not _is_indicator_noun(tokens[current])
        and not any(
            tokens[between] in _INDICATOR_REFERENCE_RELATIONS
            for between in range(min(index, current) + 1, max(index, current))
        )
    ]
    nearby_ids = []
    for distance, current, label in candidate_ids:
        if current > index and any(
            _is_indicator_noun(tokens[following])
            for following in range(current + 1, min(end, current + 4))
        ):
            continue
        nearby_ids.append((distance, label))
    if nearby_ids:
        distance = min(item[0] for item in nearby_ids)
        return frozenset(
            label for label_distance, label in nearby_ids if label_distance == distance
        )
    if candidate_ids:
        # An identifier immediately followed by another indicator belongs to that later
        # indicator. Do not let a broad context window attach it to the preceding one too.
        return frozenset()
    return _context_label_group(tokens, index, start, end)


def _descriptive_label_group(
    tokens: Sequence[str], index: int, start: int, end: int
) -> frozenset[str]:
    return frozenset(
        token
        for current in range(max(start, index - 5), min(end, index + 6))
        if current != index
        for token in (tokens[current],)
        if token not in _LABEL_CONTEXT_SKIP and not _is_indicator_noun(token)
    )


def _question_indicator_label_groups(question: str) -> list[frozenset[str]]:
    tokens = tokenize(question)
    raw = _raw_tokens(question)
    breaks = clause_breaks(question)
    groups = []
    for index, token in enumerate(tokens):
        if not _is_indicator_noun(token):
            continue
        start, end = _clause_bounds(index, tokens, breaks)
        labels = _indicator_label_group(tokens, raw, index, start, end)
        if labels:
            groups.append(labels)
    if groups:
        # Main's object groups already carry cross-language aliases for these shared contexts.
        # Expand only non-code context labels so a Hindi question about corridor lights matches
        # a Hinglish answer that names the corridor, without equating arbitrary device labels.
        expanded = list(groups)
        for group in groups:
            explicit = any(
                _EXPLICIT_LABEL.fullmatch(original)
                for token, original in zip(tokens, raw, strict=True)
                if token in group
            )
            if explicit:
                continue
            for context in _groups(list(group)) & _CONTEXT_TARGET_GROUPS:
                expanded.extend(frozenset(alias) for alias in OBJECTS[context])
        return list(dict.fromkeys(expanded))
    # A visual description can name the target without repeating "light", as in
    # "the blue one on the left". Keep the complete descriptor so siblings stay distinct.
    for index, token in enumerate(tokens):
        if token != "one":
            continue
        start, end = _clause_bounds(index, tokens, breaks)
        labels = _descriptive_label_group(tokens, index, start, end)
        if labels:
            groups.append(labels)
    if groups:
        return groups
    # Some probes name an indicator label directly without saying "light" or "indicator".
    raw = _raw_tokens(question)
    explicit_labels = {
        token
        for token, original in zip(tokens, raw, strict=True)
        if _EXPLICIT_LABEL.fullmatch(original)
        and token not in _INDICATOR_STATE_WORDS
        and not _is_indicator_noun(token)
    }
    return [frozenset({label}) for label in explicit_labels]


def _same_target_reference(labels: frozenset[str], targets: Sequence[frozenset[str]]) -> bool:
    return bool(labels) and any(target and target.issubset(labels) for target in targets)


def _indicator_references(
    text: str, tokens: Sequence[str], breaks: set[int]
) -> list[_IndicatorReference]:
    raw = _raw_tokens(text)
    cue_references: list[_IndicatorReference] = []
    cue_windows: list[tuple[int, int, frozenset[str]]] = []
    for index, token in enumerate(tokens):
        if _is_indicator_noun(token):
            start, end = _clause_bounds(index, tokens, breaks)
            labels = _indicator_label_group(tokens, raw, index, start, end)
            cue_windows.append((max(start, index - 5), min(end, index + 6), labels))
            marked_other = bool(labels & _OTHER_INDICATOR_CUES)
            cue_references.append(_IndicatorReference(index, labels, marked_other))
        elif token in _INDICATOR_REFERENCE_MARKERS:
            start, end = _clause_bounds(index, tokens, breaks)
            labels = _context_label_group(tokens, index, start, end)
            if labels:
                cue_windows.append((max(start, index - 5), min(end, index + 6), labels))
                non_indicator = any(
                    tokens[current] in _NON_INDICATOR_LABEL_NOUNS
                    for current in range(max(start, index - 3), min(end, index + 4))
                )
                cue_references.append(
                    _IndicatorReference(index, labels, non_indicator=non_indicator)
                )
    references: list[_IndicatorReference] = []
    for reference in sorted(cue_references, key=lambda item: item.position):
        if references:
            previous = references[-1]
            between = tokens[previous.position + 1 : reference.position]
            is_same_phrase = (
                _clause_bounds(previous.position, tokens, breaks)
                == _clause_bounds(reference.position, tokens, breaks)
                and reference.position - previous.position <= 3
                and previous.labels == reference.labels
                and previous.marked_other == reference.marked_other
                and not any(token in _INDICATOR_LABEL_BREAKS for token in between)
                and all(
                    token in _INDICATOR_LABEL_STOP
                    or token in reference.labels
                    or _is_indicator_noun(token)
                    for token in between
                )
            )
            if is_same_phrase:
                continue
        references.append(reference)
    for index, (token, original) in enumerate(zip(tokens, raw, strict=True)):
        if not _EXPLICIT_LABEL.fullmatch(original) or _is_indicator_noun(token):
            continue
        if any(start <= index < end and token in labels for start, end, labels in cue_windows):
            continue
        start, end = _clause_bounds(index, tokens, breaks)
        non_indicator = any(
            tokens[current] in _NON_INDICATOR_LABEL_NOUNS
            for current in range(max(start, index - 2), min(end, index + 3))
        )
        references.append(
            _IndicatorReference(index, frozenset({token}), non_indicator=non_indicator)
        )
    references.extend(
        _IndicatorReference(index, frozenset(), non_indicator=True)
        for index, token in enumerate(tokens)
        if token in _NON_INDICATOR_LABEL_NOUNS
    )
    # Also recognize descriptions such as "blue one on the left" if the answer omits "light".
    if not any(_is_indicator_noun(token) for token in tokens):
        for index, token in enumerate(tokens):
            if token != "one":
                continue
            start, end = _clause_bounds(index, tokens, breaks)
            labels = _descriptive_label_group(tokens, index, start, end)
            if labels:
                references.append(_IndicatorReference(index, labels))
    return references


def _reference_kind(reference: _IndicatorReference, targets: Sequence[frozenset[str]]) -> str:
    if reference.non_indicator:
        return "other"
    if _same_target_reference(reference.labels, targets):
        return "target"
    if reference.marked_other or reference.labels:
        return "other"
    return "generic"


def _candidate_reference(
    match: _Match,
    references: Sequence[_IndicatorReference],
    targets: Sequence[frozenset[str]],
    tokens: Sequence[str],
    breaks: set[int],
) -> str:
    clause = _clause_bounds(match.start, tokens, breaks)
    local = [
        reference
        for reference in references
        if _clause_bounds(reference.position, tokens, breaks) == clause
    ]
    nearby: list[tuple[int, str]] = []
    reference_labels = {label for reference in local for label in reference.labels} | {
        label for target in targets for label in target
    }

    def add_reference_options(index: int, distance: int) -> bool:
        associated = [
            reference
            for reference in local
            if reference.position == index
            or (tokens[index] in reference.labels and abs(reference.position - index) <= 5)
        ]
        if not associated:
            return False
        nearby.extend((distance, _reference_kind(reference, targets)) for reference in associated)
        return True

    # Bind each state to its nearest nearby referent. Any content word beside a state can be an
    # object, even when it is not in a hand-maintained noun list. This prevents a target named in
    # another clause from donating its identity to the color.
    for indices in (
        range(match.start - 1, max(clause[0] - 1, match.start - 6), -1),
        range(match.end, min(clause[1], match.end + 5)),
    ):
        for index in indices:
            distance = min(abs(index - match.start), abs(index - (match.end - 1)))
            if add_reference_options(index, distance):
                break
            token = tokens[index]
            if token in _REFERENT_CONTEXT_SKIP or _is_indicator_noun(token):
                continue
            if token in reference_labels:
                continue
            nearby.append((distance, "other"))
            break

    if nearby:
        nearest = min(distance for distance, _ in nearby)
        kinds = {kind for distance, kind in nearby if distance == nearest}
        if kinds == {"target"}:
            return "target"
        if kinds == {"other"}:
            return "other"
        if kinds == {"generic"} and len(references) == 1:
            return "target"
        return "ambiguous"
    if not references:
        return "target"
    kinds = {_reference_kind(reference, targets) for reference in references}
    if kinds == {"target"}:
        return "target"
    if kinds == {"generic"} and len(references) == 1:
        return "target"
    return "ambiguous"


def _filter_other_indicators(
    candidates: list[_Match],
    tokens: Sequence[str],
    question: str,
    text: str,
    breaks: set[int],
) -> tuple[list[_Match], dict[_Match, str], bool, list[str]]:
    """Attribute each state to a proven referent; leave unbound states unknown."""
    targets = _question_indicator_label_groups(question)
    references = _indicator_references(text, tokens, breaks)
    kept: list[_Match] = []
    bindings: dict[_Match, str] = {}
    ambiguous = False
    evidence: list[str] = []
    for match in candidates:
        binding = _candidate_reference(match, references, targets, tokens, breaks)
        if binding == "target":
            kept.append(match)
            bindings[match] = "target"
        elif binding == "ambiguous":
            ambiguous = True
            evidence.append("unbound:" + " ".join(tokens[match.start : match.end]))
        else:
            evidence.append("other_indicator:" + " ".join(tokens[match.start : match.end]))
    return kept, bindings, ambiguous, evidence


def _is_indicator_question(question: str, outcomes: Sequence[str]) -> bool:
    tokens = tokenize(question)
    if any(_is_indicator_noun(token) for token in tokens):
        return True
    if any(token in _INDICATOR_REFERENCE_MARKERS or token == "one" for token in tokens):
        return True
    return bool(set(outcomes) & {"green", "red", "amber"})


_CORRECTION_CUES = frozenset(tokenize("actually wait sorry rather matlab meant म्हणजे असल वास्तव"))
_CORRECTION_NEGATIONS = frozenset(tokenize("no nahi nahin नहीं नही नाही"))
_NON_CORRECTION_AFTER_NEGATION = frozenset(tokenize("other another else बाकी दूसरे दूसरी दुसरा"))
_REFERENT_CONTEXT_SKIP = frozenset(
    _INDICATOR_LABEL_STOP
    | _INDICATOR_STATE_WORDS
    | _INDICATOR_REFERENCE_RELATIONS
    | _OTHER_INDICATOR_CUES
    | _CORRECTION_CUES
    | _CORRECTION_NEGATIONS
    | _NON_CORRECTION_AFTER_NEGATION
    | NEGATIONS
    | AFFIRM
    | DENY
    | frozenset(
        tokenize(
            "i me myself you he she it we they them him her us this that these those there here "
            "now today yes yeah no nope please well very really just also too only "
            "looks look appear appears seemed seems seem feel feels felt sounds sound "
            "show shows showing marked called labelled labeled written say says "
            "broken faulty damaged bad dim faded faint weak bright blinking flashing "
            "pitch solid steady stable small smaller smallest little tiny big large "
            "si see probably maybe perhaps shayad maybe perhaps "
            "orange lag lagta lagti lagti लग लगता लगती लगते लग "
            "distoay distoy disat diste दिसतोय दिसतायत दिसतात दिसतो दिसते दिसताय "
            "lagto lagte lagla laglay lagta lagti लागतो लागते लागला लागलाय लागले "
            "व्यवस्थित "
            "chhota chhoti chhote chhoti si chhota sa "
            "छोटा छोटी छोटे लहान वरचा वरची वरचे छतावरच्या डब्यावरचा पोर्टचे पोर्टचा पोर्टची "
            "bahar baher बाहर बाहेर बाहेरचा बाहेरची बाहेरचे "
            "koi कोई some any theyre "
            "meri mera mere maza mazi maze माझा माझी माझे माझ्या मेरा मेरी मेरे "
            "खराब खराबी टूटा टूटी हुआ हुई दिसता दिसते दिसतो दिसली दिसला दिसले "
            "वाटतो वाटते होता होती होते आहे आहेत असतो असते असतात "
        )
    )
    | FILLER
    | frozenset(word for phrase in (*PROBABLE, *UNSURE, *ASSUMPTION) for word in phrase)
)


def _correction_cue_indices(tokens: Sequence[str], breaks: set[int]) -> list[int]:
    cues = []
    for index, token in enumerate(tokens):
        if token in _CORRECTION_CUES or tokens[index : index + 2] == ["i", "mean"]:
            cues.append(index)
            continue
        clause_start = max((boundary for boundary in breaks if boundary <= index), default=0)
        if (
            token in _CORRECTION_NEGATIONS
            and index == clause_start
            and index + 1 < len(tokens)
            and tokens[index + 1] not in _NON_CORRECTION_AFTER_NEGATION
        ):
            cues.append(index)
    return cues


def _remove_self_corrected(
    candidates: list[_Match],
    tokens: Sequence[str],
    breaks: set[int],
    all_candidates: Sequence[_Match],
    bindings: dict[_Match, str],
) -> tuple[list[_Match], list[_Match]]:
    """Remove a prior value only when the correction resolves to the same referent."""
    ordered = sorted(candidates, key=lambda match: (match.start, match.end))
    cues = _correction_cue_indices(tokens, breaks)

    def corrects(earlier: _Match, later: _Match) -> bool:
        if bindings.get(earlier) != bindings.get(later) or bindings.get(later) != "target":
            return False
        if later.start < earlier.end or later.start - earlier.end > 16:
            return False
        for cue in cues:
            if not earlier.end <= cue <= later.start:
                continue
            next_values = [match for match in all_candidates if cue <= match.start <= later.start]
            if next_values and min(next_values, key=lambda match: match.start).start == later.start:
                return True
        return False

    corrected = [
        earlier for earlier in ordered if any(corrects(earlier, later) for later in ordered)
    ]
    corrected_set = set(corrected)
    return [match for match in candidates if match not in corrected_set], corrected


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
        candidates = [m for o in outcomes for m in _find(tokens, OUTCOME_LEXICON.get(o, []), o)]
        # "lagta hai" is "it seems" unless it ends an answer phrase that started earlier:
        # "charge hone lagta hai" is "it starts charging", not a hedge.
        probable = [
            h
            for h in _find(tokens, PROBABLE, "probable")
            if not any(c.start < h.start < c.end for c in candidates)
        ]
        meta = _claim(
            _find(tokens, INJECTION, "injection")
            + _find(tokens, STOP, "stop")
            + _find(tokens, PHONE_TALK, "phone_talk")
            + _find(tokens, PRESENCE_TALK, "presence_talk")
            + _find(tokens, UNSURE, "unsure")
            + probable
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
        # "Opens the answer": the first word not already read as a hedge, a report or a
        # filler ("kadachit ho, chalu aahe"), or the start of a new clause.
        first = next((i for i, t in enumerate(tokens) if not taken[i] and t not in FILLER), 0)
        breaks = clause_breaks(text)
        starts = breaks | {first}
        candidates = [
            m
            for m in candidates
            if not (m.end - m.start == 1 and tokens[m.start] in SENTENCE_INITIAL_ONLY)
            or m.start in starts
        ]
        matches = _claim(candidates, taken)
        if "presence_talk" in {m.label for m in meta}:
            # "haan, main yahin hoon": the "haan" answers "are you there?".
            kept = [m for m in matches if not _bare_polar(tokens, m)]
            evidence += [f"presence_talk:{tokens[m.start]}" for m in matches if m not in kept]
            matches = kept
        indicator_question = question is not None and _is_indicator_question(question, outcomes)
        indicator_ambiguous = False
        if question is not None:
            if indicator_question:
                matches, dropped = _about_the_question(text, tokens, matches, question)
                evidence += dropped
                all_candidates = matches.copy()
                matches, bindings, indicator_ambiguous, attribution_evidence = (
                    _filter_other_indicators(matches, tokens, question, text, breaks)
                )
                evidence += attribution_evidence
                matches, corrected = _remove_self_corrected(
                    matches, tokens, breaks, all_candidates, bindings
                )
                evidence.extend("corrected:" + " ".join(tokens[m.start : m.end]) for m in corrected)
            else:
                matches, dropped = _about_the_question(text, tokens, matches, question)
                evidence += dropped

        found: set[str] = set()
        for m in matches:
            if (
                not indicator_question
                and m.end in breaks
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
        if not found and polar is not None and "presence_talk" not in labels:
            free = [t for t, used in zip(tokens, taken, strict=True) if not used]
            said = {t for t in free if t not in FILLER}
            if said and said <= AFFIRM:
                found.add(polar)
                evidence.append(f"{polar}<-polar yes")
            elif said and said <= DENY:
                found.add(FLIP[polar])
                evidence.append(f"{FLIP[polar]}<-polar no")

        injection = "injection" in labels
        assumption_same_clause = any(
            max((b for b in breaks if b <= assumption.start), default=0)
            == max((b for b in breaks if b <= match.start), default=0)
            for assumption in _find(tokens, ASSUMPTION, "assumption")
            for match in matches
        )
        assumption_blocks = (
            "assumption" in labels
            and bool(found)
            and (assumption_same_clause or any(token in ASSUMPTION_CONNECTORS for token in tokens))
        )
        blocked = (
            injection
            or "stop" in labels
            or "not_observed" in labels
            or "stale" in labels
            or assumption_blocks
        )
        blocked = blocked or indicator_ambiguous
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
