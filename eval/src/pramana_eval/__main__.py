"""Run the benchmark: ``python -m pramana_eval --n 500 --out <dir> [--policies E,A,C,D]``.

Seeds 0-9,999 are for development; 10,000+ are reserved for the final, reported run
(docs/EVALUATION.md §9: never tune on the reporting seeds).
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from pramana_domain import load_pack
from pramana_engine import compile_pack

from .budget import (
    BudgetOutcome,
    BudgetPolicy,
    budget_curves,
    run_trajectory,
    write_budget_artifacts,
    write_calibration_svg,
)
from .policies import Policy, ablations, baseline_policies
from .runner import Episode, paired_difference, run_episode, summarize, to_rows
from .scenarios import generate
from .statistics import holm, mcnemar_exact, wilcoxon_signed_rank


def _git_sha() -> str:
    """Commit of the code being run; "-dirty" if tracked files were modified."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty else "")


SHORT = {
    "E": "E_ours",
    "A": "A_checklist",
    "C": "C_random",
    "D": "D_greedy_entropy",
    "P2": "E_parallel2",
    "P3": "E_parallel3",
}

PRIMARY = ("A_checklist", "B_llm", "C_random", "D_greedy_entropy", "E_parallel3")


def primary_tests(results: dict[str, list[Episode]]) -> dict[str, Any]:
    """The five registered comparisons, corrected separately for each outcome.

    Missing comparisons occupy a family slot with p=1, so omitting B or K=3 cannot
    make the remaining tests more permissive. Only paired completed episodes count.
    """
    output: dict[str, Any] = {
        "success_definition": (
            "correct decision or abstention where identifiability is false; "
            "pair abstention is not success"
        )
    }
    ours = {e.seed: e for e in results.get("E_ours", []) if not e.failed}
    for field in ("success", "probes", "effort_s"):
        entries: dict[str, Any] = {}
        raw: list[float] = []
        for name in PRIMARY:
            paired = [
                (ours[e.seed], e) for e in results.get(name, []) if not e.failed and e.seed in ours
            ]
            stat_field = "honest_success" if field == "success" else field
            a = [float(getattr(x, stat_field)) for x, _ in paired]
            b = [float(getattr(y, stat_field)) for _, y in paired]
            p = (
                (mcnemar_exact(a, b) if field == "success" else wilcoxon_signed_rank(a, b))
                if paired
                else None
            )
            raw.append(p if p is not None else 1.0)
            entries[name] = {"n": len(paired), "p": p, "p_holm": None}
        for name, adjusted in zip(PRIMARY, holm(raw), strict=True):
            if entries[name]["p"] is not None:
                entries[name]["p_holm"] = adjusted
        output[field] = entries
    return output


