"""Run policies over scenarios and compute the metrics of docs/EVALUATION.md §4."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from pramana_contracts import PlanKind, ProbeAction
from pramana_domain import DomainPack
from pramana_engine import CompiledModel, Engine, Evidence, schedule

from .policies import Conclusion, History, ParallelOurs, Policy
from .scenarios import Answers, Scenario

MAX_STEPS = 30


@dataclass(frozen=True)
class Episode:
    policy: str
    seed: int
    kind: str
    identifiable: bool | None
    decided: bool
    decision: str | None
    confidence: float
    correct: bool
    """Decided and the decision is one the true faults need."""
    success: bool
    """Correct, or abstained where abstaining is right (unidentifiable or outside the model)."""
    probes: int
    effort_s: float
    people: int
    hit_step_limit: bool
    failed: bool = False
    wall_s: float = 0.0
    """Simulated time from the report to the conclusion. Sequential questions take their
    effort one after another; parallel ones overlap."""
    withdrawn: int = 0
    """Questions withdrawn in flight because another answer made them pointless."""
    presence_challenges: int = 0


def run_episode(
    pack: DomainPack,
    model: CompiledModel,
    scenario: Scenario,
    policy: Policy,
    *,
    presence_checks: bool = False,
) -> Episode:
    if isinstance(policy, ParallelOurs):
        return run_parallel_episode(pack, model, scenario, policy, presence_checks=presence_checks)
    engine = Engine(model, scenario.specs, policy.config)
    answers = Answers(pack, scenario)
    report = answers.report()
    engine.observe(report)
    policy.start(scenario, report)
    history: History = []
    effort = 0.0
    presence_challenges = 0
    conclusion: Conclusion | None = None
    for _ in range(MAX_STEPS):
        step = policy.next(engine, history)
        if isinstance(step, Conclusion):
            conclusion = step
            break
        costs = {(a.participant_id, a.probe_id, a.location_id): c for a, c in engine.menu()}
        key = (step.participant_id, step.probe_id, step.location_id)
        if key not in costs:  # an infeasible choice (only the LLM can make one) is wasted
            history.append((step, Evidence(*key, "refused")))
            continue
        effort += costs[key]
        engine.record_question(step.participant_id)
        ev = answers.ask(*key)
        observed = engine.observe(ev)
        history.append((step, ev))
        if presence_checks:
            presence_challenges += _challenge_presence(engine, answers, ev, observed)
    hit_limit = conclusion is None
    if conclusion is None:
        snap = engine.snapshot()
        conclusion = Conclusion(None, snap.map_decision_probability)
    decided = conclusion.decision is not None
    correct = decided and conclusion.decision in scenario.true_decisions
    abstain_ok = scenario.identifiable is False or scenario.kind == "pair"
    asked = [h for h in history if h[1].outcome != "refused"]
    return Episode(
        policy=policy.name,
        seed=scenario.seed,
        kind=scenario.kind,
        identifiable=scenario.identifiable,
        decided=decided,
        decision=conclusion.decision,
        confidence=conclusion.confidence,
        correct=correct,
        success=correct or (not decided and abstain_ok),
        probes=len(asked) + presence_challenges,
        effort_s=effort,
        people=len({a.participant_id for a, _ in asked}),
        hit_step_limit=hit_limit,
        failed=conclusion.failed,
        wall_s=effort,
        presence_challenges=presence_challenges,
    )


def run_parallel_episode(
    pack: DomainPack,
    model: CompiledModel,
    scenario: Scenario,
    policy: ParallelOurs,
    *,
    presence_checks: bool = False,
) -> Episode:
    """Our planner with up to ``policy.max_parallel`` questions in flight (the service's rule,
    ``pramana_engine.schedule``). Each answer arrives ``cost_s`` after its question was asked;
    a withdrawn question costs the person the time they had already spent on it."""
    engine = Engine(model, scenario.specs, policy.config)
    answers = Answers(pack, scenario)
    engine.observe(answers.report())
    now = effort = 0.0
    inflight: list[tuple[float, int, ProbeAction, float]] = []  # (done at, order, action, asked)
    asked: list[ProbeAction] = []
    withdrawn = 0
    presence_challenges = 0
    order = 0
    conclusion: Conclusion | None = None

    def launch(action: ProbeAction) -> None:
        nonlocal order
        costs = {(a.participant_id, a.probe_id, a.location_id): c for a, c in engine.menu()}
        cost = costs[(action.participant_id, action.probe_id, action.location_id)]
        engine.record_question(action.participant_id)
        inflight.append((now + cost, order, action, now))
        order += 1

    for _ in range(MAX_STEPS):
        sched = schedule(engine, [a for _, _, a, _ in inflight], policy.max_parallel)
        for i in sorted(sched.withdraw, reverse=True):
            _, _, _, t_ask = inflight.pop(i)
            effort += now - t_ask
            withdrawn += 1
        if sched.plan is not None:
            plan = sched.plan
            if plan.kind == PlanKind.ASK and plan.action is not None:
                launch(plan.action)
            else:
                decided = plan.kind == PlanKind.DECIDE
                conclusion = Conclusion(
                    plan.decision_class if decided else None,
                    float(plan.decision_probability or 0.0),
                )
                break
        for c in sched.ask:
            launch(c.action)
        if not inflight:
            break
        inflight.sort(key=lambda x: (x[0], x[1]))
        done_at, _, action, t_ask = inflight.pop(0)
        now = done_at
        effort += done_at - t_ask
        ev = answers.ask(action.participant_id, action.probe_id, action.location_id)
        observed = engine.observe(ev)
        if presence_checks:
            presence_challenges += _challenge_presence(engine, answers, ev, observed)
        asked.append(action)
    hit_limit = conclusion is None
    if conclusion is None:
        conclusion = Conclusion(None, engine.snapshot().map_decision_probability)
    decided = conclusion.decision is not None
    correct = decided and conclusion.decision in scenario.true_decisions
    abstain_ok = scenario.identifiable is False or scenario.kind == "pair"
    return Episode(
        policy=policy.name,
        seed=scenario.seed,
        kind=scenario.kind,
        identifiable=scenario.identifiable,
        decided=decided,
        decision=conclusion.decision,
        confidence=conclusion.confidence,
        correct=correct,
        success=correct or (not decided and abstain_ok),
        probes=len(asked) + presence_challenges,
        effort_s=effort,
        people=len({a.participant_id for a in asked}),
        hit_step_limit=hit_limit,
        wall_s=now,
        withdrawn=withdrawn,
        presence_challenges=presence_challenges,
    )


def _challenge_presence(engine: Engine, answers: Answers, ev: Evidence, observed: Any) -> int:
    """Resolve an engine-requested presence challenge using the simulated private token check."""
    token_id = engine.presence_challenge(ev, observed)
    if token_id is None:
        return 0
    engine.set_presence(ev.participant_id, ev.location_id, "pending")
    engine.record_question(ev.participant_id)
    passed = not answers.last_false_presence(ev.participant_id, ev.probe_id, ev.location_id)
    engine.set_presence(ev.participant_id, ev.location_id, "verified" if passed else "failed")
    return 1


def summarize(all_episodes: list[Episode]) -> dict[str, Any]:
    episodes = [e for e in all_episodes if not e.failed]
    n = len(episodes)
    decided = [e for e in episodes if e.decided]
    # Abstaining is the only safe answer when the people available cannot tell the causes
    # apart. Two-fault worlds are modelled since ADR 0008, so a correct pair decision is a
    # success there, not a missed abstention (abstaining on a pair is still acceptable).
    must_abstain = [e for e in episodes if e.identifiable is False]
    pairs = [e for e in episodes if e.kind == "pair"]
    should_decide = [e for e in episodes if e.identifiable is True]
    abstained = [e for e in episodes if not e.decided]
    return {
        "n": n,
        "failed_runs": len(all_episodes) - n,
        "success_rate": _rate(sum(e.success for e in episodes), n),
        "decision_accuracy": _rate(sum(e.correct for e in decided), len(decided)),
        "decided": len(decided),
        "accuracy_on_identifiable": _rate(
            sum(e.correct for e in should_decide), len(should_decide)
        ),
        "false_confidence_rate": _rate(
            sum(1 for e in episodes if e.decided and e.confidence >= 0.9 and not e.correct), n
        ),
        "abstention_recall": _rate(
            sum(1 for e in must_abstain if not e.decided), len(must_abstain)
        ),
        "accuracy_when_unidentifiable_but_decided": _rate(
            sum(e.correct for e in must_abstain if e.decided),
            sum(1 for e in must_abstain if e.decided),
        ),
        "pair_accuracy": _rate(sum(e.correct for e in pairs), len(pairs)),
        "abstention_precision": _rate(
            sum(1 for e in abstained if e.identifiable is False or e.kind == "pair"), len(abstained)
        ),
        "probes_mean": statistics.fmean(e.probes for e in episodes) if n else None,
        "probes_median": statistics.median(e.probes for e in episodes) if n else None,
        "effort_s_mean": statistics.fmean(e.effort_s for e in episodes) if n else None,
        "people_mean": statistics.fmean(e.people for e in episodes) if n else None,
        "hit_step_limit": sum(e.hit_step_limit for e in episodes),
        "wall_s_mean": statistics.fmean(e.wall_s for e in episodes) if n else None,
        "withdrawn_mean": statistics.fmean(e.withdrawn for e in episodes) if n else None,
        "presence_challenges_mean": (
            statistics.fmean(e.presence_challenges for e in episodes) if n else None
        ),
    }


def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


def paired_difference(
    a: list[Episode], b: list[Episode], field: str, resamples: int = 10_000, seed: int = 2026
) -> dict[str, float | None]:
    """Mean of (a - b) over the same scenarios, with a bootstrap 95% CI (None if no pairs)."""
    by_seed = {e.seed: e for e in b if not e.failed}
    a = [e for e in a if not e.failed]
    diffs = np.array(
        [
            float(getattr(e, field)) - float(getattr(by_seed[e.seed], field))
            for e in a
            if e.seed in by_seed
        ]
    )
    if len(diffs) == 0:  # e.g. every run of one policy failed: report no data, not NaN
        return {"mean": None, "ci95_low": None, "ci95_high": None, "n": 0.0}
    rng = np.random.default_rng(seed)
    boots = rng.choice(diffs, size=(resamples, len(diffs)), replace=True).mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {
        "mean": float(diffs.mean()),
        "ci95_low": float(lo),
        "ci95_high": float(hi),
        "n": float(len(diffs)),
    }


def to_rows(episodes: list[Episode]) -> list[dict[str, Any]]:
    return [asdict(e) for e in episodes]
