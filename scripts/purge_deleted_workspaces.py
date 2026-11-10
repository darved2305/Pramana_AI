"""Purge workspaces whose 30-day restore window has ended.

Run daily with a dedicated maintenance database connection that can bypass tenant RLS:
    uv run python scripts/purge_deleted_workspaces.py

Never run this script with the web service's runtime database credentials.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core.db import Database
from pramana_core.settings import Settings
from pramana_core.workspace_lifecycle import purge_deleted_organizations


async def run() -> int:
    engine = create_async_engine(Settings().database_url)
    db = Database(engine)
    try:
        async with engine.connect() as connection:
            role = (
                await connection.execute(
                    text(
                        "select current_user, rolsuper, rolbypassrls "
                        "from pg_roles where rolname = current_user"
                    )
                )
            ).one()
        if not role.rolsuper and not role.rolbypassrls:
            raise RuntimeError(
                "workspace purge requires a dedicated maintenance role with RLS bypass; "
                "the runtime role is not allowed"
            )
        return await purge_deleted_organizations(db)
    finally:
        await db.dispose()


if __name__ == "__main__":
    print(f"Purged {asyncio.run(run())} expired workspaces.")
