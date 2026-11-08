"""Belief, plan and observation contracts produced by the engine.

Every number here is computed by deterministic code in ``pramana_engine``; nothing in these
models is written by a language model.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from .common import (
    Directness,
    Hedge,
    Identifier,
    Modality,
    Probability,
    StrictModel,
)


class HypothesisBelief(StrictModel):
    id: str
    label: str
    probability: Probability
    decision_class: str | None
    """``None`` for OPEN_WORLD, which maps to no operational decision."""


class DecisionBelief(StrictModel):
    id: str
    label: str
    probability: Probability


class BeliefSnapshot(StrictModel):
    hypotheses: list[HypothesisBelief]
    """All hypotheses, sorted by descending probability."""
    decisions: list[DecisionBelief]
    hypothesis_entropy_bits: float = Field(ge=0)
    decision_entropy_bits: float = Field(ge=0)
    open_world_probability: Probability
    map_decision: str | None
    map_decision_probability: Probability
    expected_loss_now_min: float = Field(ge=0)
    """Expected loss (minutes-equivalent) of acting on the best decision right now."""
    observations_used: int = Field(ge=0)
    repair: RepairState | None = None


class RepairState(StrictModel):
    """Belief about a repair that has been carried out."""

    action: str
    target: str
    fixed_probability: Probability
    """P(the symptoms are now resolved): the cause was this target AND the repair worked."""
    post_repair_observations: int = Field(ge=0)


class ProbeAction(StrictModel):
    participant_id: Identifier
    probe_id: Identifier
    location_id: Identifier
    requires_move: bool
    """True when the participant must walk to ``location_id`` first."""


class OutcomePreview(StrictModel):
    outcome: str
    probability: Probability
    top_hypothesis: str
    top_hypothesis_probability: Probability
    decision: str | None
    decision_probability: Probability


class CandidateScore(StrictModel):
    action: ProbeAction
    eig_decision_bits: float = Field(ge=0)
    eig_hypothesis_bits: float = Field(ge=0)
    cost_s: float = Field(gt=0)
    score: float = Field(ge=0)
    """(EIG_D + eta * EIG_H) / cost, in bits per second."""
    net_value_min: float
    """Two-step adaptive value of information minus effort cost, in minutes-equivalent."""
    outcomes: list[OutcomePreview]


class InfeasibleAction(StrictModel):
    participant_id: Identifier
    probe_id: Identifier
    location_id: Identifier
    reasons: list[str]


class PlanKind(StrEnum):
    ASK = "ask"
    DECIDE = "decide"
    ABSTAIN = "abstain"
    VERIFIED = "verified"
    """After a repair: the symptoms are resolved with high probability."""
    NOT_VERIFIED = "not_verified"
    """After a repair: the evidence says it did not fix the problem, or cannot tell."""


PlanRule = Literal[
    "confident",
    "positive_value",
    "no_value_confident_enough",
    "no_value_low_confidence",
    "open_world",
    "no_feasible_action",
    "verification_confirmed",
    "verification_failed",
    "verification_inconclusive",
]
"""Which branch of the stopping rule produced a plan."""


class PlanDecision(StrictModel):
    kind: PlanKind
    action: ProbeAction | None = None
    decision_class: str | None = None
    decision_probability: Probability | None = None
    moderate_confidence: bool = False
    reason: str
    """Generated from the scoring trace by a fixed template, never by an LLM."""
    rule: PlanRule
    candidates: list[CandidateScore]
    """Top feasible candidates, best first."""
    infeasible: list[InfeasibleAction]
    """Informative actions that cannot be performed now, with reasons (for abstention)."""


class Extraction(StrictModel):
    """Structured meaning of one participant answer. Never contains decisions."""

    outcome: str
    """One of the probe's outcomes, or ``unknown``."""
    hedge: Hedge
    directness: Directness
    injection_suspected: bool = False
    wants_to_stop: bool = False
    method: Literal["rules", "llm", "structured"]
    evidence: list[str] = Field(default_factory=list)
    """Matched spans that justify the outcome (auditing aid)."""


class ObservationState(StrEnum):
    COMMITTED = "committed"
    SUPERSEDED = "superseded"
    DISCARDED = "discarded"
    """Recorded but not used as evidence (unknown outcome or a participant's conclusion)."""


class Observation(StrictModel):
    id: str
    question_id: str | None
    participant_id: Identifier
    probe_id: Identifier
    location_id: Identifier
    outcome: str
    hedge: Hedge
    directness: Directness
    modality: Modality
    transcript: str | None = None
    extraction_method: Literal["rules", "llm", "structured"]
    injection_suspected: bool = False
    state: ObservationState
    committed_at: datetime


BeliefSnapshot.model_rebuild()


class InvestigationForecast(StrictModel):
    """An estimate of how this investigation will go if it carries on. Advisory only: it is
    computed on a private copy of the engine and never changes the investigation."""

    advice: Literal[
        "repair_in_progress",
        "ready_to_decide",
        "cannot_settle",
        "keep_investigating",
        "could_act_now",
        "keep_investigating_cautiously",
    ]
    rollouts: int
    expected_questions: float
    expected_minutes: float
    p_right_decision: float
    p_wrong_decision: float
    p_no_decision: float
    p_outside_model: float
    leading_decision: str | None
    p_leading_decision: float
    p_wrong_if_acted_now: float


class MapDriftFinding(StrictModel):
    component: str
    component_label: str
    documented: str
    documented_label: str
    proposed: str
    proposed_label: str
    probability: float
    best_fault: str
    best_fault_label: str


class MapDriftCheck(StrictModel):
    """Whether the site's own map may be wrong. Advisory only: it proposes a documentation
    check and changes nothing about the investigation or the model."""

    status: Literal["ok", "not_enough_evidence", "repair_in_progress"]
    variants_checked: int
    findings: list[MapDriftFinding]
