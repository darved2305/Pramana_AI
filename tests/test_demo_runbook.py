"""Demo instructions describe the executable rehearsal paths and evidence sources."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runbook_covers_preflight_and_each_rehearsal_variant() -> None:
    text = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    assert "## Rehearsal runbook" in text
    assert "make preflight" in text
    assert "--scenario S1" in text
    assert "--scenario S2" in text
    assert "--scenario S7 --variant adversary" in text
    assert "--scenario S7 --variant honest" in text
    assert "presence_checks" in text
    assert "PRAMANA_APPROVER_EMAIL" in text
    assert "PRAMANA_APPROVER_PASSWORD" in text


def test_honesty_checklist_names_generated_rehearsal_evidence_and_no_em_dash() -> None:
    text = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    assert chr(0x2014) not in text
    assert "generated rehearsal report" in text.lower()
    assert "recorded take log" in text.lower()


def test_readme_judge_path_reaches_participants_approval_reveal_and_replay() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in (
        "Participant links",
        "Create link",
        "approver-only invitation",
        "separate browser context",
        "Replay identical",
    ):
        assert phrase in text
