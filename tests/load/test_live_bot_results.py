"""Live provider runs retain safe investigation evidence for the harness."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from load import harness


def test_live_bot_results_are_parsed_instead_of_discarded(tmp_path: Path, monkeypatch) -> None:
    clips = tmp_path / "clips"
    clips.mkdir()
    expected = {
        "investigation_id": "inv-live-test",
        "status": "verified",
        "revealed_correct": True,
        "commitment_verified": True,
        "replay_identical": True,
        "call_socket_closes": [],
        "call_socket_metrics": {"peak_open": 3, "three_way_seconds": 12.0},
    }

    def fake_run(args, **kwargs):
        assert "--clips" in args
        assert "--synthetic" not in args
        return SimpleNamespace(
            args=args,
            returncode=0,
            stdout="LOAD_RESULT_JSON=" + json.dumps(expected) + "\n",
            stderr="",
        )

    monkeypatch.setattr(harness, "subprocess", SimpleNamespace(run=fake_run))
    result = harness._run_bot(
        options=harness.LoadOptions(
            duration_s=10,
            database_url="postgresql+asyncpg://pramana@localhost:5433/pramana_load_fa31",
            scratch_root=tmp_path,
            live=True,
            clips=clips,
        ),
        run_dir=tmp_path,
        core_url="http://127.0.0.1:8210",
        sim_url="http://127.0.0.1:8110",
        automation_key="test-key",
        parallel=3,
        silent_first=False,
        delay_first_answer_s=0,
        barge_in_first=False,
        keep_calls_open=True,
        idle_probe=False,
        bot_log=tmp_path / "bots.log",
    )

    assert result == expected


def test_private_live_evidence_is_persisted_without_latency(tmp_path: Path) -> None:
    summary = {
        "provider_mode": "live Gnani",
        "latency": None,
        "all_investigations_passed": True,
        "investigations": [{"investigation_id": "inv-private", "revealed_correct": True}],
    }

    evidence_path = harness._write_private_live_evidence(tmp_path, summary)

    assert evidence_path.is_relative_to(tmp_path / "live-evidence")
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == {
        **summary,
        "private_evidence_path": str(evidence_path),
    }
