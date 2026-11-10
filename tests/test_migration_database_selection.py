"""A migration selected by Alembic must leave another checkout database untouched."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config
from db_guard import setting_database_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "services" / "core"


def test_migrations_change_only_the_explicit_database() -> None:
    selected_url = setting_database_url("TEST_DATABASE_URL")
    sentinel_url = setting_database_url("DATABASE_URL")
    assert urlsplit(selected_url).path != urlsplit(sentinel_url).path

    async def sentinel(action: str) -> str | None:
        engine = create_async_engine(sentinel_url)
        try:
            async with engine.begin() as connection:
                if action == "install":
                    await connection.exec_driver_sql("drop table if exists public.b3_db_sentinel")
                    await connection.exec_driver_sql(
                        "create table public.b3_db_sentinel (value text not null)"
                    )
                    await connection.exec_driver_sql(
                        "insert into public.b3_db_sentinel values ('untouched')"
                    )
                    return None
                if action == "remove":
                    await connection.exec_driver_sql("drop table if exists public.b3_db_sentinel")
                    return None
                result = await connection.execute(text("select value from public.b3_db_sentinel"))
                return str(result.scalar_one())
        finally:
            await engine.dispose()

    async def selected_version() -> str:
        engine = create_async_engine(selected_url)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text("select version_num from public.alembic_version")
                )
                return str(result.scalar_one())
        finally:
            await engine.dispose()

    config = Config(str(CORE / "alembic.ini"))
    config.set_main_option("script_location", str(CORE / "alembic"))
    config.attributes["url"] = selected_url
    try:
        asyncio.run(sentinel("install"))
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        assert asyncio.run(selected_version()) == "0022"
        assert asyncio.run(sentinel("read")) == "untouched"
    finally:
        with suppress(Exception):
            command.upgrade(config, "head")
        asyncio.run(sentinel("remove"))
