"""Compare presence challenges with an adversarial simulated guard.

Run with ``python -m pramana_eval.presence_eval --n 200 --seed-start 20000
--false-presence-rate 0.3 --out eval/reports/presence-YYYY-MM-DD``.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from pramana_domain import load_pack
from pramana_engine import compile_pack

from .policies import Ours
from .runner import Episode, paired_difference, run_episode, summarize, to_rows
from .scenarios import generate


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed-start", type=int, default=20_000)
    ap.add_argument("--false-presence-rate", type=float, default=0.3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.n < 1:
        ap.error("--n must be positive")
    if not 0.0 <= args.false_presence_rate <= 1.0:
        ap.error("--false-presence-rate must be between 0 and 1")

    code_version = _git_sha()
    pack = load_pack("campus_block_c")
    model = compile_pack(pack)
    scenarios = [
        generate(pack, model, seed, false_presence_rate=args.false_presence_rate)
        for seed in range(args.seed_start, args.seed_start + args.n)
    ]
    results: dict[str, list[Episode]] = {}
    start = time.perf_counter()
    for name, checks_on in (("E_presence_checks", True), ("E_no_presence_checks", False)):
        policy = Ours(name)
        results[name] = [
            run_episode(pack, model, scenario, policy, presence_checks=checks_on)
            for scenario in scenarios
        ]
        print(f"{name:24s} done ({time.perf_counter() - start:.0f} s)", flush=True)

    with_checks = results["E_presence_checks"]
    without_checks = results["E_no_presence_checks"]
    summary: dict[str, Any] = {
        "git_sha": code_version,
        "python": platform.python_version(),
        "seeds": [args.seed_start, args.seed_start + args.n - 1],
        "scenario_mix": {
            kind: sum(1 for scenario in scenarios if scenario.kind == kind)
            for kind in ("single", "pair", "no_fault", "access_limited")
        },
        "presence_adversary_scenarios": sum(
            scenario.presence_adversary_id is not None for scenario in scenarios
        ),
        "false_presence_rate": args.false_presence_rate,
        "policies": {name: summarize(episodes) for name, episodes in results.items()},
        "paired_presence_checks_minus_ablation": {
            field: paired_difference(with_checks, without_checks, field)
            for field in ("success", "probes", "effort_s", "wall_s")
        },
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    rows = [row for episodes in results.values() for row in to_rows(episodes)]
    with (out / "episodes.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = render(summary)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(report)


def _fmt(value: Any, percent: bool = False) -> str:
    if value is None:
        return "-"
    return f"{100 * value:.1f}%" if percent else f"{value:.2f}"


def render(summary: dict[str, Any]) -> str:
    lines = [
        "# Presence challenge benchmark (generated; do not edit)",
        "",
        f"Commit `{summary['git_sha']}`, seeds {summary['seeds'][0]}-"
        f"{summary['seeds'][1]}, scenario mix {summary['scenario_mix']}.",
        f"False-presence rate {summary['false_presence_rate']:.2f}; scenarios with an adversary: "
        f"{summary['presence_adversary_scenarios']}.",
        "",
        "The enabled policy applies the engine's presence challenge and resolves it with the "
        "simulated private token check. The ablation uses the same scenarios and answers without "
        "requesting or applying presence checks.",
        "",
        "| Policy | Success | Decision accuracy | Accuracy on identifiable | Presence checks "
        "(mean) | Probes (mean) |",
        "|---|---|---|---|---|---|",
    ]
    for name, metrics in summary["policies"].items():
        lines.append(
            f"| {name} | {_fmt(metrics['success_rate'], True)} "
            f"| {_fmt(metrics['decision_accuracy'], True)} "
            f"| {_fmt(metrics['accuracy_on_identifiable'], True)} "
            f"| {_fmt(metrics['presence_challenges_mean'])} "
            f"| {_fmt(metrics['probes_mean'])} |"
        )
    lines += ["", "Paired difference, enabled checks minus ablation:", ""]
    for field, difference in summary["paired_presence_checks_minus_ablation"].items():
        if difference["mean"] is None:
            value = "no paired data"
        else:
            value = (
                f"{difference['mean']:+.3f} "
                f"[{difference['ci95_low']:+.3f}, {difference['ci95_high']:+.3f}]"
            )
        lines.append(f"- {field}: {value}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
