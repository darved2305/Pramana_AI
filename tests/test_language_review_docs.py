"""The generated language packet covers localized UI, spoken, and template copy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_language_review as review  # noqa: E402


def test_committed_language_review_packet_is_current() -> None:
    assert review.main(["--check"]) == 0


def test_packet_has_context_for_all_three_languages_and_localized_sources() -> None:
    sheet = review.render_review_sheet()
    assert "# Hindi, Marathi, and Hinglish language review" in sheet
    assert "| Language | Source path and context |" in sheet
    for language in ("Hindi", "Marathi", "Hinglish"):
        assert f"| {language} |" in sheet
    for source in (
        "packs/campus_block_c.yaml",
        "packs/templates/building_water_supply.yaml",
        "packages/domain/src/pramana_domain/templates/office_water.json",
        "packages/domain/src/pramana_domain/builder.py",
        "services/core/src/pramana_core/language/speakable.py",
        "services/core/src/pramana_core/voice/call.py",
        "apps/web/src/app/consent/[token]/ConsentForm.tsx",
        "apps/web/src/components/landing/Hero.tsx",
        "apps/web/src/lib/preview/fixtures.ts",
    ):
        assert source in sheet
    rows = [
        line
        for line in sheet.splitlines()
        if line.startswith("| ") and not line.startswith(("| Language |", "| ---"))
    ]
    assert rows
    assert all(line.endswith("| unchecked |") for line in rows)
