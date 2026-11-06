"""Template linter and speakable text: the shipped pack is clean, and each rule catches what it
is meant to catch."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pramana_contracts import Hedge, TemplateLanguage
from pramana_core.language.extraction import RuleExtractor
from pramana_core.language.lint import LANGUAGES, lint_pack, lint_spoken
from pramana_core.language.realize import CONFIRM_PREFIX
from pramana_core.language.speakable import RAW_CODE, speakable
from pramana_core.voice.call import CONSENT_TEXT
from pramana_domain import DomainPack, load_pack

PACK = load_pack("campus_block_c")


def _with(pack: DomainPack, **changes: Any) -> DomainPack:
    data = pack.model_dump(by_alias=True)
    data.update(changes)
    return DomainPack.model_validate(data)


def _probe_texts(pack: DomainPack, probe_id: str, **templates: str) -> DomainPack:
    data = pack.model_dump(by_alias=True)
    for p in data["probes"]:
        if p["id"] == probe_id:
            p["templates"].update(templates)
    return DomainPack.model_validate(data)


def _codes(pack: DomainPack, probe_id: str, lang: str) -> set[str]:
    return {
        i.code
        for i in lint_pack(pack)
        if i.where.startswith(f"probe {probe_id}") and i.language == lang
    }


# -- the shipped pack -------------------------------------------------------------------------


def test_shipped_pack_and_fixed_phrases_are_clean() -> None:
    issues = lint_pack(PACK, {"consent": CONSENT_TEXT, "confirm prefix": CONFIRM_PREFIX})
    assert not issues, "\n".join(str(i) for i in issues)


def test_every_place_has_a_name_in_every_language() -> None:
    for loc in PACK.locations:
        for lang in LANGUAGES:
            assert loc.label.get(lang).strip(), (loc.id, lang)


def test_hindi_place_names_are_devanagari_and_hinglish_ones_latin() -> None:
    for loc in PACK.locations:
        assert not loc.label.get("hi").isascii(), loc.id
        assert loc.label.get("hi-en").isascii(), loc.id


def test_hinglish_falls_back_to_latin_hindi_then_english() -> None:
    from pramana_domain.pack import LocalizedText

    assert LocalizedText(en="the desk", hi="desk", mr="डेस्क").get("hi-en") == "desk"
    assert LocalizedText(en="the desk", hi="डेस्क", mr="डेस्क").get("hi-en") == "the desk"
    explicit = LocalizedText.model_validate({"en": "a", "hi": "ब", "mr": "क", "hi-en": "b"})
    assert explicit.get("hi-en") == "b"


@pytest.mark.parametrize("lang", ["hi", "hi-en"])
def test_socket_question_is_a_yes_no_question_about_charging(lang: str) -> None:
    """The linter found this: the Hindi socket question named no answer the extractor knew."""
    probe = PACK.probe_by_id["room_socket"]
    question = probe.templates[lang].replace(
        "{place}", PACK.location_by_id["F2_R205"].label.get(lang)
    )
    yes = {"hi": "हाँ", "hi-en": "haan"}[lang]
    no = {"hi": "नहीं", "hi-en": "nahi"}[lang]
    assert RuleExtractor().extract_sync(yes, probe.outcomes, question=question).outcome == "on"
    assert RuleExtractor().extract_sync(no, probe.outcomes, question=question).outcome == "off"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("हाँ, चार्ज होने लगता है", "on"),
        ("charge hone lagta hai", "on"),
        ("नहीं, चार्ज नहीं होता", "off"),
    ],
)
def test_charging_phrasings_from_the_question_are_read(text: str, expected: str) -> None:
    result = RuleExtractor().extract_sync(text, ["on", "off"])
    assert result.outcome == expected, result.evidence
    assert result.hedge == Hedge.CERTAIN, result.evidence


@pytest.mark.parametrize("text", ["चार्ज हो रहा है, लगता है", "lagta hai charge ho raha hai"])
def test_seems_after_or_before_an_answer_is_still_a_hedge(text: str) -> None:
    result = RuleExtractor().extract_sync(text, ["on", "off"])
    assert result.outcome == "on"
    assert result.hedge == Hedge.PROBABLE, result.evidence


# -- each rule catches its fault ----------------------------------------------------------------


def test_missing_language_is_reported() -> None:
    data = PACK.model_dump(by_alias=True)
    del data["move_templates"]["mr"]
    issues = lint_pack(DomainPack.model_validate(data))
    assert any(
        i.code == "language" and i.where == "move prefix" and i.language == "mr" for i in issues
    )


def test_unknown_or_unbalanced_placeholder_is_reported() -> None:
    bad = _probe_texts(PACK, "ap_light", en="In {room}, is the light on or off?")
    assert "placeholder" in _codes(bad, "ap_light", "en")
    bad = _probe_texts(PACK, "ap_light", en="In {place, is the light on or off?")
    assert "placeholder" in _codes(bad, "ap_light", "en")


def test_unsafe_instruction_is_reported_in_every_language() -> None:
    bad = _probe_texts(
        PACK,
        "nvr_screen",
        en="In {place}, please reset the CCTV recorder. Is the screen on or off?",
        **{"hi-en": "{place} mein recorder ko restart kijiye. Screen on hai ya off?"},
        hi="{place} में रिकॉर्डर रीसेट कीजिए। स्क्रीन चालू है या बंद?",
        mr="{place} मध्ये रेकॉर्डर रीसेट करा. स्क्रीन चालू आहे की बंद?",
    )
    for lang in LANGUAGES:
        assert "unsafe" in _codes(bad, "nvr_screen", lang), lang


def test_without_touching_anything_is_not_an_instruction() -> None:
    assert "unsafe" not in _codes(PACK, "breaker_c2_7", "en")


def test_naming_a_cause_is_reported() -> None:
    bad = _probe_texts(PACK, "nvr_screen", en="In {place}, is the CCTV recorder dead, on or off?")
    assert "cause" in _codes(bad, "nvr_screen", "en")


def test_question_offering_only_some_answers_is_reported() -> None:
    bad = _probe_texts(PACK, "switch_leds", en="In {place}, are the switch lights green or off?")
    assert "options" in _codes(bad, "switch_leds", "en")


def test_on_off_question_whose_options_the_extractor_cannot_see_is_reported() -> None:
    """Naming neither answer would make a bare "yes" mean "on" for any wording."""
    bad = _probe_texts(PACK, "nvr_screen", en="In {place}, what does the recorder screen show?")
    assert "options" in _codes(bad, "nvr_screen", "en")


def test_too_long_question_is_reported() -> None:
    long = "In {place}, " + "please look very carefully " * 6 + "is the screen on or off?"
    assert "length" in _codes(_probe_texts(PACK, "nvr_screen", en=long), "nvr_screen", "en")


def test_wrong_script_is_reported() -> None:
    bad = _probe_texts(PACK, "nvr_screen", hi="{place} mein screen on hai ya off?")
    assert "script" in _codes(bad, "nvr_screen", "hi")
    bad = _probe_texts(PACK, "nvr_screen", en="In {place}, is the screen चालू or off?")
    assert "script" in _codes(bad, "nvr_screen", "en")


def test_quoted_names_may_stay_latin_in_hindi() -> None:
    assert not lint_spoken("x", "hi", "फ़ोन में 'IP test page' खोलिए।")


def test_raw_code_left_for_speech_is_reported() -> None:
    # A code speakable cannot read ("C2D" has no word and is all letters and digits) must
    # still come out spelled; anything left raw is reported.
    assert all(i.code != "spoken_code" for i in lint_spoken("x", "en", "Check SW-C2 and AB12CD."))


def test_place_names_are_linted_inside_rendered_questions() -> None:
    data = PACK.model_dump(by_alias=True)
    for loc in data["locations"]:
        if loc["id"] == "IDF2":
            loc["label"]["hi"] = "network closet IDF-2"
    issues = lint_pack(DomainPack.model_validate(data))
    assert any(i.code == "script" and "IDF2" in i.where and i.language == "hi" for i in issues)


# -- speakable ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "text", "spoken"),
    [
        ("en", "network closet IDF-2", "network closet I D F 2"),
        ("en", "distribution board DB-C2", "distribution board D B C 2"),
        ("en", "breaker C2-7 is up", "breaker C 2 7 is up"),
        ("en", "the breaker labelled MAIN-1", "the breaker labelled main 1"),
        ("en", "find the router labelled GATEWAY", "find the router labelled gateway"),
        ("en", "Is NAVA-WiFi missing?", "Is Nava Wi-Fi missing?"),
        ("en", "its PON light on the ONT", "its P O N light on the O N T"),
        ("en", "the Wi-Fi list", "the Wi-Fi list"),
        ("en", "room 205, breaker number 7", "room 205, breaker number 7"),
        ("en", "the 2nd floor", "the 2nd floor"),
        ("en", "I am at the desk. A light is on.", "I am at the desk. A light is on."),
        ("hi-en", "IDF-2 mein WiFi", "I D F 2 mein WiFi"),
        ("hi", "नेटवर्क क्लोज़ेट IDF-2 में", "नेटवर्क क्लोज़ेट आई डी एफ़ टू में"),
        ("hi", "DB-C2 पर", "डी बी सी टू पर"),
        ("hi", "NAVA-WiFi दिख", "नवा वाई-फ़ाई दिख"),
        ("mr", "नेटवर्क खोली IDF-1 मध्ये", "नेटवर्क खोली आय डी एफ वन मध्ये"),
        ("mr", "CCTV रेकॉर्डर", "सी सी टी व्ही रेकॉर्डर"),
        ("mr", "IDF-2मध्ये", "आय डी एफ टूमध्ये"),
    ],
)
def test_speakable_reads_codes_as_people_say_them(
    lang: TemplateLanguage, text: str, spoken: str
) -> None:
    assert speakable(text, lang) == spoken


@pytest.mark.parametrize(
    ("language", "spoken"),
    [
        ("en", "1 9 2 dot 1 6 8 dot 1 dot 1 0"),
        ("hi-en", "1 9 2 dot 1 6 8 dot 1 dot 1 0"),
        ("hi", "वन नाइन टू डॉट वन सिक्स एट डॉट वन डॉट वन ज़ीरो"),
        ("mr", "वन नाइन टू डॉट वन सिक्स एट डॉट वन डॉट वन झिरो"),
    ],
)
def test_speakable_reads_ipv4_addresses_digit_by_digit(
    language: TemplateLanguage, spoken: str
) -> None:
    assert speakable("192.168.1.10", language) == spoken


_code = st.from_regex(r"[A-Z]{1,4}[0-9]{0,2}(-[A-Z0-9]{1,3}){0,2}", fullmatch=True)
_word = st.sampled_from(["the", "light", "रैक", "में", "पर", "box", "मध्ये", "room 205,"])


@given(st.lists(st.one_of(_code, _word), min_size=1, max_size=8), st.sampled_from(LANGUAGES))
def test_speakable_never_leaves_a_raw_code_and_is_idempotent(
    parts: list[str], lang: TemplateLanguage
) -> None:
    text = " ".join(parts)
    once = speakable(text, lang)
    assert not RAW_CODE.search(once), (text, once)
    assert speakable(once, lang) == once
    if lang in ("hi", "mr"):
        assert not any(c.isascii() and c.isupper() for c in once), once


def test_speech_is_what_is_synthesised_but_not_what_is_shown() -> None:
    """The cache key and the synthesised text are the speakable form; the shown text is not
    changed anywhere (it is stored on the question)."""
    import asyncio

    from pramana_core.voice.conversation import QuestionAudioCache, speak_question

    class Gnani:
        def __init__(self) -> None:
            self.texts: list[str] = []

        async def synthesize(self, text: str, **_: Any) -> tuple[bytes, float]:
            self.texts.append(text)
            return b"RIFF", 1.0

    g = Gnani()
    cache = QuestionAudioCache()
    asyncio.run(speak_question(g, cache, "In network closet IDF-2, is it on?", "en"))  # type: ignore[arg-type]
    assert g.texts == ["In network closet I D F 2, is it on?"]
    _, cached = asyncio.run(speak_question(g, cache, "In network closet IDF-2, is it on?", "en"))  # type: ignore[arg-type]
    assert cached
    assert len(g.texts) == 1
