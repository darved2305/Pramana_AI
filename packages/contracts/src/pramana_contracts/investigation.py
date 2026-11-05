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
    AWAITING_APPROVAL = "awaiting_approval"
    ACTING = "acting"
    """Approved; the authorised person is carrying out the action."""
    VERIFYING = "verifying"
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    CLOSED = "closed"
    """Ground truth has been revealed; no further observations are accepted."""


TERMINAL_STATUSES = frozenset(
    {
        InvestigationStatus.DECIDED,
        InvestigationStatus.ABSTAINED,
        InvestigationStatus.VERIFIED,
        InvestigationStatus.NOT_VERIFIED,
        InvestigationStatus.CLOSED,
    }
)
"""States in which the hidden truth may be revealed. A decided investigation can still
continue into approval and verification instead."""
ANSWERABLE_STATUSES = frozenset({InvestigationStatus.INVESTIGATING, InvestigationStatus.VERIFYING})


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTED = "executed"


class RequestApproval(StrictModel):
    action: Identifier
    target: Identifier
    participant_id: Identifier
    """Who will carry it out. Must hold one of the action's roles."""


class ApprovalDecision(StrictModel):
    decision: Literal["approve", "deny"]
    approver_id: Identifier | None = None
    """Ignored when sign-in is enforced: the approval records the signed-in approver."""
    note: str | None = Field(default=None, max_length=500)


class Approval(StrictModel):
    id: str
    action: Identifier
    action_label: str
    target: Identifier
    participant_id: Identifier
    status: ApprovalStatus
    risk: Literal["low", "medium", "high"]
    reversible: bool
    rationale: str
    """The decision and its probability at the time of the request."""
    requested_at: datetime
    approver_id: str | None = None
    decided_at: datetime | None = None


class CapabilityGrant(StrictModel):
    """Handed to the authorised participant only: present it to the simulator to act."""

    capability: str
    expires_at: datetime
    action: Identifier
    target: Identifier
    scenario_id: str
    sim_url: str
    instructions: str
    location_id: Identifier | None = None
    """Where the action must be carried out; the executor has to be there."""


class ReportIntervention(StrictModel):
    approval_id: str
    participant_id: Identifier


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
    max_parallel_calls: int = Field(default=1, ge=1, le=3)
    """How many people may have a question at the same time (docs/adr/0011: at most 3). With
    more than one, a question in flight is withdrawn when another answer makes it pointless."""

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
    WITHDRAWN = "withdrawn"
    """Asked in parallel, then dropped: another answer made it pointless (docs/adr/0011)."""


class Question(StrictModel):
    id: str
    action: ProbeAction
    language: TemplateLanguage
    text: str
    """Rendered from the pack's reviewed template for the participant's language."""
    outcomes: list[str]
    status: QuestionStatus
    asked_at: datetime
    kind: Literal["probe", "confirm"] = "probe"
    """``confirm``: re-asking a spoken answer the decision hinges on, before relying on it."""


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
    """The earliest question still waiting for an answer (the only one when calls are
    sequential)."""
    observations: list[Observation]
    questions_asked: int
    ground_truth: GroundTruthComparison | None = None
    approvals: list[Approval] = Field(default_factory=list)
    pending_questions: list[Question] = Field(default_factory=list)
    """Every question waiting for an answer, oldest first (several with parallel calls)."""
    max_parallel_calls: int = 1


class EventEnvelope(StrictModel):
    seq: int
    investigation_id: str
    type: str
    payload: dict[str, Any]
    ts: datetime


AnswerResult.model_rebuild()
VoiceAnswerResult.model_rebuild()
