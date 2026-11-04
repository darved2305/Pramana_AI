"""Investigation API contracts (``/v1/investigations``)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import Directness, Hedge, Identifier, Modality, StrictModel, TemplateLanguage
from .participants import ParticipantSpec
from .reasoning import BeliefSnapshot, Extraction, Observation, PlanDecision, ProbeAction
from .sim import FaultSpec, RevealResult
from .voice import SttResult


class InvestigationStatus(StrEnum):
    INVESTIGATING = "investigating"
    DECIDED = "decided"
    ABSTAINED = "abstained"
    CLOSED = "closed"
    """Ground truth has been revealed; no further observations are accepted."""


TERMINAL_STATUSES = frozenset(
    {InvestigationStatus.DECIDED, InvestigationStatus.ABSTAINED, InvestigationStatus.CLOSED}
)


class Report(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    reporter_id: Identifier
    affected_location_id: Identifier | None = None
    """Location the report is about. Initial observations are only ever taken from explicit
    structured fields, never inferred silently from free text."""


class ScenarioRequest(StrictModel):
    """How the simulator should choose the sealed hidden fault."""

    seed: int = Field(ge=0, le=2**31 - 1)
    fault: Literal["random"] | FaultSpec = "random"


class CreateInvestigation(StrictModel):
    pack_id: Identifier
    participants: list[ParticipantSpec] = Field(min_length=1, max_length=12)
    report: Report
    scenario: ScenarioRequest

    @model_validator(mode="after")
    def _consistent(self) -> CreateInvestigation:
        ids = [p.id for p in self.participants]
        if len(set(ids)) != len(ids):
            raise ValueError("participant ids must be unique")
        if self.report.reporter_id not in ids:
            raise ValueError("report.reporter_id must be one of the participants")
        return self


class QuestionStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    CANCELLED = "cancelled"


class Question(StrictModel):
    id: str
    action: ProbeAction
    language: TemplateLanguage
    text: str
    """Rendered from the pack's reviewed template for the participant's language."""
    outcomes: list[str]
    status: QuestionStatus
    asked_at: datetime


class SubmitAnswer(StrictModel):
    """A participant's answer to the pending question.

    Exactly one of ``text`` (free speech or typing, extracted into structured evidence) and
    ``outcome`` (a structured tap answer) must be given. ``participant_id`` must match the
    participant the question was addressed to; it is never inferred from the text.
    """

    question_id: str
    participant_id: Identifier
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    outcome: str | None = None
    hedge: Hedge = Hedge.CERTAIN
    directness: Directness = Directness.DIRECT
    modality: Modality = Modality.TEXT

    @model_validator(mode="after")
    def _one_of(self) -> SubmitAnswer:
        if (self.text is None) == (self.outcome is None):
            raise ValueError("provide exactly one of text or outcome")
        return self


class AnswerResult(StrictModel):
    observation: Observation
    extraction: Extraction
    state: InvestigationState


class VoiceAnswerResult(StrictModel):
    """A spoken answer: what Gnani heard, then the same result as a typed answer."""

    stt: SttResult
    result: AnswerResult


class GroundTruthComparison(StrictModel):
    reveal: RevealResult
    true_decision_classes: list[str]
    concluded_decision: str | None
    abstained: bool
    correct: bool | None
    """None when the investigation abstained (correctness of abstention is judged by eval)."""


class InvestigationState(StrictModel):
    id: str
    pack_id: Identifier
    status: InvestigationStatus
    created_at: datetime
    report: Report
    participants: list[ParticipantSpec]
    sealed_commitment: str
    belief: BeliefSnapshot
    plan: PlanDecision
    pending_question: Question | None
    observations: list[Observation]
    questions_asked: int
    ground_truth: GroundTruthComparison | None = None


class EventEnvelope(StrictModel):
    seq: int
    investigation_id: str
    type: str
    payload: dict[str, Any]
    ts: datetime


AnswerResult.model_rebuild()
VoiceAnswerResult.model_rebuild()
