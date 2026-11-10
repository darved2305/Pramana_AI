"""docs/EVALUATION.md results are generated from a summary and never drift from it."""

from __future__ import annotations

import json
from pathlib import Path

from pramana_eval import evaluation_doc

ROOT = Path(__file__).resolve().parents[2]
RC1 = ROOT / "eval" / "reports" / "benchmark-2026-11-07-rc1"


def test_the_committed_results_match_the_release_candidate_summary() -> None:
    assert evaluation_doc.main([str(RC1), "--check"]) == 0


def test_every_policy_number_comes_from_the_summary() -> None:
    summary = json.loads((RC1 / "summary.json").read_text(encoding="utf-8"))
    block = evaluation_doc.render(summary, "x")
    assert "Source: `x/summary.json`" in block
    for p in summary["policies"].values():
        assert f"{p['success_rate'] * 100:.1f}%" in block
    assert summary["git_sha"] in block
    assert "this analysis is exploratory" in block
    assert "do not establish adjusted statistical significance" in block
    assert "full incident resolution" in block


def test_splicing_replaces_only_the_generated_block() -> None:
    doc = f"before\n{evaluation_doc.START}\nold\n{evaluation_doc.END}\nafter\n"
    out = evaluation_doc.splice(doc, f"{evaluation_doc.START}\nnew\n{evaluation_doc.END}")
    assert out == f"before\n{evaluation_doc.START}\nnew\n{evaluation_doc.END}\nafter\n"
