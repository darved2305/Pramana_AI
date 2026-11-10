"""Reap 72-hour retry records within one principal/organization scope.

Run with the runtime DATABASE_URL, for example:
uv run python scripts/reap_idempotency.py --user usr_... [--org org_...]
Scheduling this maintenance command is part of the worker deployment.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core import ids
from pramana_core.db import Database, acting_for
from pramana_core.idempotency import reap_expired
from pramana_core.settings import Settings


async def run(user: str, organization: str | None) -> None:
    org = ids.decode("org", organization) if organization else None
    db = Database(create_async_engine(Settings().database_url))
    try:
        await db.require_runtime_role()
        with acting_for(org, user):
            count = await reap_expired(db)
        print(f"Removed {count} expired idempotency records.")
    finally:
        await db.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True)
    parser.add_argument("--org")
    args = parser.parse_args()
    asyncio.run(run(args.user, args.org))
