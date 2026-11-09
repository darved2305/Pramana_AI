from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

BACKEND_PATH = Path(__file__).with_name("backend.py")
SPEC = importlib.util.spec_from_file_location("real_e2e_backend", BACKEND_PATH)
assert SPEC is not None and SPEC.loader is not None
BACKEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKEND)


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            "E2E_DATABASE": "pramana_web_e2e",
            "PRAMANA_DB_NAMES": "pramana_tn,pramana_tn_test,pramana_tn_e2e",
        },
        {"E2E_DATABASE": "pramana_tn", "PRAMANA_DB_NAMES": "pramana_tn"},
    ],
)
def test_database_reset_requires_explicit_allowlisted_e2e_name(environment: dict[str, str]) -> None:
    with pytest.raises(SystemExit):
        BACKEND._database_name(environment)


def test_database_reset_accepts_the_worktree_e2e_database() -> None:
    assert (
        BACKEND._database_name(
            {
                "E2E_DATABASE": "pramana_tn_e2e",
                "PRAMANA_DB_NAMES": "pramana_tn,pramana_tn_test,pramana_tn_e2e",
            }
        )
        == "pramana_tn_e2e"
    )
