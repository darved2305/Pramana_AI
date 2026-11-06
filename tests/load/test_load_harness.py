"""Opt-in 60 to 90 second process-level voice load check."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from load.harness import DEFAULT_SCRATCH, LoadOptions, run_load

pytestmark = pytest.mark.load


@pytest.mark.skipif(
    os.environ.get("PRAMANA_RUN_LOAD") != "1",
    reason="set PRAMANA_RUN_LOAD=1 to run the process-level load test",
)
async def test_short_emulated_load() -> None:
    options = LoadOptions(
        duration_s=75,
        database_url=os.environ.get(
            "PRAMANA_LOAD_DATABASE_URL",
            "postgresql+asyncpg://pramana@localhost:5433/pramana_load_p3_short",
        ),
        scratch_root=DEFAULT_SCRATCH,
        report_dir=(
            Path(os.environ["PRAMANA_LOAD_REPORT_DIR"])
            if os.environ.get("PRAMANA_LOAD_REPORT_DIR")
            else None
        ),
    )
    summary = await run_load(options)

    assert summary["load_duration_seconds"] >= 75
    assert summary["all_investigations_passed"] is True
    assert summary["peak_participant_call_sockets"] == 3
    assert summary["three_call_seconds"] >= 75
    assert summary["websocket_closes"]["unexpected_count"] == 0
