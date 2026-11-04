"""Score recorded answer clips through the real voice pipeline (internal use only).

Each clip goes through the running core's ``/v1/voice/stt`` (Prisma v3.0, metered and rate
limited by the governor) with that probe's answer vocabulary as context, then through the same
extractor investigations use. The report compares the extracted outcome with the label in the
file name. Per the Gnani EULA, results stay private: write them outside the repository.

File names: ``<lang>__<probe>__<expected outcome>__<anything>.<ext>``
  lang:    mr | hi | en | hi-en
  probe:   a probe id from packs/campus_block_c.yaml (e.g. nvr_screen, wifi_status)
  outcome: one of that probe's outcomes, or "unknown" for deliberately unclear answers
  ext:     wav | mp3 | m4a | ogg | flac | aac   (WhatsApp ".opus" voice notes are sent as .ogg)
Example: ``mr__nvr_screen__off__mahesh1.m4a``

Usage: python scripts/voice_eval.py --clips <folder> --out <report.csv> [--yes]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

import httpx

from pramana_core.language.extraction import RuleExtractor
from pramana_core.voice.conversation import answer_keyterms
from pramana_domain import load_pack

CANDIDATES = {"mr": "mr-IN,hi-IN", "hi": "hi-IN,en-IN", "en": "en-IN,hi-IN", "hi-en": "hi-IN,en-IN"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
MIN_COST_INR = 0.02  # observed per-request STT minimum


def parse(path: Path, outcomes: dict[str, list[str]]) -> tuple[str, str, str] | str:
    parts = path.stem.split("__")
    if len(parts) < 3:
        return "name must be <lang>__<probe>__<outcome>__<tag>"
    lang, probe, expected = parts[0], parts[1], parts[2]
    if lang not in CANDIDATES:
        return f"unknown language {lang!r}"
    if probe not in outcomes:
        return f"unknown probe {probe!r}"
    if expected != "unknown" and expected not in outcomes[probe]:
        return f"{expected!r} is not an outcome of {probe} {outcomes[probe]}"
    return lang, probe, expected


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = ap.parse_args()

    pack = load_pack("campus_block_c")
    outcomes = {p.id: list(p.outcomes) for p in pack.probes}
    files = sorted(p for p in Path(args.clips).iterdir() if p.suffix.lower() in AUDIO_EXT)
    jobs, skipped = [], []
    for f in files:
        parsed = parse(f, outcomes)
        if isinstance(parsed, str):
            skipped.append((f.name, parsed))
        else:
            jobs.append((f, *parsed))
    for name, why in skipped:
        print(f"skip {name}: {why}")
    estimate = len(jobs) * MIN_COST_INR
    print(f"{len(jobs)} clips; estimated cost at least Rs {estimate:.2f} (+ Rs 0.0056/s of audio)")
    if not jobs:
        return
    if not args.yes and input("proceed? [y/N] ").strip().lower() != "y":
        return

    extractor = RuleExtractor()
    rows = []
    async with httpx.AsyncClient(base_url=args.core, timeout=60) as client:
        for f, lang, probe, expected in jobs:
            name = f.name if f.suffix.lower() != ".opus" else f.with_suffix(".ogg").name
            r = await client.post(
                "/v1/voice/stt",
                files={"audio": (name, f.read_bytes())},
                data={
                    "language_codes": CANDIDATES[lang],
                    "codemix": str(lang == "hi-en").lower(),
                    "keyterms": ",".join(t for t in answer_keyterms(pack, probe) if "," not in t),
                },
            )
            if r.status_code != 200:
                err = r.json().get("error", {})
                rows.append(
                    {
                        "file": f.name,
                        "lang": lang,
                        "probe": probe,
                        "expected": expected,
                        "transcript": "",
                        "extracted": "",
                        "hedge": "",
                        "correct": "",
                        "error": err.get("code", r.status_code),
                    }
                )
                print(f"  {f.name}: ERROR {err.get('code')} {err.get('message', '')}")
                if err.get("code") in ("VOICE_BUDGET_EXCEEDED", "VOICE_CREDIT_EXHAUSTED"):
                    break
                continue
            stt = r.json()
            ext = extractor.extract_sync(stt["transcript"], outcomes[probe])
            ok = ext.outcome == expected
            rows.append(
                {
                    "file": f.name,
                    "lang": lang,
                    "probe": probe,
                    "expected": expected,
                    "transcript": stt["transcript"],
                    "extracted": ext.outcome,
                    "hedge": ext.hedge.value,
                    "correct": ok,
                    "error": "",
                }
            )
            mark = "ok " if ok else "MISS"
            print(f"  {mark} {f.name}: heard {stt['transcript']!r} -> {ext.outcome}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    scored = [r for r in rows if r["error"] == ""]
    by_lang: dict[str, list[bool]] = {}
    for r in scored:
        by_lang.setdefault(str(r["lang"]), []).append(bool(r["correct"]))
    print("\nend-to-end outcome agreement (private):")
    for lang, oks in sorted(by_lang.items()):
        print(f"  {lang:6s} {sum(oks)}/{len(oks)}")
    print(f"report: {out}")


if __name__ == "__main__":
    asyncio.run(main())
