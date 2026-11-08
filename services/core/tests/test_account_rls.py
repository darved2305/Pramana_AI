"""Personal state and pre-organization retry keys fail closed with the runtime role."""

from __future__ import annotations

import asyncio

import pytest
from auth_testkit import _seed
from core_testkit import truncate_all
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core import ids
from pramana_core.db import Database, acting_for

pytestmark = pytest.mark.db


def test_personal_tables_and_retry_keys_are_private_and_fail_closed(migrated_db: str) -> None:
    asyncio.run(truncate_all(migrated_db))
    users = asyncio.run(_seed(migrated_db))
    app_url = (
        make_url(migrated_db)
        .set(username="pramana_app", password=None)
        .render_as_string(hide_password=False)
    )

    async def check() -> None:
        db = Database(create_async_engine(app_url))
        try:
            await db.require_runtime_role()
            for uid in (users["operator"], users["approver"]):
                with acting_for(None, uid):
                    async with db.transaction() as session:
                        await session.execute(
                            text("insert into onboarding_state (user_id) values (:u)"), {"u": uid}
                        )
                        await session.execute(
                            text("insert into user_preferences (user_id) values (:u)"), {"u": uid}
                        )
                        await session.execute(
                            text(
                                "insert into idempotency_keys "
                                "(scope,principal,key,method,path,request_sha256,"
                                "response_status,response_body,response_headers) "
                                "values (:s,:s,'private-scope-0001','POST','/test',"
                                ":hash,200,:body,'{}')"
                            ),
                            {"s": f"user:{uid}", "hash": b"x" * 32, "body": b"{}"},
                        )
            for table in ("onboarding_state", "user_preferences", "idempotency_keys"):
                async with db.read() as session:
                    assert await session.scalar(text(f"select count(*) from {table}")) == 0
                with acting_for(None, users["operator"]):
                    async with db.read() as session:
                        assert await session.scalar(text(f"select count(*) from {table}")) == 1
            with acting_for(None, users["operator"]):
                with pytest.raises(DBAPIError, match="row-level security"):
                    async with db.transaction() as session:
                        await session.execute(
                            text("insert into onboarding_state (user_id) values ('other-user')")
                        )
                with pytest.raises(DBAPIError, match="row-level security"):
                    async with db.transaction() as session:
                        await session.execute(
                            text(
                                "update idempotency_keys set principal='user:other-user',"
                                "scope='user:other-user'"
                            )
                        )
            with pytest.raises(DBAPIError, match="permission denied"):
                async with db.transaction() as session:
                    await session.execute(text("update model_templates set version=2"))
        finally:
            await db.dispose()

    asyncio.run(check())


def test_database_also_rejects_unverified_organization_creator(migrated_db: str) -> None:
    asyncio.run(truncate_all(migrated_db))
    users = asyncio.run(_seed(migrated_db))
    app_url = (
        make_url(migrated_db)
        .set(username="pramana_app", password=None)
        .render_as_string(hide_password=False)
    )

    async def check() -> None:
        owner = create_async_engine(migrated_db)
        db = Database(create_async_engine(app_url))
        try:
            async with owner.begin() as conn:
                await conn.execute(
                    text("update users set email_verified_at=null where id=:u"),
                    {"u": users["operator"]},
                )
            org_id = ids.uuid7()
            with (
                acting_for(org_id, users["operator"]),
                pytest.raises(DBAPIError, match="row-level security"),
            ):
                async with db.transaction() as session:
                    await session.execute(
                        text(
                            "insert into organizations (id,slug,name,kind,created_by) "
                            "values (:id,'unverified-workspace','Unverified','campus',:u)"
                        ),
                        {"id": org_id, "u": users["operator"]},
                    )
        finally:
            await owner.dispose()
            await db.dispose()

    asyncio.run(check())
