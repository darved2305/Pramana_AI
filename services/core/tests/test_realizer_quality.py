from __future__ import annotations

import copy
import re
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from pramana_contracts import ProbeAction, TemplateLanguage
from pramana_core.language.realize import CONFIRM_PREFIX, realize
from pramana_core.language.realizer_lint import (
    MAX_QUESTION_CHARACTERS,
    MAX_QUESTION_WORDS,
    lint_pack,
)
from pramana_core.language.speakable import speakable
from pramana_core.voice.conversation import QuestionAudioCache, speak_question
from pramana_core.voice.gnani import GnaniClient
from pramana_domain import DomainPack, load_pack

LANGUAGES: tuple[TemplateLanguage, ...] = ("en", "hi", "mr", "hi-en")


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return load_pack("campus_block_c")


def _change(pack: DomainPack, change: Any) -> DomainPack:
    data = copy.deepcopy(pack.model_dump(mode="python", by_alias=True))
    change(data)
    return DomainPack.model_validate(data)


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        ("DB-C2", "en", "D B C two"),
        ("DB-C2", "hi-en", "D B C two"),
        ("DB-C2", "hi", "डी बी सी टू"),
        ("DB-C2", "mr", "डी बी सी टू"),
        ("IDF-1", "en", "I D F one"),
        ("IDF-1", "hi", "आई डी एफ वन"),
        ("MAIN-1", "mr", "एम ए आय एन वन"),
        ("Wi-Fi", "en", "Wi-Fi"),
        ("WiFi", "hi", "वाई-फ़ाई"),
        ("WiFi", "mr", "वाय-फाय"),
        ("NAVA-WiFi", "en", "Nava Wi-Fi"),
        ("NAVA-WiFi", "hi", "नावा वाई-फ़ाई"),
        ("IP", "hi-en", "I P"),
        ("IP", "hi", "आई पी"),
        ("IP", "mr", "आय पी"),
        ("CCTV", "mr", "सी सी टी व्ही"),
        ("ONT", "hi", "ओ एन टी"),
        ("PON", "mr", "पी ओ एन"),
        ("GATEWAY", "hi", "गेटवे"),
        ("'IP test page'…", "en", "I P test page,"),
        ('"IP test page"...?', "en", "I P test page?"),
        ("Wait... what?!  Really?", "en", "Wait, what? Really?"),
        (
            "The IP 192.168.1.2 is listed.",
            "en",
            "The I P one nine two dot one six eight dot one dot two is listed.",
        ),
        ("192.168.1.2", "hi", "वन नाइन टू डॉट वन सिक्स एट डॉट वन डॉट टू"),
        ("Use 192.168.1.2.", "en", "Use one nine two dot one six eight dot one dot two."),
        ("room 205", "en", "room 205"),
    ],
)
def test_speakable_table(text: str, language: TemplateLanguage, expected: str) -> None:
    assert speakable(text, language) == expected


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("DB-C2", "en"),
        ("IDF-1", "hi"),
        ("NAVA-WiFi", "mr"),
        ("'IP test page'…", "hi-en"),
        ("Wait... what?!  Really?", "en"),
        ("IP 192.168.1.2", "hi"),
    ],
)
def test_speakable_is_idempotent(text: str, language: TemplateLanguage) -> None:
    spoken = speakable(text, language)
    assert speakable(spoken, language) == spoken


async def test_speak_question_synthesizes_and_caches_spoken_text() -> None:
    gnani = AsyncMock()
    gnani.synthesize.return_value = (b"RIFF audio", 12.0)
    cache = QuestionAudioCache()

    audio, cached = await speak_question(cast(GnaniClient, gnani), cache, "DB-C2", "hi")

    assert audio == b"RIFF audio"
    assert cached is False
    assert gnani.synthesize.await_args.args[0] == "डी बी सी टू"
    spoken_key = cache.key("डी बी सी टू", "hi-IN", "timbre-v3.0", None)
    display_key = cache.key("DB-C2", "hi-IN", "timbre-v3.0", None)
    assert cache.get(spoken_key) == b"RIFF audio"
    assert cache.get(display_key) is None


def test_linter_accepts_every_shipped_pack() -> None:
    for path in sorted(Path("packs").glob("*.yaml")):
        errors = lint_pack(load_pack(path))
        assert errors == [], f"{path.name}:\n" + "\n".join(errors)


