from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pramana_contracts import (
    CreateInvestigation,
    FaultSpec,
    LanguageProfile,
    ParticipantSpec,
    Report,
    ScenarioRequest,
    SubmitAnswer,
)
from pramana_contracts.export import DEFAULT_PATH, render


def _participant(pid: str = "p_riya", **overrides: object) -> ParticipantSpec:
    data: dict[str, object] = {
        "id": pid,
        "display_name": "Riya",
        "roles": ["student"],
        "skill": "lay",
        "location_id": "F3_R304",
        "languages": {"stt_candidates": ["hi-IN", "en-IN"], "template_language": "hi-en"},
    }
    data.update(overrides)
    return ParticipantSpec.model_validate(data)


def test_create_investigation_round_trips_through_json() -> None:
    req = CreateInvestigation(
        pack_id="campus_block_c",
        participants=[_participant()],
        report=Report(text="Floor 3 pe WiFi nahi chal raha", reporter_id="p_riya"),
        scenario=ScenarioRequest(seed=7, fault=FaultSpec.model_validate(
            {"faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]}
        )),
    )
    again = CreateInvestigation.model_validate_json(req.model_dump_json())
    assert again == req


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Report.model_validate({"text": "x", "reporter_id": "a", "secret_truth": "SW_C2"})


def test_reporter_must_be_a_participant() -> None:
    with pytest.raises(ValidationError, match="reporter_id"):
        CreateInvestigation(
            pack_id="campus_block_c",
            participants=[_participant()],
            report=Report(text="x", reporter_id="p_nobody"),
            scenario=ScenarioRequest(seed=1),
        )


def test_duplicate_participants_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        CreateInvestigation(
            pack_id="campus_block_c",
            participants=[_participant(), _participant()],
            report=Report(text="x", reporter_id="p_riya"),
            scenario=ScenarioRequest(seed=1),
        )


@pytest.mark.parametrize(
    "candidates",
    [[], ["hi-IN", "hi-IN"], ["hi-IN", "en-IN", "mr-IN", "ta-IN", "te-IN"], ["as-IN"]],
)
def test_language_candidates_follow_prisma_limits(candidates: list[str]) -> None:
    with pytest.raises(ValidationError):
        LanguageProfile.model_validate({"stt_candidates": candidates})


def test_identifiers_reject_injection_characters() -> None:
    with pytest.raises(ValidationError):
        _participant(pid="p riya; drop table")


def test_answer_requires_exactly_one_of_text_or_outcome() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        SubmitAnswer(question_id="q1", participant_id="p_riya")
    with pytest.raises(ValidationError, match="exactly one"):
        SubmitAnswer(question_id="q1", participant_id="p_riya", text="haan", outcome="yes")
    assert SubmitAnswer(question_id="q1", participant_id="p_riya", outcome="yes").outcome == "yes"


def test_models_are_immutable() -> None:
    report = Report(text="x", reporter_id="a")
    with pytest.raises(ValidationError):
        report.text = "y"  # type: ignore[misc]


def test_committed_schema_bundle_matches_models() -> None:
    """Fails when a contract changed without regenerating the schema (and TS types)."""
    assert DEFAULT_PATH.read_text(encoding="utf-8") == render()


def test_schema_bundle_exposes_every_exported_model() -> None:
    bundle = json.loads(render())
    assert set(bundle["properties"]) <= set(bundle["$defs"])
    assert "InvestigationState" in bundle["$defs"]
