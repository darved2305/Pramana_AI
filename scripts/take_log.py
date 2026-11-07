"""Append one recording take to the private take sheet, filled from the core, not by hand.

DEMO.md §6 asks for the seed, commit and hash of every take, and the honesty checklist asks for
outcome, reveal and replay claims to come from a recorded log. Run this after a take's reveal:

    uv run python scripts/take_log.py --investigation inv_... --scenario S1 --seed 19 \
        --participants human --deployment local --recording D:/takes/s1-take3.mkv

The sheet lives in ``.cache/takes/take-sheet.csv`` (git-ignored): it names recordings and
people's roles, and must not be committed. Nothing here sends a message or spends voice credit.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from pramana_core.llm import read_env_file

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / ".cache" / "takes" / "take-sheet.csv"
COLUMNS = [
    "take_id",
    "logged_at_utc",
    "source_commit",
    "worktree_clean",
    "scenario",
    "seed_as_entered",
    "deployment",
    "participants",
    "voice_provider",
    "investigation_id",
    "commitment",
    "status_before_reveal",
    "decision",
    "repair_verified",
    "correct_on_reveal",
    "commitment_verified",
    "replay_identical",
    "questions_asked",
    "recording",
    "selected",
    "notes",
]


STATUS_OF_PLAN = {
    "decide": "decided",
    "abstain": "abstained",
    "verified": "verified",
    "not_verified": "not_verified",
}


class TakeError(RuntimeError):
    pass


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return out.stdout.strip()


def _get(client: httpx.Client, path: str) -> Any:
    r = client.get(path)
    if r.status_code != 200:
        raise TakeError(f"GET {path} returned {r.status_code}")
    return r.json()


def take_row(
    client: httpx.Client, args: argparse.Namespace, *, commit: str, clean: bool
) -> dict[str, Any]:
    inv = args.investigation
    state = _get(client, f"/v1/investigations/{inv}")
    if state["status"] != "closed" or state.get("ground_truth") is None:
        raise TakeError(f"{inv} is {state['status']}: reveal it in the same take first")
    events = _get(client, f"/v1/investigations/{inv}/events?limit=500")
    created = next(e for e in events if e["type"] == "InvestigationCreated")["payload"]
    # Reveal is allowed only after a terminal plan, so the last plan before it is the status
    # the take ended in (decided, abstained, verified or not verified).
    revealed_at = next(i for i, e in enumerate(events) if e["type"] == "GroundTruthRevealed")
    plans = [e["payload"] for e in events[:revealed_at] if e["type"] == "PlanComputed"]
    before = STATUS_OF_PLAN.get(plans[-1]["kind"], plans[-1]["kind"]) if plans else "unknown"
    replay = _get(client, f"/v1/investigations/{inv}/replay")
    voice = _get(client, "/v1/voice/status")
    gt = state["ground_truth"]
    return {
        "take_id": args.take_id or f"{args.scenario}-{inv[-6:]}",
        "logged_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_commit": commit,
        "worktree_clean": clean,
        "scenario": args.scenario,
        "seed_as_entered": args.seed,
        "deployment": args.deployment,
        "participants": args.participants,
        "voice_provider": f"{voice.get('provider', 'unknown')} ({voice.get('provider_host')})",
        "investigation_id": inv,
        "commitment": created["commitment"],
        "status_before_reveal": before,
        "decision": gt.get("concluded_decision") or ("abstained" if gt.get("abstained") else ""),
        "repair_verified": any(
            e["type"] == "VerificationResult" and e["payload"].get("kind") == "verified"
            for e in events
        ),
        "correct_on_reveal": gt.get("correct"),
        "commitment_verified": gt["reveal"]["commitment_verified"],
        "replay_identical": replay["identical"],
        "questions_asked": state.get("questions_asked"),
        "recording": args.recording or "",
        "selected": "",
        "notes": args.notes or "",
    }


def append(row: dict[str, Any], sheet: Path = SHEET) -> None:
    sheet.parent.mkdir(parents=True, exist_ok=True)
    new = not sheet.exists()
    with sheet.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Log one recording take from the core's records")
    ap.add_argument("--investigation", required=True)
    ap.add_argument("--scenario", required=True, choices=["S1", "S2", "S7"])
    ap.add_argument("--seed", required=True, help="the seed entered when the take was created")
    ap.add_argument("--participants", required=True, choices=["human", "bot", "mixed"])
    ap.add_argument("--deployment", required=True, choices=["local", "tunnel", "staging"])
    ap.add_argument("--core", default=None, help="core URL (default PRAMANA_CORE_URL)")
    ap.add_argument("--take-id")
    ap.add_argument("--recording", help="path of the private recording file")
    ap.add_argument("--notes")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env = read_env_file(ROOT / ".env")
    env.update(os.environ)
    core = (args.core or env.get("PRAMANA_CORE_URL") or "http://127.0.0.1:8010").rstrip("/")
    key = env.get("CORE_AUTOMATION_KEY", "")
    commit = _git("rev-parse", "HEAD")
    clean = _git("status", "--porcelain", "--untracked-files=no") == ""
    with httpx.Client(base_url=core, headers={"X-Automation-Key": key}, timeout=30) as client:
        try:
            row = take_row(client, args, commit=commit, clean=clean)
        except (TakeError, httpx.HTTPError) as exc:
            print(f"take not logged: {exc}", file=sys.stderr)
            return 1
    append(row)
    print(f"logged {row['take_id']} to {SHEET}")
    for k in (
        "status_before_reveal",
        "correct_on_reveal",
        "commitment_verified",
        "replay_identical",
    ):
        print(f"  {k}: {row[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