def build_policies(
    names: list[str], provider: str, model: str | None, rpd: int | None = None
) -> list[Policy]:
    available: dict[str, Policy] = {p.name: p for p in [*baseline_policies(), *ablations()]}
    chosen: list[Policy] = []
    for n in names:
        if n == "B":
            from pramana_core.llm import PROVIDERS, LlmClient, ProviderLimits

            from .llm_policy import LlmPolicy

            limits = None
            if rpd is not None:
                base = PROVIDERS[provider][2]
                limits = ProviderLimits(base.requests_per_min, base.tokens_per_min, rpd)
            client = LlmClient(provider, model, cache_dir=Path(".cache/llm"), limits=limits)
            chosen.append(LlmPolicy(client, load_pack("campus_block_c")))
        elif SHORT.get(n, n) in available:
            chosen.append(available[SHORT.get(n, n)])
        else:
            sys.exit(f"unknown policy {n}; choose from {sorted(SHORT)}, B, or {sorted(available)}")
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--policies", default="E,A,C,D,E-no_decision_focus,E-no_cost")
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget-curves", action="store_true")
    ap.add_argument("--budget-questions", type=int, default=10)
    ap.add_argument("--llm-provider", default="groq", choices=["groq", "gemini"])
    ap.add_argument("--llm-model", default=None)
    ap.add_argument(
        "--llm-rpd",
        type=int,
        default=None,
        help="local requests/day cap; a provider quota error still stops the run",
    )
    ap.add_argument(
        "--llm-n",
        type=int,
        default=100,
        help="run the LLM policy on the first N scenarios only (free-tier quota)",
    )
    args = ap.parse_args()

    code_version = _git_sha()  # captured before running, not after
    pack = load_pack("campus_block_c")
    model = compile_pack(pack)
    policies = build_policies(
        args.policies.split(","), args.llm_provider, args.llm_model, args.llm_rpd
    )
    seeds = range(args.seed_start, args.seed_start + args.n)
    scenarios = [generate(pack, model, s) for s in seeds]
    results: dict[str, list[Episode]] = {}
    start = time.perf_counter()
    for policy in policies:
        # The LLM runs on a paired subset; comparisons use only scenarios both policies ran.
        subset = scenarios[: args.llm_n] if policy.name.startswith("B_") else scenarios
        results[policy.name] = [run_episode(pack, model, sc, policy) for sc in subset]
        print(f"{policy.name:24s} done ({time.perf_counter() - start:.0f} s)", flush=True)

    ours = results.get("E_ours")
    summary: dict[str, Any] = {
        "git_sha": code_version,
        "python": platform.python_version(),
        "seeds": [args.seed_start, args.seed_start + args.n - 1],
        "scenario_mix": {
            k: sum(1 for s in scenarios if s.kind == k)
            for k in ("single", "pair", "no_fault", "access_limited")
        },
        "scenario_manifest": {
            "total": len(scenarios),
            "strata": {
                k: sum(1 for s in scenarios if s.kind == k)
                for k in ("single", "pair", "no_fault", "access_limited")
            },
            "behaviors": {
                "implemented": [
                    "single_fault",
                    "pair_fault",
                    "no_fault",
                    "access_limited",
                    "sampled_participant_reliability",
                    "hedging",
                    "lay_hearsay",
                ],
                "proposed_not_in_this_generator": [
                    "unmodelled_fault",
                    "changing_world",
                    "map_drift",
                    "correlated_error",
                    "stale_answer",
                    "call_drop",
                    "generic_adversary",
                ],
            },
        },
        "policies": {name: summarize(eps) for name, eps in results.items()},
        "paired_vs_E": {},
        "primary_tests": primary_tests(results),
    }
    if ours is not None:
        for name, eps in results.items():
            if name == "E_ours":
                continue
            summary["paired_vs_E"][name] = {
                f: paired_difference(ours, eps, f)
                for f in ("success", "probes", "effort_s", "wall_s")
            }
    out = Path(args.out)
    if args.budget_curves:
        required = {"E_ours", "A_checklist", "C_random", "D_greedy_entropy"}
        chosen = {policy.name: policy for policy in policies}
        missing = required - chosen.keys()
        if missing:
            ap.error(
                "--budget-curves requires E,A,C,D policies; missing " + ",".join(sorted(missing))
            )
        budget_results: dict[str, list[list[BudgetOutcome]]] = {}
        for name in ("E_ours", "D_greedy_entropy", "A_checklist", "C_random"):
            policy = chosen[name]
            budget_results[name] = [
                run_trajectory(
                    pack, model, scenario, cast(BudgetPolicy, policy), args.budget_questions
                )
                for scenario in scenarios
            ]
        summary["budget_questions_max"] = args.budget_questions
        summary["budget_curves"] = budget_curves(budget_results, args.budget_questions)
        write_budget_artifacts(out, summary["budget_curves"])
        with (out / "budget-episodes.csv").open("w", newline="", encoding="utf-8") as fh:
            rows = [
                asdict(point)
                for runs in budget_results.values()
                for trajectory in runs
                for point in trajectory
            ]
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    out.mkdir(parents=True, exist_ok=True)
    if "E_ours" in summary["policies"]:
        write_calibration_svg(
            out / "reliability-diagram.svg", summary["policies"]["E_ours"]["calibration"]
        )
    (out / "scenario-manifest.json").write_text(
        json.dumps(summary["scenario_manifest"], indent=2) + "\n", encoding="utf-8"
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (out / "episodes.csv").open("w", newline="", encoding="utf-8") as fh:
        rows = [r for eps in results.values() for r in to_rows(eps)]
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "report.md").write_text(render(summary), encoding="utf-8")
    print(render(summary))


def _fmt(x: Any, pct: bool = False) -> str:
    if x is None:
        return "-"
    return f"{100 * x:.1f}%" if pct else f"{x:.2f}"


