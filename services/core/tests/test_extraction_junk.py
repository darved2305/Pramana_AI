"""Irrelevant, vague and phone-call speech must never become evidence, for any question in any
language, while real answers (including ones with extra detail) are still read.

Found by sending real off-topic speech and phone fillers through every question: "haan haan
bolo" ("yes, go on") was read as "yes", and "corridor ki lights on hai" as an answer about the
CCTV screen.
"""

from __future__ import annotations

import pytest
from pramana_contracts import ProbeAction, TemplateLanguage
from pramana_core.language.extraction import RuleExtractor
from pramana_core.language.realize import realize
from pramana_domain import load_pack

PACK = load_pack("campus_block_c")
X = RuleExtractor()
LANGS: tuple[TemplateLanguage, ...] = ("en", "hi", "mr", "hi-en")

JUNK = [
    # phone pick-up and fillers
    "haan haan bolo",
    "haan bolo",
    "haan ji boliye",
    "हाँ, hello",
    "हाँ बोलिए",
    "hello hello, sunai de raha hai?",
    "हो बोला",
    "ok",
    "हम्म",
    # talking about being there, not about the question
    "हाँ, मैं थोड़ी देर यहीं हूँ",
    "haan main yahin hoon",
    "हो, मी इथेच आहे",
    "yes I am here",
    # off-topic
    "मैं दर्शन बोल रहा हूँ",
    "माझं नाव आर्या आहे",
    "तुम्ही कसे आहात?",
    "Third floor",
    "ek minute ruko",
    "kaun bol raha hai?",
    # do not know
    "पता नहीं यार",
    "माहीत नाही",
]


def _question(probe_id: str, lang: TemplateLanguage) -> str:
    probe = PACK.probe_by_id[probe_id]
    action = ProbeAction(
        participant_id="x", probe_id=probe_id, location_id=probe.observes[0].at, requires_move=False
    )
    return realize(PACK, action, lang)


@pytest.mark.parametrize("text", JUNK)
def test_junk_is_never_evidence_for_any_question(text: str) -> None:
    for probe in PACK.probes:
        for lang in LANGS:
            got = X.extract_sync(text, probe.outcomes, question=_question(probe.id, lang))
            assert got.outcome == "unknown", (probe.id, lang, got.evidence)


@pytest.mark.parametrize(
    ("text", "asked"),
    [
        ("corridor की lights on है, वो ठीक है", "nvr_screen"),
        ("corridor ki lights on hain", "ap_light"),
        ("corridor की लाइट जल रही है", "closet_light"),
        ("wifi box ki light off hai", "nvr_screen"),
        ("screen band hai", "corridor_lights"),
    ],
)
def test_an_answer_about_another_thing_is_not_an_answer(text: str, asked: str) -> None:
    probe = PACK.probe_by_id[asked]
    for lang in LANGS:
        got = X.extract_sync(text, probe.outcomes, question=_question(asked, lang))
        assert got.outcome == "unknown", (lang, got.evidence)


@pytest.mark.parametrize(
    ("text", "asked", "expected"),
    [
        ("corridor की lights on है, वो ठीक है", "corridor_lights", "on"),
        ("lights on hain, wifi nahi chal raha", "corridor_lights", "on"),
        ("haan", "internet_works", "yes"),
        ("हाँ, खुल रही है", "internet_works", "yes"),
        ("हाँ, चालू है", "nvr_screen", "on"),
        ("screen band hai", "nvr_screen", "off"),
        ("haan bolo, screen band hai", "nvr_screen", "off"),
        ("hello, haan website khul rahi hai", "internet_works", "yes"),
        ("main yahin hoon, lights band hain", "corridor_lights", "off"),
        ("Actually WiFi बिल्कुल काम नहीं कर रहा", "internet_works", "no"),
        ("नवा WiFi दिख ही नहीं रहा", "wifi_status", "no_network"),
        ("breaker neeche hai", "breaker_c2_7", "tripped"),
    ],
)
def test_real_answers_are_still_read(text: str, asked: str, expected: str) -> None:
    probe = PACK.probe_by_id[asked]
    for lang in LANGS:
        got = X.extract_sync(text, probe.outcomes, question=_question(asked, lang))
        assert got.outcome == expected, (lang, got.evidence)
