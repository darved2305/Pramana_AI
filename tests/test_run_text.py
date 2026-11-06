"""The live and demo rehearsal CLIs share participant and answer helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_text_investigation import PEOPLE as RUN_PEOPLE  # noqa: E402
from text_investigation import PEOPLE as SHARED_PEOPLE  # noqa: E402


def test_live_text_runner_uses_shared_simulator_participants() -> None:
    assert RUN_PEOPLE is SHARED_PEOPLE
