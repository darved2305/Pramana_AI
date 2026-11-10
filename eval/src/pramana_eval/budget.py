"""Fixed question and matched-effort budget evaluation."""

from __future__ import annotations

import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from pramana_contracts import PlanKind
from pramana_domain import DomainPack
from pramana_engine import CompiledModel, Engine

from .policies import Conclusion, History, Step
from .scenarios import Answers, Scenario


class BudgetPolicy(Protocol):
    name: str
    config: Any

    def start(self, scenario: Scenario, report: Any = None) -> None: ...
    def next_at_budget(self, engine: Engine, history: History) -> Step: ...


@dataclass(frozen=True)
class BudgetOutcome:
    policy: str
    seed: int
    kind: str
    questions: int
    effort_s: float
    decision: str | None
    confidence: float
    correct: bool
    success: bool
    abstained: bool


def run_trajectory(
    pack: DomainPack,
    model: CompiledModel,
    scenario: Scenario,
    policy: BudgetPolicy,
    max_questions: int,
) -> list[BudgetOutcome]:
    """Run the policy's selector for a fixed number of questions, ignoring its stop threshold."""
    engine = Engine(model, scenario.specs, policy.config)
    answers = Answers(pack, scenario)
    report = answers.report()
    engine.observe(report)
    policy.start(scenario, report)
    history: History = []
    effort = 0.0
    points: list[BudgetOutcome] = []

    def capture(questions: int) -> None:
        plan = engine.plan()
        snap = engine.snapshot()
        decision = plan.decision_class if plan.kind == PlanKind.DECIDE else None
        confidence = float(plan.decision_probability or snap.map_decision_probability)
        correct = decision is not None and decision in scenario.true_decisions
        abstained = plan.kind == PlanKind.ABSTAIN
        success = correct or (abstained and scenario.identifiable is False)
        points.append(
            BudgetOutcome(
                policy.name,
                scenario.seed,
                scenario.kind,
                questions,
                effort,
                decision,
                confidence,
                correct,
                success,
                abstained,
            )
        )

    capture(0)
    for question in range(1, max_questions + 1):
        step = policy.next_at_budget(engine, history)
        if isinstance(step, Conclusion):
            break
        costs = {
            (action.participant_id, action.probe_id, action.location_id): cost
            for action, cost in engine.menu()
        }
        key = (step.participant_id, step.probe_id, step.location_id)
        cost = costs.get(key)
        if cost is None:
            break
        effort += cost
        engine.record_question(step.participant_id)
        ev = answers.ask(*key)
        engine.observe(ev)
        history.append((step, ev))
        capture(question)
    return points


def _at_questions(points: list[BudgetOutcome], budget: int) -> BudgetOutcome:
    return max((p for p in points if p.questions <= budget), key=lambda p: p.questions)


def _at_effort(points: list[BudgetOutcome], budget: float) -> BudgetOutcome:
    eligible = [p for p in points if p.effort_s <= budget]
    return max(eligible, key=lambda p: (p.effort_s, p.questions))


def _interval(values: list[float], seed: int, resamples: int = 2000) -> tuple[float, float]:
    if not values:
        return (math.nan, math.nan)
    data = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    samples = rng.choice(data, size=(resamples, len(data)), replace=True).mean(axis=1)
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return float(lo), float(hi)


def _metric(points: list[BudgetOutcome], seed: int) -> dict[str, Any]:
    n = len(points)
    successes = [float(p.success) for p in points]
    decided = [p for p in points if p.decision is not None]
    correct = [float(p.correct) for p in decided]
    success_lo, success_hi = _interval(successes, seed)
    accuracy_lo, accuracy_hi = _interval(correct, seed + 1)
    return {
        "n": n,
        "success": sum(successes) / n if n else None,
        "success_ci95_low": success_lo if n else None,
        "success_ci95_high": success_hi if n else None,
        "accuracy": sum(correct) / len(correct) if correct else None,
        "accuracy_n": len(correct),
        "accuracy_ci95_low": accuracy_lo if correct else None,
        "accuracy_ci95_high": accuracy_hi if correct else None,
    }


def budget_curves(
    trajectories: dict[str, list[list[BudgetOutcome]]], max_questions: int
) -> dict[str, list[dict[str, Any]]]:
    """Aggregate paired scenario trajectories on shared question and effort grids."""
    max_effort = max(
        (points[-1].effort_s for runs in trajectories.values() for points in runs), default=60
    )
    effort_grid = list(range(0, max(60, math.ceil(max_effort / 60) * 60) + 1, 60))
    output: dict[str, list[dict[str, Any]]] = {"questions": [], "effort_s": []}
    for policy_index, (name, runs) in enumerate(trajectories.items()):
        for budget_type, grid in (
            ("questions", range(1, max_questions + 1)),
            ("effort_s", effort_grid),
        ):
            for j, budget in enumerate(grid):
                chosen = [
                    _at_questions(points, budget)
                    if budget_type == "questions"
                    else _at_effort(points, budget)
                    for points in runs
                ]
                output[budget_type].append(
                    {
                        "policy": name,
                        "budget": budget,
                        **_metric(chosen, 730_001 + policy_index * 100_000 + j),
                    }
                )
    return output


