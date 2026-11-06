"""Live load collection keeps the facts needed to review a run."""

from __future__ import annotations

import json
import subprocess

from load import harness


def test_live_bot_result_is_collected_without_latency_values(tmp_path, monkeypatch) -> None:
    result = {
        "status": "verified",
        "questions_asked": 9,
        "revealed_correct": True,
        "commitment_verified": True,
        "replay_identical": True,
        "call_socket_closes": [{"participant_id": "p_riya", "code": 1000, "reason": ""}],
        "call_socket_metrics": {
            "opened": 3,
            "closed": 3,
            "peak_open": 3,
            "active": 0,
            "three_way_seconds": 10.5,
        },
    }
    stdout = "VOICE_RESULT_JSON=" + json.dumps(result) + "\n"
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=stdout, stderr=""),
    )
    options = harness.LoadOptions(
        duration_s=10,
        database_url="postgresql+asyncpg://pramana@localhost:5433/pramana_load_p3_p6",
        scratch_root=tmp_path,
        live=True,
        clips=tmp_path,
    )

    actual = harness._run_bot(
        options=options,
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
        bot_log=tmp_path / "voice-bots.log",
    )

    assert actual == result
    assert not {"emulated_eos_to_answer_ms", "caller_latency_ms"} & actual.keys()


def test_live_window_requires_elapsed_and_three_call_duration() -> None:
    assert not harness._load_window_complete(10, 10, 9.9)
    assert not harness._load_window_complete(9.9, 10, 10)
    assert harness._load_window_complete(10, 10, 10)


def test_live_stream_cap_summary_reports_observed_peak() -> None:
    samples = [
        {"open_streams": 0, "peak_streams": 0, "stream_cap": 16},
        {"open_streams": 3, "peak_streams": 3, "stream_cap": 16},
    ]

    assert harness._stream_cap_summary(samples, configured_cap=16) == {
        "configured": 16,
        "max_open_observed": 3,
        "max_peak_observed": 3,
        "passed": True,
    }


def test_live_stream_cap_summary_fails_if_observed_peak_exceeds_limit() -> None:
    samples = [{"open_streams": 3, "peak_streams": 17, "stream_cap": 16}]

    assert harness._stream_cap_summary(samples, configured_cap=16)["passed"] is False


def test_runtime_cache_summary_tracks_start_end_and_peak() -> None:
    samples = [
        {"runtime_caches": {"question_audio_bytes": 32, "engine_entries": 1}},
        {"runtime_caches": {"question_audio_bytes": 128, "engine_entries": 0}},
        {"runtime_caches": {"question_audio_bytes": 64, "engine_entries": 2}},
    ]

    assert harness._runtime_cache_summary(samples) == {
        "question_audio_bytes": {"start": 32, "end": 64, "peak": 128},
        "engine_entries": {"start": 1, "end": 2, "peak": 2},
    }


def test_full_load_memory_failure_is_not_ignored() -> None:
    assert not harness._memory_checks_passed([{"passed": False}], full_run=True)
    assert harness._memory_checks_passed([{"passed": True}], full_run=True)
    assert harness._memory_checks_passed([], full_run=False)


def test_live_summary_line_keeps_memory_and_result_facts_without_latency_values() -> None:
    summary = {
        "latency": None,
        "memory": {"sample_count": 120, "leak_checks": [{"service": "core", "passed": False}]},
        "investigations": [{"status": "verified", "replay_identical": True}],
    }

    line = harness.live_summary_line(summary)

    assert line.startswith("LIVE_LOAD_SUMMARY=")
    assert json.loads(line.removeprefix("LIVE_LOAD_SUMMARY=")) == summary
    assert "caller_latency_ms" not in line
    assert "emulated_eos_to_answer_ms" not in line
