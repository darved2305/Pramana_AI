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
from pathlib import Path
from typing import Any

from pramana_domain import load_pack
from pramana_engine import compile_pack

from .policies import Policy, ablations, baseline_policies
from .runner import Episode, paired_difference, run_episode, summarize, to_rows
from .scenarios import generate


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
    ap.add_argument(
        "--false-presence-rate",
        type=float,
        default=0.0,
        help=(
            "per restricted or moved question chance that the simulated guard "
            "falsely claims to be on site"
        ),
    )
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
    scenarios = [
        generate(pack, model, s, false_presence_rate=args.false_presence_rate) for s in seeds
    ]
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
        "presence_adversary_scenarios": sum(
            1 for scenario in scenarios if scenario.presence_adversary_id is not None
        ),
        "false_presence_rate": args.false_presence_rate,
        "policies": {name: summarize(eps) for name, eps in results.items()},
        "paired_vs_E": {},
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
    out.mkdir(parents=True, exist_ok=True)
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
        f"False-presence rate {summary['false_presence_rate']:.2f}; "
        f"scenarios with an adversary: {summary['presence_adversary_scenarios']}.",
        "",
        "| Policy | Success | Accuracy (decided) | Accuracy (identifiable) | False confidence "
        "| Abstention recall (unidentifiable) | Pair accuracy | Probes (mean) | Presence checks "
        "(mean) | Effort s (mean) | People | Time to conclusion s (mean) | Withdrawn (mean) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, m in summary["policies"].items():
        lines.append(
            f"| {name} | {_fmt(m['success_rate'], True)} | {_fmt(m['decision_accuracy'], True)} "
            f"| {_fmt(m['accuracy_on_identifiable'], True)} "
            f"| {_fmt(m['false_confidence_rate'], True)} | {_fmt(m['abstention_recall'], True)} "
            f"| {_fmt(m['pair_accuracy'], True)} "
            f"| {_fmt(m['probes_mean'])} | {_fmt(m['presence_challenges_mean'])} "
            f"| {_fmt(m['effort_s_mean'])} | {_fmt(m['people_mean'])} "
            f"| {_fmt(m.get('wall_s_mean'))} | {_fmt(m.get('withdrawn_mean'))} |"
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
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
