"""The migration chain has exactly one head, so ``alembic upgrade head`` is unambiguous.

Reads the revision scripts only; no database is needed.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

CORE = Path(__file__).resolve().parents[1]


def test_alembic_has_a_single_head() -> None:
    config = Config(str(CORE / "alembic.ini"))
    config.set_main_option("script_location", str(CORE / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"alembic has several heads, so upgrade head is ambiguous: {heads}"
