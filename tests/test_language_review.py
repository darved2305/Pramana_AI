"""The native-speaker review sheet lists every Hindi and Marathi line the product can say."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_language_review as review  # noqa: E402

from pramana_domain import load_pack  # noqa: E402


def test_the_committed_sheet_is_current() -> None:
    assert review.main(["--check"]) == 0


def test_every_probe_place_and_presence_check_is_listed_in_both_languages() -> None:
    sheet = review.render_review_sheet()
    pack = load_pack("campus_block_c")
    for lang in review.LANGUAGES:
        for probe in pack.probes:
            for b in probe.observes:
                assert f"| {lang} | {probe.id} | {b.at} | move confirmation |" in sheet
        for token in pack.presence_tokens:
            assert f"| {lang} | {token.id} | {token.at} | presence check |" in sheet
    assert ":  " not in sheet  # confirmations are joined exactly as the core joins them
