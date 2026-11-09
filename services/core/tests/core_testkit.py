"""Shared builders for core tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

from pramana_contracts.tokens import generate_private_key_b64
from pramana_core.settings import Settings

SIGNING_KEY = generate_private_key_b64()
OPERATOR_KEY = "test-operator-key"
DEMO_ORG_ID = "019a5e00-0000-7000-8000-000000000001"
DEMO_SITE_ID = "019a5e00-0000-7000-8000-000000000011"
DEMO_MODEL_ID = "019a5e00-0000-7000-8000-000000000012"
"""Created by migration 0008; owns every row written without an organization context."""


def core_settings(db_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "PRAMANA_MODE": "test",
        "DATABASE_URL": db_url,
        "SIM_URL": "http://sim.test",
        "SIM_OPERATOR_KEY": OPERATOR_KEY,
        "PARTICIPANT_SIGNING_KEY": SIGNING_KEY,
        "GNANI_API_KEY": "",
        "LLM_EXTRACTOR_PROVIDER": "none",
        "TTS_CACHE_DIR": "",  # each test counts its own synthesis
        "LOG_JSON": False,
        "LOG_LEVEL": "WARNING",
        "GOOGLE_OAUTH_CLIENT_ID": "",
        "GOOGLE_OAUTH_CLIENT_SECRET": "",
    }
    values.update(overrides)
    # Ignore the checkout's .env: a test's settings are only what the test states.
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


async def truncate_all(db_url: str) -> None:
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "truncate events, observations, questions, approvals, investigations, voice_usage, "
            "sessions, users, directory_participants "
            "restart identity cascade"
        )
        # The cascade through ``users`` also empties ``organizations`` (``created_by``). Rows
        # written without an organization context belong to the demo organization: restore it.
        has_orgs = await conn.exec_driver_sql("select to_regclass('organizations') is not null")
        if has_orgs.scalar():
            await conn.exec_driver_sql(
                f"insert into organizations (id, slug, name, kind) values "
                f"('{DEMO_ORG_ID}', 'pramana-demo', 'Pramana demo', 'campus') "
                "on conflict (id) do nothing"
            )
        has_limits = await conn.exec_driver_sql("select to_regclass('rate_limits') is not null")
        if has_limits.scalar():
            await conn.exec_driver_sql("truncate rate_limits")
        has_templates = await conn.exec_driver_sql(
            "select to_regclass('model_templates') is not null"
        )
        if has_templates.scalar():
            await conn.exec_driver_sql(
                f"insert into sites (id,org_id,name,kind,mode) values "
                f"('{DEMO_SITE_ID}','{DEMO_ORG_ID}',"
                "'Sample hostel (simulated)','hostel','sandbox') "
                "on conflict do nothing"
            )
            await conn.exec_driver_sql(
                "insert into site_models "
                "(id,org_id,site_id,version,status,spec,spec_sha256,published_at) "
                f"select '{DEMO_MODEL_ID}','{DEMO_ORG_ID}','{DEMO_SITE_ID}',1,'published',"
                "spec,spec_sha256,now() from model_templates where purpose = 'sandbox' "
                "order by version desc limit 1 on conflict do nothing"
            )
            await conn.exec_driver_sql(
                f"update sites set current_model_id = '{DEMO_MODEL_ID}' where id = '{DEMO_SITE_ID}'"
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
