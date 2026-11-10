"""docs/EVALUATION.md results are generated from a summary and never drift from it."""

from __future__ import annotations

import json
from pathlib import Path

from pramana_eval import evaluation_doc

ROOT = Path(__file__).resolve().parents[2]
RC1 = ROOT / "eval" / "reports" / "benchmark-2026-11-07-rc1"
HELDOUT = ROOT / "eval" / "reports" / "benchmark-2026-11-10-heldout"


def test_the_committed_results_match_the_frozen_heldout_summary() -> None:
    assert evaluation_doc.main([str(HELDOUT), "--check"]) == 0


def test_every_policy_number_comes_from_the_summary() -> None:
    summary = json.loads((HELDOUT / "summary.json").read_text(encoding="utf-8"))
    block = evaluation_doc.render(summary, "x")
    assert "Source: `x/summary.json`" in block
    rows = block.splitlines()
    for i, line in enumerate(rows):
        if line.startswith("| Policy |"):
            assert line.count("|") == rows[i + 1].count("|")
    for key, p in summary["policies"].items():
        row = (
            f"| {evaluation_doc.LABEL.get(key, key)} | {p['n']} ({p['failed_runs']}) | "
            f"{p['success_rate'] * 100:.1f}% | {p['honest_success_rate'] * 100:.1f}% |"
        )
        assert row in block
    assert summary["git_sha"] in block
    assert summary["protocol"]["frozen_code_commit"] in block
    assert "Adjusted success comparisons below 0.05:" in block
    for field, comparisons in summary["primary_tests"].items():
        if field == "success_definition":
            continue
        for key, result in comparisons.items():
            raw = "n/a" if result["p"] is None else f"{result['p']:.6g}"
            adjusted = "n/a" if result["p_holm"] is None else f"{result['p_holm']:.6g}"
            row = (
                f"| {field} | E vs {evaluation_doc.LABEL.get(key, key)} | {result['n']} | "
                f"{raw} | {adjusted} |"
            )
            assert row in block
    assert "Full pair resolution" in block
    assert "budget-curves.json" in block
    for deviation in summary["protocol"]["deviations"]:
        assert f"Protocol deviation: {deviation}" in block


def test_rc1_is_explicitly_exploratory() -> None:
    summary = json.loads((RC1 / "summary.json").read_text(encoding="utf-8"))
    block = evaluation_doc.render(summary, "x")
    assert "this analysis is exploratory" in block
    assert "No adjusted significance claim follows from its bootstrap intervals" in block
    assert "does not measure resolution of both faults" in block


def test_splicing_replaces_only_the_generated_block() -> None:
    doc = f"before\n{evaluation_doc.START}\nold\n{evaluation_doc.END}\nafter\n"
    out = evaluation_doc.splice(doc, f"{evaluation_doc.START}\nnew\n{evaluation_doc.END}")
    assert out == f"before\n{evaluation_doc.START}\nnew\n{evaluation_doc.END}\nafter\n"
