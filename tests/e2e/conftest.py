"""Fixtures for the live end-to-end tests; the machinery is in ``harness.py``."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from e2e.harness import (
    CORE_PORT,
    DB_URL,
    SIM_PORT,
    Process,
    Services,
    ensure_database,
    migrate,
    port_free,
)

from pramana_contracts.tokens import generate_private_key_b64, private_key_from_b64, public_key_b64


@pytest.fixture(scope="session")
def services() -> Iterator[Services]:
    if os.environ.get("PRAMANA_SKIP_E2E") == "1":
        pytest.skip("PRAMANA_SKIP_E2E=1")
    try:
        asyncio.run(ensure_database(DB_URL))
    except Exception as exc:  # unreachable server, wrong credentials
        pytest.skip(f"PostgreSQL for e2e unreachable ({type(exc).__name__}); run make db-up")
    for port in (CORE_PORT, SIM_PORT):
        if not port_free(port):
            pytest.fail(f"port {port} is in use; set PRAMANA_E2E_CORE_PORT / PRAMANA_E2E_SIM_PORT")
    migrate(DB_URL)

    signing = generate_private_key_b64()
    operator, oracle = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    automation = secrets.token_urlsafe(24)
    work = Path(tempfile.mkdtemp(prefix="pramana-e2e-"))  # no .env here: settings come from env
    base = {k: v for k, v in os.environ.items() if not k.startswith(("SIM_", "GNANI_", "LLM_"))}
    base |= {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    sim_env = base | {
        "SIM_PORT": str(SIM_PORT),
        "SIM_OPERATOR_KEY": operator,
        "SIM_ORACLE_KEY": oracle,
        "SIM_PARTICIPANT_PUBLIC_KEY": public_key_b64(private_key_from_b64(signing)),
    }
    core_env = base | {
        "CORE_PORT": str(CORE_PORT),
        "PRAMANA_MODE": "dev",
        "DATABASE_URL": DB_URL,
        "SIM_URL": f"http://127.0.0.1:{SIM_PORT}",
        "SIM_OPERATOR_KEY": operator,
        "PARTICIPANT_SIGNING_KEY": signing,
        "CORE_AUTOMATION_KEY": automation,
        "GNANI_API_KEY": "",
        "LLM_EXTRACTOR_PROVIDER": "none",
        "LLM_CACHE_DIR": str(work / "llm"),
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
    }
    svc = Services(
        core_url=f"http://127.0.0.1:{CORE_PORT}",
        sim_url=f"http://127.0.0.1:{SIM_PORT}",
        signing_key=signing,
        operator_key=operator,
        oracle_key=oracle,
        automation_key=automation,
        sim=Process("sim", [sys.executable, "-m", "pramana_sim"], sim_env, work, work / "sim.log"),
        core=Process(
            "core", [sys.executable, "-m", "pramana_core"], core_env, work, work / "core.log"
        ),
    )
    try:
        svc.sim.start()
        svc.wait_ready(svc.sim, f"{svc.sim_url}/health")
        svc.core.start()
        svc.wait_ready(svc.core, f"{svc.core_url}/ready")
        yield svc
    finally:
        svc.core.kill()
        svc.sim.kill()


@pytest.fixture
def core(services: Services) -> Iterator[httpx.Client]:
    with services.client(services.core_url) as c:
        yield c


@pytest.fixture
def sim(services: Services) -> Iterator[httpx.Client]:
    with services.client(services.sim_url) as c:
        yield c
