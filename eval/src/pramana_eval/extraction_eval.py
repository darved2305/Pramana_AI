"""Language-level check of answer extraction: rules alone vs rules + LLM second opinion.

``python -m pramana_eval.extraction_eval [--set PATH] [--provider gemini|groq|none] [--model M]
[--out DIR]``

Two labelled sets, both synthetic text:

* ``eval/data/extraction_set.jsonl``: the development set (48 answers). The rules were tuned
  on it, so its scores are optimistic.
* ``eval/data/extraction_heldout.jsonl``: 80 answers (20 each in English, Hindi, Marathi and
  Hinglish), written and committed before any tuning against it and never used for tuning.

Every item names the probe; the question is that probe's English template. Two error types are
reported separately because they differ in harm: *invented evidence* (a definite outcome where
the right answer is "unknown") can push a decision the wrong way; a *missed answer* only costs
another question. With ``--out``, ``summary.json`` and ``report.md`` are written from the same
numbers, so no figure is typed by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pramana_core.language.extraction import RuleExtractor
from pramana_core.language.hybrid import HybridExtractor
from pramana_core.llm import LlmClient
from pramana_domain import load_pack

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA = DATA_DIR / "extraction_set.jsonl"
HELDOUT = DATA_DIR / "extraction_heldout.jsonl"
FIELDS = ("outcome", "hedge", "directness", "injection", "stop")


def load_items(path: Path = DATA) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


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
        got = {
            "outcome": r.outcome,
            "hedge": r.hedge.value,
            "directness": r.directness.value,
            "injection": r.injection_suspected,
            "stop": r.wants_to_stop,
        }
        checks = {f: got[f] == it[f] for f in FIELDS if f in it}
        rows.append(
            {
                "id": it["id"],
                "lang": it.get("lang", "?"),
                "text": it["text"],
                "expected": it["outcome"],
                "got": r.outcome,
                "fields": checks,
                "got_fields": got,
                "method": r.method,
                "ok": all(checks.values()),
            }
        )
    n = len(rows)
    invented = [r for r in rows if r["expected"] == "unknown" and r["got"] != "unknown"]
    missed = [r for r in rows if r["expected"] != "unknown" and r["got"] == "unknown"]
    wrong = [
        r for r in rows if r["expected"] != "unknown" and r["got"] not in ("unknown", r["expected"])
    ]
    injections = [r for r in rows if r["got_fields"]["injection"] or "injection" in r["fields"]]
    per_field = {
        f: _rate(
            sum(r["fields"][f] for r in rows if f in r["fields"]),
            sum(f in r["fields"] for r in rows),
        )
        for f in FIELDS
    }
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_lang[r["lang"]].append(r)
    per_language = {
        lang: {
            "n": len(rs),
            "all_fields": _rate(sum(r["ok"] for r in rs), len(rs)),
            **{
                f: _rate(
                    sum(r["fields"][f] for r in rs if f in r["fields"]),
                    sum(f in r["fields"] for r in rs),
                )
                for f in FIELDS
            },
        }
        for lang, rs in sorted(by_lang.items())
    }
    return {
        "n": n,
        "correct": sum(r["ok"] for r in rows),
        "all_fields_accuracy": _rate(sum(r["ok"] for r in rows), n),
        "invented": len(invented),
        "missed": len(missed),
        "wrong_outcome": len(wrong),
        "injection_flagged_with_evidence": sum(
            1 for r in injections if r["got_fields"]["injection"] and r["got"] != "unknown"
        ),
        "llm_used": sum(r["method"] == "llm" for r in rows),
        "per_field": per_field,
        "per_language": per_language,
        "rows": rows,
    }


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        f"# Answer extraction: {summary['set']}",
        "",
        f"Generated by `python -m pramana_eval.extraction_eval` at commit `{summary['git_sha']}` "
        f"on {summary['generated_at']}. Synthetic text answers; no audio, no speech recognition.",
        "",
        summary["note"],
        "",
    ]
    for name, m in summary["extractors"].items():
        lines += [
            f"## {name}",
            "",
            f"- All labelled fields correct: {m['correct']}/{m['n']} "
            f"({_pct(m['all_fields_accuracy'])})",
            f"- Invented evidence (definite outcome where the answer is unknown): {m['invented']}",
            f"- Missed answers (unknown where an outcome was given): {m['missed']}",
            f"- Wrong outcome: {m['wrong_outcome']}",
            f"- Injection flagged but still produced an outcome: "
            f"{m['injection_flagged_with_evidence']}",
            "",
            "| Field | Accuracy |",
            "|---|---|",
            *[f"| {f} | {_pct(v)} |" for f, v in m["per_field"].items()],
            "",
            "| Language | n | All fields | Outcome | Hedge | Directness | Injection | Stop |",
            "|---|---|---|---|---|---|---|---|",
            *[
                f"| {lang} | {v['n']} | {_pct(v['all_fields'])} | {_pct(v['outcome'])} | "
                f"{_pct(v['hedge'])} | {_pct(v['directness'])} | {_pct(v['injection'])} | "
                f"{_pct(v['stop'])} |"
                for lang, v in m["per_language"].items()
            ],
            "",
            "Mistakes:",
            "",
        ]
        bad = [r for r in m["rows"] if not r["ok"]]
        if not bad:
            lines.append("- none")
        for r in bad:
            wrong_fields = ", ".join(
                f"{f}: got {r['got_fields'][f]}" for f, ok in r["fields"].items() if not ok
            )
            lines.append(f"- `{r['id']}` ({r['lang']}) \"{r['text']}\": {wrong_fields}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, default=DATA)
    ap.add_argument("--provider", default="gemini", choices=["gemini", "groq", "none"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    pack = load_pack("campus_block_c")
    outcomes = {p.id: list(p.outcomes) for p in pack.probes}
    questions = {p.id: p.templates["en"].replace("{place}", "there") for p in pack.probes}
    items = load_items(args.set)
    runs: dict[str, Any] = {"rules": RuleExtractor()}
    if args.provider != "none":
        model = args.model or ("gemini-3.1-flash-lite" if args.provider == "gemini" else None)
        client = LlmClient(args.provider, model, cache_dir=Path(".cache/llm"))
        runs[f"rules+{client.model}"] = HybridExtractor(RuleExtractor(), client)
    results = {
        name: asyncio.run(score(ex, items, outcomes, questions)) for name, ex in runs.items()
    }
    print(f"{len(items)} labelled answers from {args.set.name}\n")
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
            print(f"  {r['id']}: expected {r['expected']}, got {r['got']} {r['fields']}")
    if args.out is not None:
        heldout = args.set.resolve() == HELDOUT.resolve()
        summary = {
            "set": args.set.name,
            "items": len(items),
            "git_sha": _git_sha(),
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "note": (
                "Held-out set: written and committed before any tuning against it, and never "
                "used for tuning."
                if heldout
                else "Development set: the rules were tuned on it, so these figures are "
                "optimistic."
            ),
            "extractors": results,
        }
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.out / "report.md").write_text(render_report(summary), encoding="utf-8")
        print(f"\nwrote {args.out / 'summary.json'} and {args.out / 'report.md'}")


if __name__ == "__main__":
    main()
