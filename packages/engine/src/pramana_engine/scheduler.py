"""Parallel questions: what to ask now, and what to withdraw, with questions still in flight.

The single-question planner (``Engine.plan``) assumes nothing is pending. With several people
on calls at once (docs/adr/0011, at most 3 per investigation), the investigation service asks
this module after every change of belief. It has no I/O, so the service, replay and the
benchmark use the same rule:

1. Nothing in flight: plan as usual (ask the best question, or conclude). If the plan asks,
   add questions for other people whose *conditional* gain, given the answers already on their
   way, is worth it (``Engine.parallel_questions``).
2. Something in flight and the belief is already conclusive (a confident decision, an
   unmodelled cause, or a verification verdict): withdraw everything in flight and conclude.
3. Otherwise withdraw the questions whose answer no longer matters (``Engine.moot``) and fill
   free slots with questions that add information given what is still in flight. The
   investigation never concludes while a question that still matters is unanswered.

Every withdrawal is also told to the engine (``Engine.question_withdrawn``) before anything
new is chosen: someone whose walk was withdrawn may already be there, so they are no longer
planned as standing where they started. The service records the place in ``QuestionWithdrawn``
and replay applies it the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pramana_contracts import CandidateScore, PlanDecision, PlanKind, ProbeAction

from .engine import Engine


@dataclass(frozen=True)
class Schedule:
    withdraw: list[int] = field(default_factory=list)
    """Indices into the questions in flight that should be withdrawn."""
    ask: list[CandidateScore] = field(default_factory=list)
    """Extra questions to ask now, beside the plan's own question (if any)."""
    plan: PlanDecision | None = None
    """The plan to apply (its question, or the conclusion) when nothing that matters remains
    in flight; ``None`` means keep waiting for the answers in flight."""


def _same(a: ProbeAction, b: ProbeAction) -> bool:
    return (a.participant_id, a.probe_id, a.location_id) == (
        b.participant_id,
        b.probe_id,
        b.location_id,
    )


def _conclusive(plan: PlanDecision) -> bool:
    if plan.kind in (PlanKind.VERIFIED, PlanKind.NOT_VERIFIED):
        return True
    if plan.kind == PlanKind.DECIDE and plan.rule == "confident":
        return True
    return plan.kind == PlanKind.ABSTAIN and plan.rule == "open_world"


def schedule(engine: Engine, pending: Sequence[ProbeAction], max_parallel: int) -> Schedule:
    if max_parallel < 1:
        raise ValueError("max_parallel must be at least 1")
    plan = engine.plan()
    if not pending:
        extras: list[CandidateScore] = []
        if plan.kind == PlanKind.ASK and plan.action is not None and max_parallel > 1:
            extras = engine.parallel_questions([plan.action], max_parallel)
        return Schedule([], extras, plan)
    if _conclusive(plan):
        for a in pending:
            engine.question_withdrawn(a)
        return Schedule(list(range(len(pending))), [], plan)
    moot = engine.moot(pending)
    if all(moot) and plan.kind == PlanKind.ASK and plan.action is not None:
        # The plan wants one of the questions in flight after all: keep that one.
        for i, a in enumerate(pending):
            if _same(a, plan.action):
                moot[i] = False
    keep = [a for a, m in zip(pending, moot, strict=True) if not m]
    withdraw = [i for i, m in enumerate(moot) if m]
    # Someone whose walk is withdrawn may be at either place now: plan with that.
    moved = [engine.question_withdrawn(pending[i]) for i in withdraw]
    if any(moved):
        plan = engine.plan()
    if not keep:
        extras = []
        if plan.kind == PlanKind.ASK and plan.action is not None and max_parallel > 1:
            extras = engine.parallel_questions([plan.action], max_parallel)
        return Schedule(withdraw, extras, plan)
    return Schedule(withdraw, engine.parallel_questions(keep, max_parallel), None)


__all__ = ["Schedule", "schedule"]