def test_presence_template_linter_rejects_unknown_and_missing_slots(pack: DomainPack) -> None:
    def change(data: dict[str, Any]) -> None:
        token = data["presence_tokens"][0]
        token["prompt_templates"]["en"] = "Read {length} letters at {location}?"
        token["display_templates"]["mr"] = "पांढऱ्या लेबलवरील अक्षरे."

    errors = lint_pack(_change(pack, change))

    assert any("unknown placeholder '{location}'" in error for error in errors), errors
    assert any("placeholder '{value}' has no value" in error for error in errors), errors


@pytest.mark.parametrize(
    ("language", "replacement", "message"),
    [
        ("en", " ", "template is empty or has outer whitespace"),
        ("hi", "क्या {station} खुला है?", "unknown placeholder"),
        ("hi", "Is NAVA WiFi visible?", "mostly Devanagari"),
        ("hi", "कृपया वेबसाइट पहा।", "does not offer answer outcome"),
        ("mr", "कृपया वाय-फाय तपासा \u2014 चालू आहे का?", "em dash is not allowed"),
        ("en", "x" * (MAX_QUESTION_CHARACTERS + 1) + "?", "question limit"),
        (
            "en",
            " ".join(["yes"] * (MAX_QUESTION_WORDS + 1)) + "?",
            "word question limit",
        ),
    ],
)
def test_linter_reports_template_defects(
    pack: DomainPack, language: TemplateLanguage, replacement: str, message: str
) -> None:
    def change(data: dict[str, Any]) -> None:
        data["probes"][0]["templates"][language] = replacement

    errors = lint_pack(_change(pack, change))
    assert any(message in error for error in errors), errors


def test_linter_reports_stray_braces_after_an_unknown_placeholder(pack: DomainPack) -> None:
    def change(data: dict[str, Any]) -> None:
        data["probes"][0]["templates"]["en"] = "Can {station} see a green light?"

    errors = lint_pack(_change(pack, change))
    assert any("unknown placeholder" in error for error in errors), errors
    assert any("stray braces remain after rendering" in error for error in errors), errors


def test_linter_checks_move_template_script_without_location_labels(pack: DomainPack) -> None:
    def change(data: dict[str, Any]) -> None:
        data["move_templates"]["hi"] = "Please walk to {place}. Then:"

    errors = lint_pack(_change(pack, change))
    assert any(
        "move_templates@GUARD_DESK [hi]: text must be mostly Devanagari" in error
        for error in errors
    ), errors


def test_linter_names_move_confirmation_and_consent_templates(pack: DomainPack) -> None:
    def change(data: dict[str, Any]) -> None:
        data["move_templates"]["mr"] = "  "

    errors = lint_pack(_change(pack, change))
    assert any("move_templates" in error and "[mr]" in error for error in errors)

    assert set(CONFIRM_PREFIX) == set(LANGUAGES)
    assert all(text and text == text.strip() for text in CONFIRM_PREFIX.values())


def test_move_templates_keep_a_polite_request_to_walk_to_the_location(pack: DomainPack) -> None:
    assert "Could you please walk to {place}?" in pack.move_templates["en"]
    assert "ja sakte hain?" in pack.move_templates["hi-en"]
    assert "जा सकते हैं?" in pack.move_templates["hi"]
    assert "जाऊ शकाल का?" in pack.move_templates["mr"]


def test_every_rendered_question_normalizes_for_all_languages_and_locations(
    pack: DomainPack,
) -> None:
    for probe in pack.probes:
        for binding in probe.observes:
            for language in LANGUAGES:
                for requires_move in (False, True):
                    action = ProbeAction(
                        participant_id="p_riya",
                        probe_id=probe.id,
                        location_id=binding.at,
                        requires_move=requires_move,
                    )
                    display = realize(pack, action, language)
                    for displayed_variant in (display, CONFIRM_PREFIX[language] + " " + display):
                        spoken = speakable(displayed_variant, language)
                        assert "{" not in spoken
                        assert "}" not in spoken
                        assert speakable(spoken, language) == spoken
                        assert len(spoken) <= MAX_QUESTION_CHARACTERS
                        assert len(spoken.split()) <= MAX_QUESTION_WORDS
                        assert not re.search(r"\b[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)+\b", spoken)


def test_native_speaker_review_sheet_matches_generator() -> None:
    generator = runpy.run_path("scripts/generate_language_review.py")
    render = cast(Callable[[], str], generator["render_review_sheet"])
    expected = render()
    output = Path("docs/engineering/LANGUAGE_REVIEW.md").read_text(encoding="utf-8")
    assert output == expected
    rows = [line for line in expected.splitlines() if line.startswith(("| hi |", "| mr |"))]
    assert len(rows) == 440
    assert all(line.endswith("|  |") for line in rows)
