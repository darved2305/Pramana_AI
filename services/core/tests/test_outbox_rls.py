"""The email outbox is tenant-scoped for administrators and cross-tenant only for its relay."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from test_tenancy_rls import _as_app

from pramana_core import ids
from pramana_core.db import Database, acting_as_job, acting_for
from pramana_core.outbox import RELAY_JOB

pytestmark = pytest.mark.db


def test_outbox_rows_are_visible_only_inside_their_organization(migrated_db: str) -> None:
    async def run() -> None:
        orgs = [ids.uuid7(), ids.uuid7()]
        invitation_ids = [ids.uuid7(), ids.uuid7()]
        outbox_ids = [ids.uuid7(), ids.uuid7()]
        owner = create_async_engine(migrated_db)
        async with owner.begin() as conn:
            for index, org_id in enumerate(orgs):
                await conn.execute(
                    text(
                        "insert into organizations (id, slug, name, kind) "
                        "values (:id, :slug, :slug, 'campus')"
                    ),
                    {"id": org_id, "slug": f"outbox-rls-{org_id.hex[-8:]}"},
                )
                await conn.execute(
                    text(
                        "insert into invitations "
                        "(id, org_id, email, roles, token_hash, expires_at) "
                        "values (:id, :org, :email, array['viewer'], :secret, "
                        "now() + interval '1 day')"
                    ),
                    {
                        "id": invitation_ids[index],
                        "org": org_id,
                        "email": f"person{index}@example.test",
                        "secret": bytes([index + 1]) * 32,
                    },
                )
                await conn.execute(
                    text(
                        "insert into email_outbox "
                        "(id, org_id, invitation_id, state, attempts, available_at, dead_at, "
                        "last_error) "
                        "values (:id, :org, :invite, 'dead', 0, now(), now(), 'EmailNotConfigured')"
                    ),
                    {"id": outbox_ids[index], "org": org_id, "invite": invitation_ids[index]},
                )
                await conn.execute(
                    text(
                        "insert into email_outbox_attempts "
                        "(org_id, outbox_id, attempt, finished_at, result) "
                        "values (:org, :outbox, 1, now(), 'sent')"
                    ),
                    {"org": org_id, "outbox": outbox_ids[index]},
                )
        await owner.dispose()

        db = Database(create_async_engine(_as_app(migrated_db)))
        async with db.read() as session:
            assert await session.scalar(text("select count(*) from email_outbox")) == 0
        for org_id, expected in ((orgs[0], outbox_ids[0]), (orgs[1], outbox_ids[1])):
            with acting_for(org_id):
                async with db.read() as session:
                    visible = await session.scalars(text("select id from email_outbox"))
                    assert list(visible) == [expected]
                    attempts = await session.scalars(
                        text("select outbox_id from email_outbox_attempts")
                    )
                    assert list(attempts) == [expected]
        with acting_as_job(RELAY_JOB):
            async with db.read() as session:
                all_outbox = await session.scalars(
                    text(
                        "select id from email_outbox where org_id in (:first, :second) order by id"
                    ),
                    {"first": orgs[0], "second": orgs[1]},
                )
                assert set(all_outbox) == set(outbox_ids)
                all_attempts = await session.scalars(
                    text(
                        "select outbox_id from email_outbox_attempts "
                        "where org_id in (:first, :second) order by outbox_id"
                    ),
                    {"first": orgs[0], "second": orgs[1]},
                )
                assert set(all_attempts) == set(outbox_ids)
        with acting_as_job("personal-data-backfill"):
            async with db.read() as session:
                assert await session.scalar(text("select count(*) from email_outbox")) == 0
                assert await session.scalar(text("select count(*) from email_outbox_attempts")) == 0
        await db.dispose()

    asyncio.run(run())
