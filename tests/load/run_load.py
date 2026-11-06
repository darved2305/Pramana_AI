"""Run the emulated or live voice load harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from harness import DEFAULT_SCRATCH, ROOT, LoadOptions, run_load


def parse_args() -> argparse.Namespace:
    today = datetime.now(UTC).date().isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=float, default=600)
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "PRAMANA_LOAD_DATABASE_URL",
            "postgresql+asyncpg://pramana@localhost:5433/pramana_load_p3",
        ),
    )
    parser.add_argument("--scratch-dir", type=Path, default=DEFAULT_SCRATCH)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--core-port", type=int, default=8210)
    parser.add_argument("--sim-port", type=int, default=8110)
    parser.add_argument("--fake-port", type=int, default=8310)
    parser.add_argument("--stream-cap", type=int, default=16)
    parser.add_argument(
        "--live",
        action="store_true",
        help="send clip audio to live Gnani through the core's existing budget guard",
    )
    parser.add_argument("--clips", type=Path, help="16 kHz mono PCM16 clips, required with --live")
    args = parser.parse_args()
    if not args.live and args.report_dir is None and args.duration_seconds >= 600:
        args.report_dir = ROOT / "eval" / "reports" / f"load-{today}"
    return args


def main() -> None:
    args = parse_args()
    options = LoadOptions(
        duration_s=args.duration_seconds,
        database_url=args.database_url,
        scratch_root=args.scratch_dir,
        report_dir=args.report_dir,
        core_port=args.core_port,
        sim_port=args.sim_port,
        fake_port=args.fake_port,
        stream_cap=args.stream_cap,
        live=args.live,
        clips=args.clips,
    )
    summary = asyncio.run(run_load(options))
    if args.live:
        print("Live load completed. The core budget and rate guards remained active.", flush=True)
    else:
        print(
            "LOAD_SUMMARY="
            + json.dumps(
                {
                    "investigations": summary["investigation_count"],
                    "duration_seconds": summary["load_duration_seconds"],
                    "three_call_seconds": summary["three_call_seconds"],
                    "all_passed": summary["all_investigations_passed"],
                    "report_dir": str(args.report_dir) if args.report_dir else None,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
