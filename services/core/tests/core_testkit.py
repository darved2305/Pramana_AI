"""Shared builders for core tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

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
        "LLM_EXTRACTOR_PROVIDER": "none",
        "LOG_JSON": False,
        "LOG_LEVEL": "WARNING",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


async def truncate_all(db_url: str) -> None:
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "truncate events, observations, questions, approvals, investigations, voice_usage, "
            "sessions, users, directory_participants "
            "restart identity cascade"
        )
    await engine.dispose()


PEOPLE = [
    {
        "id": "p_riya",
        "display_name": "Riya",
        "roles": ["student"],
        "skill": "lay",
        "location_id": "F3_R304",
        "languages": {
            "stt_candidates": ["hi-IN", "en-IN"],
            "template_language": "hi-en",
            "codemix": True,
        },
    },
    {
        "id": "p_mahesh",
        "display_name": "Mahesh",
        "roles": ["guard"],
        "skill": "access",
        "location_id": "GUARD_DESK",
        "languages": {"stt_candidates": ["mr-IN", "hi-IN"], "template_language": "mr"},
    },
    {
        "id": "p_imran",
        "display_name": "Imran",
        "roles": ["electrician"],
        "skill": "technician",
        "location_id": "MAINT_ROOM",
        "languages": {"stt_candidates": ["hi-IN"], "template_language": "hi"},
    },
]


def body(
    fault: str | None = None,
    people: list[dict[str, Any]] | None = None,
    report: str = "Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha",
) -> dict[str, Any]:
    spec: Any = "random"
    if fault:
        comp, mode = fault.split(".")
        spec = {"faults": [{"component_id": comp, "mode": mode}]}
    return {
        "pack_id": "campus_block_c",
        "participants": people or PEOPLE,
        "report": {"text": report, "reporter_id": "p_riya"},
        "scenario": {"seed": 7, "fault": spec},
    }
