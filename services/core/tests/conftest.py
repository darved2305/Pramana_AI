"""Core test harness: real PostgreSQL (``pramana_test``) and the real simulator app in-process.

Start the database with ``python scripts/dev_db.py start``. Tests needing it are skipped with an
explicit reason when it is unreachable, never silently passed.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from core_testkit import OPERATOR_KEY, SIGNING_KEY, core_settings, truncate_all
from db_guard import require_listed_url, setting_database_url
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_contracts.tokens import private_key_from_b64, public_key_b64
from pramana_core.main import create_app
from pramana_sim.app import SimSettings
from pramana_sim.app import create_app as create_sim_app

CORE_DIR = Path(__file__).resolve().parents[1]


async def _reachable(url: str) -> bool:
    engine = create_async_engine(url, connect_args={"timeout": 2})
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("select 1")
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _alembic(action: str, url: str) -> None:
    cfg = Config(str(CORE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))
    cfg.attributes["url"] = require_listed_url(url)
    if action == "upgrade":
        command.upgrade(cfg, "head")
    else:
        command.downgrade(cfg, "base")


@pytest.fixture(scope="session")
def migrated_db() -> str:
    # Refused before any connection: no URL, or a database this checkout does not allowlist.
    url = setting_database_url("TEST_DATABASE_URL")
    if not asyncio.run(_reachable(url)):
        pytest.skip("PostgreSQL test database unreachable; run `python scripts/dev_db.py start`")
    # Rows left by an earlier run (a status like "awaiting_approval") would not fit the older,
    # narrower columns the downgrade passes through.
    with contextlib.suppress(Exception):  # a fresh database has no tables yet
        asyncio.run(truncate_all(url))
    _alembic("downgrade", url)
    _alembic("upgrade", url)
    return url


@pytest.fixture
def sim_app() -> FastAPI:
    return create_sim_app(
        SimSettings(
            operator_key=SecretStr(OPERATOR_KEY),
            oracle_key=SecretStr("test-oracle-key"),
            participant_public_key=public_key_b64(private_key_from_b64(SIGNING_KEY)),
        )
    )


@pytest.fixture
def core(migrated_db: str, sim_app: FastAPI) -> Iterator[TestClient]:
    asyncio.run(truncate_all(migrated_db))
    app = create_app(core_settings(migrated_db), sim_transport=httpx.ASGITransport(app=sim_app))
    with TestClient(app) as client:
        client.sim_app = sim_app  # type: ignore[attr-defined]
        yield client
