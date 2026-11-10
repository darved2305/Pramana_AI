"""Start a real simulator or core for the browser end-to-end tests.

    uv run python tests-real/backend.py sim
    uv run python tests-real/backend.py core   # recreates the test database first

Configuration comes from the environment set by playwright.real.config.ts: fresh keys for
every run, a dedicated database (``E2E_DATABASE``, never the development one) and test users.
Nothing here is mocked: the core talks to the simulator over HTTP and to PostgreSQL.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[3]
CORE_DIR = ROOT / "services" / "core"
sys.path.insert(0, str(ROOT / "scripts"))

from db_guard import (  # noqa: E402
    DatabaseGuardError,
    require_listed_database,
    require_listed_url,
)


def _database_name(environment: Mapping[str, str] | None = None) -> str:
    env = os.environ if environment is None else environment
    name = env.get("E2E_DATABASE", "").strip()
    if not name:
        raise SystemExit("refusing to reset a database: set E2E_DATABASE explicitly")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) or not name.endswith("_e2e"):
        raise SystemExit("refusing to reset a database: E2E_DATABASE must be a dedicated _e2e name")
    try:
        # The browser run passes its settings explicitly, so this checkout's .env is not read.
        return require_listed_database(name, environ=env, dotenv_path=None)
    except DatabaseGuardError as error:
        raise SystemExit(str(error)) from error


def _db_url() -> str:
    name = _database_name()
    port = os.environ.get("PRAMANA_DB_PORT", "5433")
    return f"postgresql+asyncpg://pramana@localhost:{port}/{name}"


async def _recreate_database(url: str) -> None:
    """Drop and create the listed test database. A downgrade cannot reset it: migration 0004
    narrows ``investigations.status`` back to 16 characters, which fails on rows left by a run."""
    from sqlalchemy.ext.asyncio import create_async_engine

    name = require_listed_url(url, dotenv_path=None).rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) or not name.endswith("_e2e"):
        raise SystemExit("refusing to reset a database: E2E_DATABASE must be a dedicated _e2e name")
    admin = url.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        await engine.dispose()


def _migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(CORE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))
    cfg.attributes["url"] = require_listed_url(url, dotenv_path=None)
    command.upgrade(cfg, "head")


async def _users(url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from pramana_contracts import StaffRole
    from pramana_core.auth.service import AuthService, LoginThrottle
    from pramana_core.db import Database

    db = Database(create_async_engine(url))
    try:
        svc = AuthService(db, 3600, LoginThrottle(50, 60))
        password = os.environ["E2E_PASSWORD"]
        await svc.create_user("operator@e2e.test", "Olu Operator", password, [StaffRole.OPERATOR])
        await svc.create_user("approver@e2e.test", "Asha Approver", password, [StaffRole.APPROVER])
    finally:
        await db.dispose()


def main() -> None:
    which = sys.argv[1]
    if which == "sim":
        os.environ["SIM_PORT"] = os.environ.get("E2E_SIM_PORT", "8120")
        uvicorn.run(
            "pramana_sim.app:create_app",
            factory=True,
            host="127.0.0.1",
            port=int(os.environ["SIM_PORT"]),
            log_level="warning",
            timeout_keep_alive=65,  # see pramana_core.__main__
        )
        return
    if which != "core":
        raise SystemExit("usage: backend.py sim|core")
    url = _db_url()
    asyncio.run(_recreate_database(url))
    _migrate(url)
    asyncio.run(_users(url))
    os.environ["DATABASE_URL"] = url
    uvicorn.run(
        "pramana_core.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=int(os.environ.get("E2E_CORE_PORT", "8020")),
        log_level="warning",
        timeout_keep_alive=65,  # see pramana_core.__main__
    )


if __name__ == "__main__":
    main()
