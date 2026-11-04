"""Test the voice pipeline on real short conversational turns from an open dataset.

Source: liva-ai/hindi-english-asr on Hugging Face (CC-BY-4.0), Hindi-English code-mixed
conversations with per-speaker time-coded human transcripts. Short turns (0.4-4 s) are cut out
with ffmpeg, sent through the running core's ``/v1/voice/stt`` (metered, rate limited), and
compared with the human reference: character error rate, and whether our answer extractor reaches
the same yes/no outcome from Gnani's transcript as from the reference.

Downloaded audio goes to a temporary folder and is deleted at the end. Results are private
(Gnani EULA s.16); print them, do not publish them.

Usage: python scripts/dataset_voice_check.py [--max-clips 25] [--rows 40] [--keep]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import httpx

from pramana_core.language.extraction import RuleExtractor

DATASET = "liva-ai/hindi-english-asr"
ROWS_API = "https://datasets-server.huggingface.co/rows"
SEGMENT = re.compile(r"Speaker \d+ \[(\d+):(\d+):([\d.]+) - (\d+):(\d+):([\d.]+)\]: (.+)")


def seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text.casefold())
    return re.sub(r"[\s\W_]+", "", text)


def cer(ref: str, hyp: str) -> float:
    """Character error rate after removing punctuation and spaces (script-sensitive)."""
    r, h = normalise(ref), normalise(hyp)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i]
        for j, hc in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(r)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--rows", type=int, default=40)
    ap.add_argument("--max-clips", type=int, default=25)
    ap.add_argument("--keep", action="store_true", help="do not delete downloaded audio")
    args = ap.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        sys.exit("ffmpeg is required to cut segments")

    work = Path(tempfile.mkdtemp(prefix="pramana_ds_"))
    extractor = RuleExtractor()
    results: list[dict[str, object]] = []
    try:
        with (
            httpx.Client(timeout=60, follow_redirects=True) as hub,
            httpx.Client(base_url=args.core, timeout=60) as core,
        ):
            rows = hub.get(
                ROWS_API,
                params={
                    "dataset": DATASET,
                    "config": "default",
                    "split": "train",
                    "offset": 0,
                    "length": min(args.rows, 100),
                },
            ).json()["rows"]
            for item in rows:
                if len(results) >= args.max_clips:
                    break
                row = item["row"]
                src = row["audio"][0]["src"]
                segments = []
                for m in SEGMENT.finditer(row["transcript"]):
                    start, end = seconds(*m.group(1, 2, 3)), seconds(*m.group(4, 5, 6))
                    text = m.group(7).strip()
                    if 0.4 <= end - start <= 4.0 and "[" not in text and normalise(text):
                        segments.append((start, end, text))
                if not segments:
                    continue
                mp3 = work / f"{item['row_idx']}.mp3"
                mp3.write_bytes(hub.get(src).content)
                for k, (start, end, ref) in enumerate(segments[:2]):
                    if len(results) >= args.max_clips:
                        break
                    wav = work / f"{item['row_idx']}_{k}.wav"
                    subprocess.run(
                        [
                            ffmpeg,
                            "-loglevel",
                            "error",
                            "-y",
                            "-ss",
                            f"{max(0, start - 0.15):.2f}",
                            "-to",
                            f"{end + 0.25:.2f}",
                            "-i",
                            str(mp3),
                            "-ac",
                            "1",
                            "-ar",
                            "16000",
                            str(wav),
                        ],
                        check=True,
                    )
                    r = core.post(
                        "/v1/voice/stt",
                        files={"audio": (wav.name, wav.read_bytes(), "audio/wav")},
                        data={"language_codes": "hi-IN,en-IN", "codemix": "true"},
                    )
                    if r.status_code != 200:
                        print(f"  stop: HTTP {r.status_code} {r.text[:160]}")
                        return
                    hyp = r.json()["transcript"]
                    ref_out = extractor.extract_sync(ref, ["yes", "no"]).outcome
                    hyp_out = extractor.extract_sync(hyp, ["yes", "no"]).outcome
                    results.append(
                        {
                            "ref": ref,
                            "hyp": hyp,
                            "cer": cer(ref, hyp),
                            "dur": end - start,
                            "ref_yn": ref_out,
                            "hyp_yn": hyp_out,
                        }
                    )
                    print(
                        f"  {end - start:4.1f}s  ref {ref!r}\n         heard {hyp!r}"
                        f"  [yes/no: ref={ref_out} heard={hyp_out}]"
                    )
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
            print(f"\ndeleted downloaded audio ({work})")

    if not results:
        return
    cers = sorted(float(r["cer"]) for r in results)  # type: ignore[arg-type]
    decided = [r for r in results if r["ref_yn"] != "unknown"]
    agree = sum(1 for r in decided if r["ref_yn"] == r["hyp_yn"])
    print(f"\n{len(results)} real turns (private results, Gnani EULA s.16)")
    print(
        f"  median CER {cers[len(cers) // 2]:.2f} (script-sensitive: Latin vs Devanagari "
        "spellings of the same word count as errors)"
    )
    print(
        f"  yes/no answers in the reference: {len(decided)}; same outcome from Gnani's "
        f"transcript: {agree}/{len(decided)}"
    )


if __name__ == "__main__":
    main()
