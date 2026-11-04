"""Run policies over scenarios and compute the metrics of docs/EVALUATION.md §4."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from pramana_domain import DomainPack
from pramana_engine import CompiledModel, Engine, Evidence

from .policies import Conclusion, History, Policy
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


def run_episode(
    pack: DomainPack, model: CompiledModel, scenario: Scenario, policy: Policy
) -> Episode:
    engine = Engine(model, scenario.specs, policy.config)
    answers = Answers(pack, scenario)
    report = answers.report()
    engine.observe(report)
    policy.start(scenario, report)
    history: History = []
    effort = 0.0
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
        engine.observe(ev)
        history.append((step, ev))
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
        probes=len(asked),
        effort_s=effort,
        people=len({a.participant_id for a, _ in asked}),
        hit_step_limit=hit_limit,
        failed=conclusion.failed,
    )


def summarize(all_episodes: list[Episode]) -> dict[str, Any]:
    episodes = [e for e in all_episodes if not e.failed]
    n = len(episodes)
    decided = [e for e in episodes if e.decided]
    abstain_ok = [e for e in episodes if e.identifiable is False or e.kind == "pair"]
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
        "abstention_recall": _rate(sum(1 for e in abstain_ok if not e.decided), len(abstain_ok)),
        "abstention_precision": _rate(
            sum(1 for e in abstained if e.identifiable is False or e.kind == "pair"), len(abstained)
        ),
        "probes_mean": statistics.fmean(e.probes for e in episodes) if n else None,
        "probes_median": statistics.median(e.probes for e in episodes) if n else None,
        "effort_s_mean": statistics.fmean(e.effort_s for e in episodes) if n else None,
        "people_mean": statistics.fmean(e.people for e in episodes) if n else None,
        "hit_step_limit": sum(e.hit_step_limit for e in episodes),
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
