"""The native-speaker review packet lists localized product text and runtime questions."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_language_review as review  # noqa: E402

from pramana_domain import load_pack  # noqa: E402


def test_the_committed_sheet_is_current() -> None:
    assert review.main(["--check"]) == 0


def test_every_probe_place_and_presence_check_is_listed_in_each_language() -> None:
    sheet = review.render_review_sheet()
    pack = load_pack("campus_block_c")
    for lang in review.LANGUAGES:
        language = review.LANGUAGE_NAMES[lang]
        for probe in pack.probes:
            for b in probe.observes:
                for requires_move in (False, True):
                    form = "move" if requires_move else "direct"
                    for confirmation in (False, True):
                        if confirmation:
                            form += " confirmation"
                        row = (
                            f"| {language} | `packs/campus_block_c.yaml`: probe {probe.id} "
                            f"at {b.at}, {form} |"
                        )
                        assert row in sheet
        for token in pack.presence_tokens:
            assert (
                f"| {language} | `packs/campus_block_c.yaml`: presence check "
                f"{token.id} at {token.at} |"
            ) in sheet
    data_rows = [
        line
        for line in sheet.splitlines()
        if line.startswith("| ") and not line.startswith(("| Language |", "| ---"))
    ]
    assert data_rows
    assert all(line.endswith("| unchecked |") for line in data_rows)
    assert "| Hinglish |" in sheet
    assert "services/core/src/pramana_core/language/speakable.py" in sheet
    assert "packages/domain/src/pramana_domain/builder.py" in sheet
