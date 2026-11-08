"""Export the JSON Schema bundle consumed by the TypeScript generator.

Usage: ``python -m pramana_contracts.export [output_path]``. ``--check`` exits non-zero when the
committed bundle differs from the models (schema drift).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from . import (
    CONTRACTS_VERSION,
    AnswerResult,
    ApprovalDecision,
    AuthSession,
    CapabilityGrant,
    CreateInvestigation,
    CreateOrganization,
    CurrentAccount,
    DirectoryParticipant,
    EvaluationReport,
    EvaluationReportSummary,
    EventEnvelope,
    InvestigationPage,
    InvestigationState,
    LoginRequest,
    MediaClientMessage,
    MediaServerMessage,
    OnboardingPatch,
    OnboardingState,
    OrganizationCreated,
    PackSummary,
    ParticipantPatch,
    ParticipantView,
    ReportIntervention,
    RequestApproval,
    RevealResult,
    SessionDevice,
    SttResult,
    SubmitAnswer,
    TtsRequest,
    VoiceAnswerResult,
)

EXPORTED: tuple[type[BaseModel], ...] = (
    CreateOrganization,
    CurrentAccount,
    OnboardingPatch,
    OnboardingState,
    OrganizationCreated,
    CreateInvestigation,
    InvestigationState,
    SubmitAnswer,
    AnswerResult,
    VoiceAnswerResult,
    RequestApproval,
    ApprovalDecision,
    CapabilityGrant,
    ReportIntervention,
    EventEnvelope,
    ParticipantView,
    RevealResult,
    SttResult,
    TtsRequest,
    MediaClientMessage,
    MediaServerMessage,
    LoginRequest,
    AuthSession,
    DirectoryParticipant,
    SessionDevice,
    ParticipantPatch,
    InvestigationPage,
    PackSummary,
    EvaluationReportSummary,
    EvaluationReport,
)

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "schema" / "pramana.schema.json"


def build_bundle() -> dict[str, object]:
    _, schema = models_json_schema(
        [(m, "serialization") for m in EXPORTED],
        title="Pramana contracts",
        ref_template="#/$defs/{model}",
    )
    defs = schema.get("$defs", {})
    # A root object referencing every exported model makes json-schema-to-typescript emit them.
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PramanaContracts",
        "description": f"Pramana contracts v{CONTRACTS_VERSION}. Generated; do not edit.",
        "type": "object",
        "properties": {m.__name__: {"$ref": f"#/$defs/{m.__name__}"} for m in EXPORTED},
        "additionalProperties": False,
        "$defs": defs,
    }


def render() -> str:
    return json.dumps(build_bundle(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    paths = [a for a in argv if not a.startswith("--")]
    path = Path(paths[0]) if paths else DEFAULT_PATH
    text = render()
    if check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != text:
            print(f"schema drift: {path} is out of date; run `make contracts`", file=sys.stderr)
            return 1
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