def render(summary: dict[str, Any]) -> str:
    lines = [
        "# Benchmark report (generated; do not edit)",
        "",
        f"Commit `{summary['git_sha']}`, seeds {summary['seeds'][0]}-{summary['seeds'][1]}, "
        f"scenario mix {summary['scenario_mix']}.",
        "",
        "| Policy | Completed episodes | Excluded failed runs | Success | Accuracy (decided) "
        "| Honest success | Accuracy (identifiable) | False confidence "
        "| Abstention recall (unidentifiable) | Pair accuracy | Probes (mean) | Effort s (mean) "
        "| People | Time to conclusion s (mean) | Withdrawn (mean) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, m in summary["policies"].items():
        lines.append(
            f"| {name} | {m['n']} | {m['failed_runs']} | {_fmt(m['success_rate'], True)} "
            f"| {_fmt(m['honest_success_rate'], True)} "
            f"| {_fmt(m['decision_accuracy'], True)} "
            f"| {_fmt(m['accuracy_on_identifiable'], True)} "
            f"| {_fmt(m['false_confidence_rate'], True)} | {_fmt(m['abstention_recall'], True)} "
            f"| {_fmt(m['pair_accuracy'], True)} "
            f"| {_fmt(m['probes_mean'])} | {_fmt(m['effort_s_mean'])} | {_fmt(m['people_mean'])} "
            f"| {_fmt(m.get('wall_s_mean'))} | {_fmt(m.get('withdrawn_mean'))} |"
        )
    if summary["policies"]:
        lines += [
            "",
            "Calibration and false-confidence counts by policy:",
            "",
            "| Policy | Bin | Count / decided n | Mean confidence | Accuracy |",
            "|---|---:|---:|---:|---:|",
        ]
        for name, m in summary["policies"].items():
            for row in m.get("calibration", []):
                lines.append(
                    f"| {name} | {row['bin']} | {row['count']} / {row['denominator']} | "
                    f"{_fmt(row['mean_confidence'], True)} | {_fmt(row['accuracy'], True)} |"
                )
        lines += [
            "",
            "False-confidence and abstention by scenario stratum:",
            "",
            "| Policy | Stratum | n | False confidence (count / rate) | Abstained | "
            "Justified abstentions | Unknown identifiability abstentions |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for name, m in summary["policies"].items():
            for kind, row in m.get("strata", {}).items():
                lines.append(
                    f"| {name} | {kind} | {row['n']} | {row['false_confidence_n']} / "
                    f"{_fmt(row['false_confidence_rate'], True)} | {row['abstentions']} | "
                    f"{row['justified_abstentions']} | "
                    f"{row['unknown_identifiability_abstentions']} |"
                )
    lines += [
        "",
        "Pair and abstention outcomes (historical success above retains its original definition):",
        "",
        "| Policy | Pair episodes | First useful action | Full pair resolution | "
        "Justified abstentions | Abstentions with unknown identifiability |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in summary["policies"].items():
        lines.append(
            f"| {name} | {m['pair_outcome_denominator']} | "
            f"{_fmt(m['pair_first_useful_action_rate'], True)} | not measured | "
            f"{m['justified_abstentions']} | {m['abstentions_with_unknown_identifiability']} |"
        )
    lines += ["", "Paired differences, E minus each policy (bootstrap 95% CI):", ""]
    for name, diffs in summary["paired_vs_E"].items():
        parts = [
            f"{f}: {d['mean']:+.3f} [{d['ci95_low']:+.3f}, {d['ci95_high']:+.3f}]"
            if d["mean"] is not None
            else f"{f}: no paired data"
            for f, d in diffs.items()
        ]
        lines.append(f"- vs {name}: " + "; ".join(parts))
    if "primary_tests" in summary:
        lines += [
            "",
            "Registered paired tests (Holm across five comparisons per outcome):",
            f"Success definition: {summary['primary_tests']['success_definition']}.",
            "",
            "| Outcome | Comparison | Paired n | p | Holm p |",
            "|---|---|---|---|---|",
        ]
        for field, comparisons in summary["primary_tests"].items():
            if field == "success_definition":
                continue
            for name, result in comparisons.items():
                p = "-" if result["p"] is None else f"{result['p']:.6g}"
                adjusted = "-" if result["p_holm"] is None else f"{result['p_holm']:.6g}"
                lines.append(f"| {field} | E vs {name} | {result['n']} | {p} | {adjusted} |")
    if "budget_curves" in summary:
        lines += ["", "Matched-budget curves (SVG files alongside this report):", ""]
        for budget_type, points in summary["budget_curves"].items():
            lines.append(
                f"- {budget_type}: {len(points)} policy-budget estimates with "
                "scenario bootstrap intervals"
            )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
