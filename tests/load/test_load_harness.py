"""Opt-in 60 to 90 second process-level voice load check."""

from __future__ import annotations

import os
import socket
import wave
from pathlib import Path

import pytest
from voice_bot_common import encode_synthetic_pcm, transcript_for_value

from load.harness import DEFAULT_SCRATCH, LoadOptions, run_load

pytestmark = pytest.mark.load


def _free_test_ports() -> tuple[int, int, int]:
    sockets = [socket.socket() for _ in range(3)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return tuple(int(sock.getsockname()[1]) for sock in sockets)  # type: ignore[return-value]
    finally:
        for sock in sockets:
            sock.close()


def test_load_test_ports_are_distinct_and_released() -> None:
    ports = _free_test_ports()

    assert len(set(ports)) == 3
    for port in ports:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))


@pytest.mark.skipif(
    os.environ.get("PRAMANA_RUN_LOAD") != "1",
    reason="set PRAMANA_RUN_LOAD=1 to run the process-level load test",
)
async def test_short_emulated_load() -> None:
    core_port, sim_port, fake_port = _free_test_ports()
    options = LoadOptions(
        duration_s=75,
        database_url=os.environ.get(
            "PRAMANA_LOAD_DATABASE_URL",
            "postgresql+asyncpg://pramana@localhost:5433/pramana_load_fa31_short",
        ),
        scratch_root=DEFAULT_SCRATCH,
        core_port=core_port,
        sim_port=sim_port,
        fake_port=fake_port,
        report_dir=(
            Path(os.environ["PRAMANA_LOAD_REPORT_DIR"])
            if os.environ.get("PRAMANA_LOAD_REPORT_DIR")
            else None
        ),
    )
    summary = await run_load(options)

    assert summary["load_duration_seconds"] >= 75
    assert summary["all_investigations_passed"] is True
    assert summary["peak_participant_call_sockets"] >= 3
    assert summary["three_call_window"]["window_seconds"] >= 75
    assert summary["three_call_window"]["under_three_call_seconds"] <= 2
    assert summary["three_call_window"]["max_handoff_gap_seconds"] <= 2
    assert summary["websocket_closes"]["unexpected_count"] == 0


def _write_local_live_clips(directory: Path) -> None:
    values = (
        "yes",
        "no",
        "on",
        "off",
        "green",
        "amber",
        "red",
        "up",
        "tripped",
        "no_network",
        "stuck_connecting",
        "connected",
    )
    directory.mkdir(parents=True, exist_ok=True)
    for language in ("hi", "mr"):
        for value in values:
            path = directory / f"{language}__{value}.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(encode_synthetic_pcm(transcript_for_value(value)))


@pytest.mark.skipif(
    os.environ.get("PRAMANA_RUN_LOAD") != "1",
    reason="set PRAMANA_RUN_LOAD=1 to run the process-level load test",
)
async def test_live_handling_uses_local_gnani_stand_in(tmp_path: Path) -> None:
    clips = tmp_path / "clips"
    _write_local_live_clips(clips)
    core_port, sim_port, fake_port = _free_test_ports()
    options = LoadOptions(
        duration_s=15,
        database_url=os.environ.get(
            "PRAMANA_LOAD_LIVE_DATABASE_URL",
            "postgresql+asyncpg://pramana@localhost:5433/pramana_load_fa31_live",
        ),
        scratch_root=DEFAULT_SCRATCH,
        live=True,
        clips=clips,
        test_local_provider=True,
        core_port=core_port,
        sim_port=sim_port,
        fake_port=fake_port,
    )
    summary = await run_load(options)

    assert summary["provider_mode"] == "local stand-in for live-mode checks"
    assert summary["latency"] is None
    assert summary["all_investigations_passed"] is True
    assert summary["three_call_window"]["window_seconds"] >= 15
    assert summary["three_call_window"]["under_three_call_seconds"] <= 2
    assert summary["three_call_window"]["max_handoff_gap_seconds"] <= 2
    assert summary["websocket_closes"]["unexpected_count"] == 0
    assert summary["stream_cap_respected"] is True
