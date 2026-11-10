"""A migration selected by Alembic must leave another checkout database untouched."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from db_guard import setting_database_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "services" / "core"


def test_migrations_change_only_the_explicit_database() -> None:
    # The sentinel is the allowlisted e2e database: CI and every checkout list it, and CI has no
    # DATABASE_URL, so the test does not depend on the runtime database setting.
    selected_url = setting_database_url("TEST_DATABASE_URL")
    sentinel_url = setting_database_url("PRAMANA_E2E_DATABASE_URL")
    assert urlsplit(selected_url).path != urlsplit(sentinel_url).path
    sentinel_table = f"b3_db_sentinel_{uuid4().hex}"

    async def sentinel(action: str) -> str | None:
        engine = create_async_engine(sentinel_url)
        try:
            async with engine.begin() as connection:
                if action == "install":
                    await connection.exec_driver_sql(
                        f"create table public.{sentinel_table} (value text not null)"
                    )
                    await connection.exec_driver_sql(
                        f"insert into public.{sentinel_table} values ('untouched')"
                    )
                    return None
                if action == "remove":
                    await connection.exec_driver_sql(
                        f"drop table if exists public.{sentinel_table}"
                    )
                    return None
                result = await connection.execute(
                    text(f"select value from public.{sentinel_table}")
                )
                return str(result.scalar_one())
        finally:
            await engine.dispose()

    async def version(url: str) -> str | None:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                if (
                    await connection.scalar(text("select to_regclass('public.alembic_version')"))
                    is None
                ):
                    return None
                return str(
                    await connection.scalar(text("select version_num from public.alembic_version"))
                )
        finally:
            await engine.dispose()

    config = Config(str(CORE / "alembic.ini"))
    config.set_main_option("script_location", str(CORE / "alembic"))
    config.attributes["url"] = selected_url
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    try:
        asyncio.run(sentinel("install"))
        sentinel_version = asyncio.run(version(sentinel_url))
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        assert asyncio.run(version(selected_url)) == head
        assert asyncio.run(version(sentinel_url)) == sentinel_version
        assert asyncio.run(sentinel("read")) == "untouched"
    finally:
        with suppress(Exception):
            command.upgrade(config, "head")
        asyncio.run(sentinel("remove"))