def calibration(episodes: list[dict[str, Any]], bins: int = 10) -> list[dict[str, Any]]:
    """Reliability bins over decided outcomes; counts and denominators are explicit."""
    rows: list[dict[str, Any]] = []
    decided = [e for e in episodes if e["decided"] and not e["failed"]]
    for i in range(bins):
        low, high = i / bins, (i + 1) / bins
        members = [
            e
            for e in decided
            if low <= e["confidence"] < high or (i == bins - 1 and e["confidence"] == 1)
        ]
        rows.append(
            {
                "bin": i + 1,
                "low": low,
                "high": high,
                "count": len(members),
                "mean_confidence": sum(e["confidence"] for e in members) / len(members)
                if members
                else None,
                "accuracy": sum(bool(e["correct"]) for e in members) / len(members)
                if members
                else None,
                "denominator": len(decided),
            }
        )
    return rows


def stratum_outcomes(episodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for kind in ("single", "pair", "no_fault", "access_limited"):
        members = [e for e in episodes if e["kind"] == kind and not e["failed"]]
        abstained = [e for e in members if not e["decided"]]
        false = [e for e in members if e["decided"] and e["confidence"] >= 0.9 and not e["correct"]]
        output[kind] = {
            "n": len(members),
            "false_confidence_n": len(false),
            "false_confidence_rate": len(false) / len(members) if members else None,
            "abstentions": len(abstained),
            "abstention_rate": len(abstained) / len(members) if members else None,
            "justified_abstentions": sum(e.get("identifiable") is False for e in abstained),
            "unknown_identifiability_abstentions": sum(
                e.get("identifiable") is None for e in abstained
            ),
        }
    return output


def write_budget_artifacts(out: Path, curves: dict[str, list[dict[str, Any]]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "budget-curves.json").write_text(json.dumps(curves, indent=2) + "\n", encoding="utf-8")
    for budget_type, points in curves.items():
        for metric in ("success", "accuracy"):
            _write_svg(out / f"{budget_type}-{metric}.svg", points, budget_type, metric)


def write_calibration_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    """Render a deterministic reliability diagram with the count printed at each bin."""
    left, top, size = 70, 35, 340
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="440" viewBox="0 0 480 440">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="70" y="22" font-family="sans-serif" font-size="16">Reliability diagram</text>',
        f'<path d="M {left} {top} V {top + size} H {left + size}" fill="none" stroke="#555"/>',
        (
            f'<path d="M {left} {top + size} L {left + size} {top}" fill="none" '
            'stroke="#999" stroke-dasharray="4 4"/>'
        ),
    ]
    for row in rows:
        confidence, accuracy = row["mean_confidence"], row["accuracy"]
        if confidence is None or accuracy is None:
            continue
        x = left + float(confidence) * size
        y = top + (1 - float(accuracy)) * size
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="#155eef"/>')
        lines.append(
            f'<text x="{x + 7:.2f}" y="{y - 5:.2f}" font-family="sans-serif" font-size="10">'
            f"n={row['count']}</text>"
        )
    lines += [
        (
            '<text x="240" y="420" text-anchor="middle" font-family="sans-serif" '
            'font-size="12">Mean confidence</text>'
        ),
        "</svg>",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _write_svg(path: Path, points: list[dict[str, Any]], x_name: str, metric: str) -> None:
    colors = {
        "E_ours": "#155eef",
        "D_greedy_entropy": "#e05d44",
        "A_checklist": "#159570",
        "C_random": "#a35bd4",
    }
    width, height, left, top, plot_w, plot_h = 720, 440, 70, 45, 610, 330
    max_x = max((float(p["budget"]) for p in points), default=1.0) or 1.0
    lines = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        (
            f'<text x="{left}" y="25" font-family="sans-serif" font-size="16">'
            f"{html.escape(metric.title())} by {html.escape(x_name)}</text>"
        ),
        f'<path d="M {left} {top} V {top + plot_h} H {left + plot_w}" fill="none" stroke="#555"/>',
    ]
    for tick in range(0, 6):
        y = top + plot_h * tick / 5
        lines.append(f'<path d="M {left} {y:.1f} H {left + plot_w}" stroke="#ddd"/>')
        lines.append(
            f'<text x="{left - 28}" y="{y + 4:.1f}" font-family="sans-serif" '
            f'font-size="11">{1 - tick / 5:.1f}</text>'
        )
    for index, (name, color) in enumerate(colors.items()):
        rows = [p for p in points if p["policy"] == name and p[metric] is not None]
        if not rows:
            continue
        coords = []
        for p in rows:
            x = left + float(p["budget"]) / max_x * plot_w
            y = top + (1 - float(p[metric])) * plot_h
            coords.append(f"{x:.2f},{y:.2f}")
            low = p[f"{metric}_ci95_low"]
            high = p[f"{metric}_ci95_high"]
            if low is not None and high is not None:
                y_low = top + (1 - float(low)) * plot_h
                y_high = top + (1 - float(high)) * plot_h
                lines.append(
                    f'<path d="M {x:.2f} {y_high:.2f} V {y_low:.2f} '
                    f"M {x - 3:.2f} {y_high:.2f} H {x + 3:.2f} "
                    f'M {x - 3:.2f} {y_low:.2f} H {x + 3:.2f}" stroke="{color}"/>'
                )
        lines.append(
            f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        lx = left + index * 145
        lines.append(
            f'<text x="{lx}" y="{top + plot_h + 45}" font-family="sans-serif" '
            f'font-size="11" fill="{color}">{html.escape(name)}</text>'
        )
    lines.append(
        f'<text x="{left + plot_w / 2}" y="{height - 12}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="12">{html.escape(x_name)}</text>'
    )
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
