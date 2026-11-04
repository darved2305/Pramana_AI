"""Policies compared in the benchmark (docs/EVALUATION.md §3).

Every policy sees the same feasible action menu (``Engine.menu()``) and the same simulated
answers. A, C, D and E read their final decision and confidence from the same Bayesian belief;
B (the LLM) states its own.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from pramana_contracts import PlanKind, ProbeAction
from pramana_engine import Engine, EngineConfig, Evidence

from .scenarios import Scenario


@dataclass(frozen=True)
class Conclusion:
    decision: str | None
    """``None`` means the policy abstained."""
    confidence: float
    failed: bool = False
    """The policy could not run (e.g. the LLM provider failed). Reported separately and
    excluded from that policy's scores, never counted as an abstention."""


Step = ProbeAction | Conclusion
History = list[tuple[ProbeAction, Evidence]]


class Policy(Protocol):
    name: str
    config: EngineConfig

    def start(self, scenario: Scenario, report: Evidence | None = None) -> None: ...
    def next(self, engine: Engine, history: History) -> Step: ...


def _engine_conclusion(engine: Engine) -> Conclusion:
    plan = engine.plan()
    if plan.kind == PlanKind.DECIDE:
        return Conclusion(plan.decision_class, float(plan.decision_probability or 0.0))
    return Conclusion(None, float(plan.decision_probability or 0.0))


class Ours:
    """E: decision-focused value of information per unit effort, two-step stopping rule."""

    def __init__(self, name: str = "E_ours", config: EngineConfig | None = None) -> None:
        self.name = name
        self.config = config or EngineConfig()

    def start(self, scenario: Scenario, report: Evidence | None = None) -> None:
        pass

    def next(self, engine: Engine, history: History) -> Step:
        plan = engine.plan()
        if plan.kind == PlanKind.ASK and plan.action is not None:
            return plan.action
        return _engine_conclusion(engine)


def greedy_entropy() -> Ours:
    """D: information about the cause only, effort ignored, same stopping rule."""
    return Ours("D_greedy_entropy", EngineConfig(decision_focus=False, cost_aware=False))


class RandomFeasible:
    """C: a random feasible question each step, with our belief updates and stopping rule."""

    name = "C_random"

    def __init__(self) -> None:
        self.config = EngineConfig()
        self._rng = random.Random(0)

    def start(self, scenario: Scenario, report: Evidence | None = None) -> None:
        self._rng = random.Random(scenario.seed * 7919 + 1)

    def next(self, engine: Engine, history: History) -> Step:
        plan = engine.plan()
        menu = engine.menu()
        if plan.kind != PlanKind.ASK or not menu:
            return _engine_conclusion(engine)
        return self._rng.choice(menu)[0]


# A reasonable standard operating procedure a campus network admin might write: check the
# reporter's phone and surroundings, then other people, then the closets, then the panel.
CHECKLIST: list[tuple[str, str]] = [
    ("wifi_status", "reporter"),
    ("corridor_lights", "reporter"),
    ("web_by_ip", "reporter"),
    ("internet_works", "others"),
    ("wifi_status", "others"),
    ("switch_leds", "IDF2"),
    ("wan_led", "IDF1"),
    ("switch_leds", "IDF1"),
    ("breaker_c2_7", "DB_C2_PANEL"),
    ("ap_light", "anywhere"),
]


class Checklist:
    """A: walk the fixed checklist; stop when the shared belief is confident or it runs out."""

    name = "A_checklist"

    def __init__(self) -> None:
        self.config = EngineConfig()
        self._reporter = ""

    def start(self, scenario: Scenario, report: Evidence | None = None) -> None:
        self._reporter = scenario.reporter

    def next(self, engine: Engine, history: History) -> Step:
        snap = engine.snapshot()
        if snap.map_decision_probability >= self.config.tau_hi:
            return Conclusion(snap.map_decision, snap.map_decision_probability)
        menu = [a for a, _ in engine.menu()]
        for probe_id, who in CHECKLIST:
            for a in menu:
                if a.probe_id != probe_id:
                    continue
                if who == "reporter" and a.participant_id != self._reporter:
                    continue
                if who == "others" and a.participant_id == self._reporter:
                    continue
                if who not in ("reporter", "others", "anywhere") and a.location_id != who:
                    continue
                return a
        if snap.map_decision_probability >= self.config.tau_lo:
            return Conclusion(snap.map_decision, snap.map_decision_probability)
        return Conclusion(None, snap.map_decision_probability)


def baseline_policies() -> list[Policy]:
    return [Ours(), Checklist(), RandomFeasible(), greedy_entropy()]


def ablations() -> list[Policy]:
    return [
        Ours("E-no_decision_focus", EngineConfig(decision_focus=False)),
        Ours("E-no_cost", EngineConfig(cost_aware=False)),
    ]
