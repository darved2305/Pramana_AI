"""Answers about any equipment are understood, not only the hostel's Wi-Fi and power words."""

from __future__ import annotations

import pytest

from pramana_core.language.extraction import RuleExtractor
from pramana_domain.builder import SiteDescription, build
from pramana_domain.catalog import templates


@pytest.mark.parametrize(
    ("text", "outcomes", "expected"),
    [
        ("it is dry", ["flowing", "dry"], "dry"),
        ("haan paani aa raha hai", ["flowing", "dry"], "flowing"),
        ("नल सूखा है", ["flowing", "dry"], "dry"),
        ("पाणी येतंय", ["flowing", "dry"], "flowing"),
        ("pump band hai", ["running", "stopped"], "stopped"),
        ("handle khula hai", ["open", "closed"], "open"),
        ("hawa thandi hai", ["cool", "warm"], "cool"),
        ("payment ho gaya", ["approved", "failing"], "approved"),
        ("tank khaali hai", ["has_water", "empty"], "empty"),
        ("it is flooded", ["normal", "flooded"], "flooded"),  # an author's own outcome word
        ("I don't know", ["flowing", "dry"], "unknown"),
    ],
)
def test_general_outcomes(text: str, outcomes: list[str], expected: str) -> None:
    assert RuleExtractor().extract_sync(text, outcomes).outcome == expected


def test_a_negated_answer_is_not_guessed() -> None:
    # "Water is not coming" must never be read as "flowing"; asking again is the safe outcome.
    assert (
        RuleExtractor().extract_sync("paani nahi aa raha", ["flowing", "dry"]).outcome != "flowing"
    )


def test_every_template_outcome_has_words() -> None:
    """Each outcome a starter template can produce is recognised when said plainly."""
    extractor = RuleExtractor()
    for tid, doc in templates().items():
        pack = build(SiteDescription.model_validate(doc["description"])).pack
        for probe in pack.probes:
            for outcome in probe.outcomes:
                said = outcome.replace("_", " ")
                got = extractor.extract_sync(f"it is {said}", probe.outcomes).outcome
                assert got == outcome, (tid, probe.id, outcome, got)
