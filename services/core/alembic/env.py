"""Alembic environment: async engine, URL from DATABASE_URL (never from alembic.ini)."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core.db import Base
from pramana_core.migrations import migration_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _url() -> str:
    return migration_database_url(
        config.attributes.get("url"),
        os.environ.get("DATABASE_URL"),
        Path(__file__).resolve().parents[3] / ".env",
    )


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        # Set per session, not as a startup setting: the Supabase pooler drops those. Until 0019
        # creates ``pramana`` new objects land in ``public``; 0019 moves them.
        await conn.exec_driver_sql("set search_path to pramana, public")
        await conn.commit()  # a session-level SET outlives this transaction
        await conn.run_sync(_run)
        await conn.commit()
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_async())
