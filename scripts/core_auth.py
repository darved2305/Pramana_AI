"""Headers that let a developer script act on a core that enforces sign-in (ADR 0010).

Scripts authenticate with ``X-Automation-Key`` (operator + approver). The key is read from the
environment or from the repository's ``.env`` (``scripts/dev_env.py`` generates it) and is never
printed.
"""

from __future__ import annotations

import os
from pathlib import Path

from pramana_core.llm import read_env_file

ROOT = Path(__file__).resolve().parents[1]


def automation_headers() -> dict[str, str]:
    key = os.environ.get("CORE_AUTOMATION_KEY") or read_env_file(ROOT / ".env").get(
        "CORE_AUTOMATION_KEY", ""
    )
    return {"X-Automation-Key": key} if key else {}
