"""Latency report attribution keeps synthetic participant time separate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import load_test


def test_latency_report_excludes_synthetic_answer_time_from_provider_share(tmp_path: Path) -> None:
    log_path = tmp_path / "core.log"
    events = [
        {
            "event": "voice_hop",
            "trace_id": "trace-1",
            "hop": "capture_end",
            "timestamp": "2026-11-10T00:00:00+00:00",
            "capture_duration_ms": 1000,
        },
        {
            "event": "voice_hop",
            "trace_id": "trace-1",
            "hop": "proxy_commit_received",
            "timestamp": "2026-11-10T00:00:01.010000+00:00",
        },
        {
            "event": "voice_hop",
            "trace_id": "trace-1",
            "hop": "extraction_complete",
            "timestamp": "2026-11-10T00:00:05+00:00",
            "duration_ms": 250,
            "total_turn_ms": 5000,
        },
    ]
    log_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

    report_path = tmp_path / "latency.md"
    load_test.write_latency_report(
        report_path,
        log_path,
        {"transcripts": 1, "tts_sse": 1},
        argparse.Namespace(investigations=1),
    )

    report = report_path.read_text(encoding="utf-8")
    assert "Synthetic answer audio transmission: 1000 ms, 20.0%" in report
    assert "Provider placeholders: 4.0% of total measured turn time, and 5.0%" in report
    assert "Remaining non-capture time: 95.0% after excluding provider placeholders" in report
    assert "not a pure application-code measurement" in report
