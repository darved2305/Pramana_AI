"""Language-level check of answer extraction: rules alone vs rules + LLM second opinion.

``python -m pramana_eval.extraction_eval [--provider gemini|groq|none] [--model M]``

The labelled set (``eval/data/extraction_set.jsonl``) is synthetic text: plain answers,
paraphrases the rules cannot map, and traps (cannot see, hearsay, guesses, injection, stale
information, self-corrections). Two error types are reported separately because they differ in
harm: *invented evidence* (a definite outcome where the right answer is "unknown") can push a
decision the wrong way; a *missed answer* only costs another question.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pramana_core.language.extraction import RuleExtractor
from pramana_core.language.hybrid import HybridExtractor
from pramana_core.llm import LlmClient
from pramana_domain import load_pack

DATA = Path(__file__).resolve().parents[2] / "data" / "extraction_set.jsonl"


def load_items() -> list[dict[str, Any]]:
    return [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line]


async def score(
    extractor: Any,
    items: list[dict[str, Any]],
    outcomes: dict[str, list[str]],
    questions: dict[str, str],
) -> dict[str, Any]:
    rows = []
    for it in items:
        r = await extractor.extract(
            it["text"], outcomes[it["probe"]], question=questions[it["probe"]]
        )
        ok = r.outcome == it["outcome"]
        if "hedge" in it:
            ok = ok and r.hedge.value == it["hedge"]
        if "directness" in it:
            ok = ok and r.directness.value == it["directness"]
        rows.append(
            {
                "id": it["id"],
                "expected": it["outcome"],
                "got": r.outcome,
                "hedge": r.hedge.value,
                "directness": r.directness.value,
                "method": r.method,
                "ok": ok,
            }
        )
    n = len(rows)
    invented = [r for r in rows if r["expected"] == "unknown" and r["got"] != "unknown"]
    missed = [r for r in rows if r["expected"] != "unknown" and r["got"] == "unknown"]
    wrong = [
        r for r in rows if r["expected"] != "unknown" and r["got"] not in ("unknown", r["expected"])
    ]
    return {
        "n": n,
        "correct": sum(r["ok"] for r in rows),
        "invented": len(invented),
        "missed": len(missed),
        "wrong_outcome": len(wrong),
        "llm_used": sum(r["method"] == "llm" for r in rows),
        "rows": rows,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="gemini", choices=["gemini", "groq", "none"])
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    pack = load_pack("campus_block_c")
    outcomes = {p.id: list(p.outcomes) for p in pack.probes}
    questions = {p.id: p.templates["en"].replace("{place}", "there") for p in pack.probes}
    items = load_items()
    runs: dict[str, Any] = {"rules": RuleExtractor()}
    if args.provider != "none":
        model = args.model or ("gemini-3.1-flash-lite" if args.provider == "gemini" else None)
        client = LlmClient(args.provider, model, cache_dir=Path(".cache/llm"))
        runs[f"rules+{client.model}"] = HybridExtractor(RuleExtractor(), client)
    results = {
        name: asyncio.run(score(ex, items, outcomes, questions)) for name, ex in runs.items()
    }
    print(f"{len(items)} labelled answers\n")
    print(f"{'extractor':36s} correct  invented  missed  wrong  llm_calls")
    for name, m in results.items():
        print(
            f"{name:36s} {m['correct']:3d}/{m['n']:<3d} {m['invented']:6d} {m['missed']:7d} "
            f"{m['wrong_outcome']:6d} {m['llm_used']:9d}"
        )
    for name, m in results.items():
        bad = [r for r in m["rows"] if not r["ok"]]
        print(f"\n{name} mistakes:")
        for r in bad:
            print(
                f"  {r['id']}: expected {r['expected']}, got {r['got']} "
                f"({r['hedge']}, {r['directness']}, {r['method']})"
            )


if __name__ == "__main__":
    main()
