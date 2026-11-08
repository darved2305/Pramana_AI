"""Investigation forecast: what happens if the investigation carries on (USP_LAB U12).

Advisory only. It rolls the engine's own policy forward on private copies of the engine, sampling
what could be true from the current posterior, and returns estimates. It writes no events and
never touches the investigation's engine. Answers are simulated with the health check's noise
(docs/EVALUATION.md §2), so the figures are estimates and are labelled as such. Presence checks
and confirmations are not simulated. The same investigation state always gives the same result.
"""

from __future__ import annotations

import copy
import hashlib
import random
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pramana_contracts import ParticipantSpec, PlanKind
from pramana_domain import DomainPack, World

from .engine import Engine
from .health import MAX_STEPS, _NoisyPeople
from .model import Hypothesis

ROLLOUTS = 24
Advice = Literal[
    "repair_in_progress",
    "ready_to_decide",
    "cannot_settle",
    "keep_investigating",
    "could_act_now",
    "keep_investigating_cautiously",
]
ACT_NOW_RISK = 0.25
"""Above this chance of the leading decision being wrong, acting now is not advised."""
WORTHWHILE = 0.6
"""A further investigation counts as worthwhile if it reaches the right decision this often."""


@dataclass(frozen=True)
class Forecast:
    advice: Advice
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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _copy(engine: Engine) -> Engine:
    # A fresh memo each time, so a copy shares only the read-only compiled model with the original.
    return copy.deepcopy(engine, {id(engine.model): engine.model})


def _stable(key: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def _rollout(
    base: Engine,
    pack: DomainPack,
    people: Sequence[ParticipantSpec],
    hypothesis: Hypothesis,
    key: str,
) -> tuple[str | None, int, float]:
    assert hypothesis.faults is not None
    engine = _copy(base)
    answers = _NoisyPeople(pack, World(pack, frozenset(hypothesis.faults)), list(people), key)
    asked, spent = 0, 0.0
    for _ in range(MAX_STEPS):
        plan = engine.plan()
        if plan.kind != PlanKind.ASK or plan.action is None:
            return (plan.decision_class if plan.kind == PlanKind.DECIDE else None), asked, spent
        a = plan.action
        costs = {(x.participant_id, x.probe_id, x.location_id): c for x, c in engine.menu()}
        spent += costs.get((a.participant_id, a.probe_id, a.location_id), 0.0)
        engine.record_question(a.participant_id)
        engine.observe(answers.ask(a.participant_id, a.probe_id, a.location_id))
        asked += 1
    return None, asked, spent


def forecast(engine: Engine, key: str, rollouts: int = ROLLOUTS) -> Forecast:
    """Forecast from ``engine``'s current state. ``key`` seeds the sampling, for repeatability."""
    model = engine.model
    posterior = engine.posterior()
    by_decision: dict[str, float] = {}
    outside = 0.0
    for h, p in zip(model.hypotheses, posterior, strict=True):
        if h.decision_class is None:
            outside += float(p)
        else:
            by_decision[h.decision_class] = by_decision.get(h.decision_class, 0.0) + float(p)
    leading = max(sorted(by_decision), key=lambda d: by_decision[d], default=None)
    p_leading = by_decision.get(leading, 0.0) if leading else 0.0

    if engine._repair is not None:  # the checks being made are about the repair, not the fault
        return Forecast(
            "repair_in_progress", 0, 0.0, 0.0, 0.0, 0.0, 0.0, outside, leading, p_leading, 0.0
        )

    plan = _copy(engine).plan()
    known = [
        (i, h)
        for i, h in enumerate(model.hypotheses)
        if h.faults is not None and h.decision_class is not None
    ]
    weights = [float(posterior[i]) for i, _ in known]
    if not known or sum(weights) <= 0:
        return Forecast(
            "cannot_settle",
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            outside,
            leading,
            p_leading,
            1.0 - p_leading,
        )

    people = [state.spec for state in engine.participants.values()]
    rng = _stable(key)
    drawn = rng.choices(known, weights=weights, k=rollouts)
    right = wrong = none = 0
    questions: list[int] = []
    effort: list[float] = []
    for n, (_, h) in enumerate(drawn):
        decision, asked, spent = _rollout(engine, model.pack, people, h, f"{key}:{n}")
        questions.append(asked)
        effort.append(spent)
        if decision is None:
            none += 1
        elif decision == h.decision_class:
            right += 1
        else:
            wrong += 1

    risk = 1.0 - p_leading
    advice: Advice
    if plan.kind == PlanKind.DECIDE:
        advice = "ready_to_decide"
    elif plan.kind == PlanKind.ABSTAIN:
        advice = "cannot_settle"
    elif risk < ACT_NOW_RISK:
        advice = "could_act_now"
    elif right / rollouts >= WORTHWHILE:
        advice = "keep_investigating"
    else:
        advice = "keep_investigating_cautiously"
    return Forecast(
        advice,
        rollouts,
        statistics.fmean(questions),
        statistics.fmean(effort) / 60.0,
        right / rollouts,
        wrong / rollouts,
        none / rollouts,
        outside,
        leading,
        p_leading,
        risk,
    )
