"""Check Prisma v3.0 on real human Marathi and Hindi speech from Google FLEURS (CC BY 4.0).

FLEURS (huggingface.co/datasets/google/fleurs) holds read sentences by native speakers. The
script streams one split's audio archive and stops after ``--n`` clips, so only a few MB are
downloaded and nothing is kept unless ``--keep`` is given. Each clip goes through the running
core's metered ``/v1/voice/stt`` and is compared with the human transcription (character error
rate, script-sensitive). This tests recognition of real voices; it says nothing about our short
answers. Results are private under the Gnani EULA (s.16): print them, never publish them.

Usage: python scripts/fleurs_voice_check.py --lang mr_in [--n 10] [--core http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import csv
import io
import shutil
import statistics
import sys
import tarfile
import tempfile
from pathlib import Path

import httpx
from core_auth import automation_headers
from dataset_voice_check import cer

BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
CANDIDATES = {"mr_in": "mr-IN,hi-IN", "hi_in": "hi-IN,en-IN"}


def references(lang: str, split: str) -> dict[str, str]:
    """file name -> human transcription (raw, with punctuation)."""
    tsv = httpx.get(f"{BASE}/{lang}/{split}.tsv", follow_redirects=True, timeout=60)
    tsv.raise_for_status()
    out: dict[str, str] = {}
    for row in csv.reader(io.StringIO(tsv.text), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(row) > 2:
            out[row[1]] = row[2]
    return out


def first_clips(lang: str, split: str, n: int, max_s: float, work: Path) -> list[Path]:
    """Stream the split's tar.gz and stop after ``n`` clips short enough for one REST call."""
    got: list[Path] = []
    url = f"{BASE}/{lang}/audio/{split}.tar.gz"
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()

        class Raw(io.RawIOBase):
            def __init__(self) -> None:
                self.it = r.iter_raw()
                self.buf = b""

            def readable(self) -> bool:
                return True

            def readinto(self, b: bytearray) -> int:  # type: ignore[override]
                while not self.buf:
                    try:
                        self.buf = next(self.it)
                    except StopIteration:
                        return 0
                k = min(len(b), len(self.buf))
                b[:k], self.buf = self.buf[:k], self.buf[k:]
                return k

        with tarfile.open(fileobj=io.BufferedReader(Raw()), mode="r|gz") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".wav"):
                    continue
                data = tar.extractfile(member)
                if data is None:
                    continue
                raw = data.read()
                seconds = (len(raw) - 44) / (2 * 16000)  # FLEURS is 16 kHz mono PCM16
                if seconds > max_s:
                    continue
                path = work / Path(member.name).name
                path.write_bytes(raw)
                got.append(path)
                if len(got) >= n:
                    break
    return got


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=sorted(CANDIDATES), required=True)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--max-s", type=float, default=12.0)
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="pramana_fleurs_"))
    try:
        refs = references(args.lang, args.split)
        clips = first_clips(args.lang, args.split, args.n, args.max_s, work)
        cost = 0.02 * len(clips)
        print(f"{len(clips)} clips from FLEURS {args.lang}/{args.split}; about Rs {cost:.2f}")
        rates: list[float] = []
        with httpx.Client(base_url=args.core, timeout=60, headers=automation_headers()) as core:
            for clip in clips:
                r = core.post(
                    "/v1/voice/stt",
                    files={"audio": (clip.name, clip.read_bytes(), "audio/wav")},
                    data={"language_codes": CANDIDATES[args.lang], "codemix": "false"},
                )
                if r.status_code != 200:
                    print(clip.name, "ERROR", r.status_code, r.text[:160])
                    continue
                hyp, ref = r.json()["transcript"], refs.get(clip.name, "")
                rate = cer(ref, hyp)
                rates.append(rate)
                print(f"{clip.name}  CER {rate:.2f}\n  ref: {ref}\n  hyp: {hyp}")
        if rates:
            print(f"median CER {statistics.median(rates):.3f} over {len(rates)} clips (private)")
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
