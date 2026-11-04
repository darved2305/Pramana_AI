"""Shared builders for core tests."""

from __future__ import annotations

from pramana_contracts.tokens import generate_private_key_b64
from pramana_core.settings import Settings

SIGNING_KEY = generate_private_key_b64()
OPERATOR_KEY = "test-operator-key"


def core_settings(db_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "PRAMANA_MODE": "test",
        "DATABASE_URL": db_url,
        "SIM_URL": "http://sim.test",
        "SIM_OPERATOR_KEY": OPERATOR_KEY,
        "PARTICIPANT_SIGNING_KEY": SIGNING_KEY,
        "GNANI_API_KEY": "",
        "LOG_JSON": False,
        "LOG_LEVEL": "WARNING",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]
