"""Row-level security fails closed (ADR 0015, PRODUCTION.md §4.4 and §12.3).

The runtime role ``pramana_app`` is not a superuser and has no ``BYPASSRLS``; these tests connect
as it. The table owner (``pramana``) is a superuser locally and bypasses RLS, so it only seeds.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from pramana_core import ids
from pramana_core.db import Database, SiteRow, acting_as_job, acting_for
from pramana_core.runtime.recovery import RECOVERY_JOB

APP_ROLE = "pramana_app"


def _as_app(url: str) -> str:
    scheme, _, rest = url.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://{APP_ROLE}@{host}"


async def _role_exists(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(
                text("select rolsuper or rolbypassrls from pg_roles where rolname = :r"),
                {"r": APP_ROLE},
            )
            flags = row.scalar_one_or_none()
        if flags is None:
            return False
        assert flags is False, f"{APP_ROLE} must not be a superuser or bypass RLS"
        return True
    finally:
        await engine.dispose()


def _run(fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    return asyncio.run(fn(*args))


@pytest.fixture
def db_urls(migrated_db: str) -> tuple[str, str]:
    if not _run(_role_exists, migrated_db):
        reason = f"role {APP_ROLE} missing; run `python scripts/dev_db.py start`"
        if os.environ.get("PRAMANA_REQUIRE_APP_ROLE"):
            pytest.fail(reason)  # CI creates the role: a skip there would hide a broken setup
        pytest.skip(reason)
    return migrated_db, _as_app(migrated_db)


async def _engine(url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed_two_orgs(owner_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    a, b = ids.uuid7(), ids.uuid7()
    engine = create_async_engine(owner_url)
    async with engine.begin() as conn:
        for org, slug in ((a, "org-a"), (b, "org-b")):
            slug = f"{slug}-{org.hex[-8:]}"
            await conn.execute(
                text(
                    "insert into organizations (id, slug, name, kind) values (:i, :s, :s, 'campus')"
                ),
                {"i": org, "s": slug},
            )
            await conn.execute(
                text(
                    "insert into sites (id, org_id, name, kind, mode) "
                    "values (:i, :o, 'Block C', 'hostel', 'sandbox')"
                ),
                {"i": ids.uuid7(), "o": org},
            )
    await engine.dispose()
    return a, b


async def _tenant_tables(conn: Any) -> list[str]:
    rows = await conn.execute(
        text(
            "select table_name from information_schema.columns "
            "where table_schema = 'pramana' and column_name = 'org_id' order by table_name"
        )
    )
    return [r[0] for r in rows]


def test_every_table_with_org_id_forces_rls(db_urls: tuple[str, str]) -> None:
    """A new tenant table that forgets RLS fails here."""

    async def check() -> None:
        engine = create_async_engine(db_urls[0])
        async with engine.connect() as conn:
            tables = await _tenant_tables(conn)
            assert {
                "investigations",
                "events",
                "sites",
                "site_models",
                "memberships",
                "consent_links",
            } <= set(tables)
            for table in tables:
                row = await conn.execute(
                    text(
                        "select relrowsecurity, relforcerowsecurity, "
                        "(select count(*) from pg_policies "
                        "where tablename = :t and schemaname = 'pramana') "
                        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where c.relname = :t and c.relkind = 'r' and n.nspname = 'pramana'"
                    ),
                    {"t": table},
                )
                enabled, forced, policies = row.one()
                assert enabled, table
                assert forced, table
                assert policies >= 1, table
        await engine.dispose()

    _run(check)


def test_consent_links_are_scoped_under_runtime_role(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        a, b = await _seed_two_orgs(db_urls[0])
        owner = create_async_engine(db_urls[0])
        async with owner.begin() as conn:
            for org in (a, b):
                site = (
                    await conn.execute(text("select id from sites where org_id=:org"), {"org": org})
                ).scalar_one()
                await conn.execute(
                    text(
                        "insert into site_people (org_id,site_id,id,spec) "
                        "values (:org,:site,'p_test','{}')"
                    ),
                    {"org": org, "site": site},
                )
                await conn.execute(
                    text(
                        "insert into consent_links "
                        "(id,org_id,site_id,person_id,purpose,channel,language,notice_version,"
                        "token_hash,created_by,created_at,expires_at) "
                        "values (:id,:org,:site,'p_test','contact_for_investigations','web',"
                        "'en','1',:hash,'test',now(),now()+interval '1 day')"
                    ),
                    {"id": ids.uuid7(), "org": org, "site": site, "hash": org.bytes},
                )
        await owner.dispose()
        db = Database(create_async_engine(db_urls[1]))
        with acting_for(a):
            async with db.read() as session:
                visible = set(
                    (await session.execute(text("select org_id from consent_links"))).scalars()
                )
                assert visible == {a}
        with acting_for(b):
            async with db.read() as session:
                visible = set(
                    (await session.execute(text("select org_id from consent_links"))).scalars()
                )
                assert visible == {b}
        with acting_for(None):
            async with db.read() as session:
                assert (
                    await session.execute(text("select count(*) from consent_links"))
                ).scalar_one() == 0
        await db.dispose()

    _run(check)


def test_no_context_sees_no_rows(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        await _seed_two_orgs(db_urls[0])
        engine = create_async_engine(db_urls[1])
        async with engine.connect() as conn:
            assert (
                await conn.execute(text("select count(*) from organizations"))
            ).scalar_one() == 0
            for table in await _tenant_tables(conn):
                count = (await conn.execute(text(f"select count(*) from {table}"))).scalar_one()
                assert count == 0, table
        await engine.dispose()

    _run(check)


def test_context_sees_only_its_organization(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        a, b = await _seed_two_orgs(db_urls[0])
        db = Database(create_async_engine(db_urls[1]))
        with acting_for(a):
            async with db.read() as session:
                orgs = {r[0] for r in await session.execute(text("select org_id from sites"))}
        assert orgs == {a}
        with acting_for(b):
            async with db.transaction() as session:
                orgs = {r[0] for r in await session.execute(text("select org_id from sites"))}
        assert orgs == {b}
        await db.dispose()

    _run(check)


def test_cross_tenant_write_fails_with_check(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        a, b = await _seed_two_orgs(db_urls[0])
        db = Database(create_async_engine(db_urls[1]))
        with acting_for(a), pytest.raises(DBAPIError, match="row-level security"):
            async with db.transaction() as session:
                session.add(SiteRow(id=ids.uuid7(), org_id=b, name="x", kind="hostel"))
        # Moving one of A's rows into B is refused too.
        with acting_for(a), pytest.raises(DBAPIError, match="row-level security"):
            async with db.transaction() as session:
                await session.execute(text("update sites set org_id = :b"), {"b": b})
        await db.dispose()

    _run(check)


def test_write_without_context_fails(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        a, _ = await _seed_two_orgs(db_urls[0])
        db = Database(create_async_engine(db_urls[1]))
        with pytest.raises(DBAPIError, match="row-level security"):
            async with db.transaction() as session:
                session.add(SiteRow(id=ids.uuid7(), org_id=a, name="x", kind="hostel"))
        await db.dispose()

    _run(check)


def test_startup_recovery_sees_only_open_candidates_and_cannot_write(
    db_urls: tuple[str, str],
) -> None:
    async def check() -> None:
        orgs = [ids.uuid7(), ids.uuid7()]
        inv_ids = ["inv_recovery_open_a", "inv_recovery_open_b", "inv_recovery_closed"]
        owner = create_async_engine(db_urls[0])
        async with owner.begin() as conn:
            for org_id in orgs:
                await conn.execute(
                    text(
                        "insert into organizations (id, slug, name, kind) "
                        "values (:id, :slug, :slug, 'campus')"
                    ),
                    {"id": org_id, "slug": f"recovery-rls-{org_id.hex[-8:]}"},
                )
            rows = [
                (inv_ids[0], orgs[0], "questioning"),
                (inv_ids[1], orgs[1], "awaiting_approval"),
                (inv_ids[2], orgs[0], "closed"),
            ]
            for inv_id, org_id, status in rows:
                await conn.execute(
                    text(
                        "insert into investigations "
                        "(id, org_id, pack_id, status, scenario_id, commitment, request, version) "
                        "values (:id, :org, 'campus_block_c', :status, 'synthetic-scenario', "
                        "'synthetic-commitment', '{}'::jsonb, 0)"
                    ),
                    {"id": inv_id, "org": org_id, "status": status},
                )
        await owner.dispose()

        db = Database(create_async_engine(db_urls[1]))
        async with db.read() as session:
            assert await session.scalar(text("select count(*) from investigations")) == 0
        with acting_as_job(RECOVERY_JOB):
            async with db.read() as session:
                visible = await session.execute(
                    text("select id from investigations where id = any(:ids) order by id"),
                    {"ids": inv_ids},
                )
                assert set(visible.scalars()) == set(inv_ids[:2])
            async with db.transaction() as session:
                result = await session.execute(
                    text("update investigations set status = 'closed' where id = :id"),
                    {"id": inv_ids[0]},
                )
                assert result.rowcount == 0
        with acting_for(orgs[0]):
            async with db.read() as session:
                status = await session.scalar(
                    text("select status from investigations where id = :id"),
                    {"id": inv_ids[0]},
                )
                assert status == "questioning"
        await db.dispose()

    _run(check)


def test_context_does_not_leak_between_transactions(db_urls: tuple[str, str]) -> None:
    """``set_config(..., true)`` is transaction-local: a pooled connection forgets it."""

    async def check() -> None:
        a, _ = await _seed_two_orgs(db_urls[0])
        engine = create_async_engine(db_urls[1], pool_size=1, max_overflow=0)
        db = Database(engine)
        with acting_for(a):
            async with db.transaction() as session:
                assert (await session.execute(text("select count(*) from sites"))).scalar_one() == 1
        async with db.transaction() as session:  # same pooled connection, no context
            assert (await session.execute(text("select count(*) from sites"))).scalar_one() == 0
        await db.dispose()

    _run(check)


def test_memberships_visible_to_their_user_only(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        a, b = await _seed_two_orgs(db_urls[0])
        owner = create_async_engine(db_urls[0])
        async with owner.begin() as conn:
            for uid in ("u_rls_one", "u_rls_two"):
                await conn.execute(
                    text(
                        "insert into users (id, email, display_name, password_hash, roles, active) "
                        "values (:u, :e, 'x', 'x', '[]', true) on conflict do nothing"
                    ),
                    {"u": uid, "e": f"{uid}@example.test"},
                )
            await conn.execute(
                text(
                    "insert into memberships (org_id, user_id, roles) values "
                    "(:a, 'u_rls_one', array['owner']), (:b, 'u_rls_one', array['viewer']), "
                    "(:b, 'u_rls_two', array['owner'])"
                ),
                {"a": a, "b": b},
            )
        await owner.dispose()
        db = Database(create_async_engine(db_urls[1]))
        with acting_for(None, user_id="u_rls_one"):
            async with db.read() as session:
                rows = set(await session.execute(text("select org_id, user_id from memberships")))
                visible = set(
                    (await session.execute(text("select id from organizations"))).scalars()
                )
        assert rows == {(a, "u_rls_one"), (b, "u_rls_one")}
        assert visible == {a, b}
        with acting_for(None, user_id="u_rls_one"):
            async with db.transaction() as session:
                result = await session.execute(text("delete from memberships returning user_id"))
                assert list(result) == []  # Reading your memberships never grants a write context.
                result = await session.execute(
                    text("update memberships set roles = array['owner'] returning user_id")
                )
                assert list(result) == []
        await db.dispose()

    _run(check)


def test_domain_suggestions_and_join_requests_are_scoped_by_runtime_rls(
    db_urls: tuple[str, str],
) -> None:
    async def check() -> None:
        a, b = await _seed_two_orgs(db_urls[0])
        domain_a, domain_b = f"college-{a.hex[:8]}.example", f"other-{b.hex[:8]}.example"
        requester, another, admin, outsider, unverified = (ids.new("usr")[1] for _ in range(5))
        request_a, request_b = ids.uuid7(), ids.uuid7()
        owner = create_async_engine(db_urls[0])
        async with owner.begin() as conn:
            for uid, email, verified in (
                (requester, f"one@{domain_a}", True),
                (another, f"two@{domain_a}", True),
                (admin, f"admin@{domain_a}", True),
                (outsider, f"person@{domain_b}", True),
                (unverified, f"unverified@{domain_a}", False),
            ):
                await conn.execute(
                    text(
                        "insert into users (id, email, display_name, password_hash, roles, "
                        "active, email_verified_at) values (:id, :email, 'Person', 'x', "
                        "'[]'::jsonb, true, case when :verified then now() else null end)"
                    ),
                    {"id": uid, "email": email, "verified": verified},
                )
            await conn.execute(
                text(
                    "insert into memberships (org_id, user_id, roles) "
                    "values (:org, :uid, '{owner}')"
                ),
                {"org": a, "uid": admin},
            )
            for org, domain, policy in ((a, domain_a, "request"), (b, domain_b, "auto")):
                await conn.execute(
                    text(
                        "insert into org_domains (org_id, domain, verification, verified_at, "
                        "join_policy) values (:org, :domain, 'dns_txt', now(), :policy)"
                    ),
                    {"org": org, "domain": domain, "policy": policy},
                )
            for request_id, org, uid in ((request_a, a, requester), (request_b, b, outsider)):
                await conn.execute(
                    text(
                        "insert into join_requests (id, org_id, requester_id, status) "
                        "values (:id, :org, :uid, 'pending')"
                    ),
                    {"id": request_id, "org": org, "uid": uid},
                )
        await owner.dispose()

        db = Database(create_async_engine(db_urls[1]))
        with acting_for(None, requester, hosted_domain=domain_a):
            async with db.read() as session:
                domains = set(
                    (await session.execute(text("select domain from org_domains"))).scalars()
                )
                orgs = set((await session.execute(text("select id from organizations"))).scalars())
                requests = set(
                    (await session.execute(text("select id from join_requests"))).scalars()
                )
        assert domains == {domain_a}
        assert orgs == {a}
        assert requests == {request_a}

        with acting_for(None, requester, hosted_domain=domain_b):
            async with db.read() as session:
                assert not (await session.execute(text("select domain from org_domains"))).all()
                assert not (await session.execute(text("select id from organizations"))).all()
        with acting_for(a, admin):
            async with db.read() as session:
                requests = set(
                    (await session.execute(text("select id from join_requests"))).scalars()
                )
                domains = set(
                    (await session.execute(text("select domain from org_domains"))).scalars()
                )
        assert requests == {request_a}
        assert domains == {domain_a}

        new_id = ids.uuid7()
        with acting_for(None, another, hosted_domain=domain_a):
            async with db.transaction() as session:
                await session.execute(
                    text(
                        "insert into join_requests (id, org_id, requester_id) "
                        "values (:id, :org, :uid)"
                    ),
                    {"id": new_id, "org": a, "uid": another},
                )
        with (
            acting_for(None, another, hosted_domain=domain_a),
            pytest.raises(DBAPIError, match="requesters may only cancel"),
        ):
            async with db.transaction() as session:
                await session.execute(
                    text(
                        "update join_requests set status = 'cancelled', decided_at = now(), "
                        "org_id = :org, roles = array['admin']::text[] where id = :id"
                    ),
                    {"id": new_id, "org": b},
                )
        with acting_for(None, another, hosted_domain=domain_a):
            async with db.transaction() as session:
                await session.execute(
                    text(
                        "update join_requests set status = 'cancelled', decided_at = now() "
                        "where id = :id"
                    ),
                    {"id": new_id},
                )
        with (
            acting_for(None, another, hosted_domain=domain_a),
            pytest.raises(DBAPIError, match="row-level security"),
        ):
            async with db.transaction() as session:
                await session.execute(
                    text(
                        "insert into join_requests (id, org_id, requester_id) "
                        "values (:id, :org, :uid)"
                    ),
                    {"id": ids.uuid7(), "org": b, "uid": another},
                )
        with (
            acting_for(None, unverified, hosted_domain=domain_a),
            pytest.raises(DBAPIError, match="row-level security"),
        ):
            async with db.transaction() as session:
                await session.execute(
                    text(
                        "insert into join_requests (id, org_id, requester_id) "
                        "values (:id, :org, :uid)"
                    ),
                    {"id": ids.uuid7(), "org": a, "uid": unverified},
                )
        with (
            acting_for(None, outsider, hosted_domain=domain_b),
            pytest.raises(DBAPIError, match="row-level security"),
        ):
            async with db.transaction() as session:
                await session.execute(
                    text(
                        "insert into join_requests (id, org_id, requester_id, status, roles, "
                        "decision_source, decided_at) values (:id, :org, :uid, 'approved', "
                        "array['admin'], 'auto', now())"
                    ),
                    {"id": ids.uuid7(), "org": b, "uid": outsider},
                )
        await db.dispose()

    _run(check)


def test_runtime_role_cannot_rewrite_the_log(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        engine = create_async_engine(db_urls[1])
        # Deleting a parent must not bypass the event DELETE restriction through a cascade.
        for statement in (
            "update events set type = 'x'",
            "delete from events",
            "delete from investigations",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
        await engine.dispose()

    _run(check)


def test_published_site_models_are_immutable(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        a, _ = await _seed_two_orgs(db_urls[0])
        db = Database(create_async_engine(db_urls[1]))
        with acting_for(a):
            async with db.transaction() as session:
                site = (await session.execute(text("select id from sites"))).scalar_one()
                await session.execute(
                    text(
                        "insert into site_models (id, org_id, site_id, version, status, spec, "
                        "spec_sha256) values (:i, :o, :s, 1, 'published', '{}', '\\x00')"
                    ),
                    {"i": ids.uuid7(), "o": a, "s": site},
                )
            with pytest.raises(DBAPIError, match="immutable"):
                async with db.transaction() as session:
                    await session.execute(text("update site_models set spec = '{\"a\": 1}'"))
        await db.dispose()

    _run(check)


def test_runtime_role_cannot_use_purge_flag_to_edit_a_published_model(
    db_urls: tuple[str, str],
) -> None:
    async def check() -> None:
        org, _ = await _seed_two_orgs(db_urls[0])
        db = Database(create_async_engine(db_urls[1]))
        owner = create_async_engine(db_urls[0])
        try:
            with acting_for(org):
                async with db.transaction() as session:
                    site = (await session.execute(text("select id from sites"))).scalar_one()
                    await session.execute(
                        text(
                            "insert into site_models (id,org_id,site_id,version,status,spec,"
                            "spec_sha256,source,validation) values "
                            "(:id,:org,:site,1,'published','{}','\\x00','{}','{}')"
                        ),
                        {"id": ids.uuid7(), "org": org, "site": site},
                    )
                async with owner.begin() as conn:
                    await conn.execute(
                        text(
                            "update organizations set deleted_at=now()-interval '31 days', "
                            "purge_after=now()-interval '1 day' where id=:org"
                        ),
                        {"org": org},
                    )

                async def mutate() -> None:
                    async with db.transaction() as session:
                        await session.execute(
                            text("select set_config('app.purge_personal_data','on',true)")
                        )
                        await session.execute(
                            text("update site_models set source=null, validation=null")
                        )

                with pytest.raises(DBAPIError, match="immutable"):
                    await mutate()
        finally:
            await owner.dispose()
            await db.dispose()

    _run(check)


@pytest.mark.parametrize(
    "statement",
    [
        "update site_models set status = 'draft'",
        "delete from site_models",
        "update site_models set version = 2",
        "update site_models set status = 'retired'; update site_models set spec = '{\"x\": 1}'",
    ],
)
def test_published_model_cannot_be_rewritten(db_urls: tuple[str, str], statement: str) -> None:
    async def check() -> None:
        a, _ = await _seed_two_orgs(db_urls[0])
        db = Database(create_async_engine(db_urls[1]))
        with acting_for(a):
            async with db.transaction() as session:
                site = (await session.execute(text("select id from sites"))).scalar_one()
                await session.execute(
                    text(
                        "insert into site_models (id, org_id, site_id, version, status, spec, "
                        "spec_sha256) values (:i, :o, :s, 1, 'published', '{}', '\\x00')"
                    ),
                    {"i": ids.uuid7(), "o": a, "s": site},
                )

            async def mutate() -> None:
                async with db.transaction() as session:
                    for sql in statement.split(";"):
                        await session.execute(text(sql))

            with pytest.raises(DBAPIError, match="immutable"):
                await mutate()
        await db.dispose()

    _run(check)


def test_model_cannot_reference_another_tenants_site(db_urls: tuple[str, str]) -> None:
    async def check() -> None:
        a, b = await _seed_two_orgs(db_urls[0])
        owner = create_async_engine(db_urls[0])
        async with owner.connect() as conn:
            site_b = (
                await conn.execute(text("select id from sites where org_id = :b"), {"b": b})
            ).scalar_one()
        await owner.dispose()
        db = Database(create_async_engine(db_urls[1]))
        with acting_for(a), pytest.raises(DBAPIError, match="foreign key"):
            async with db.transaction() as session:
                await session.execute(
                    text(
                        "insert into site_models (id, org_id, site_id, version, status, spec, "
                        "spec_sha256) values (:i, :o, :s, 1, 'draft', '{}', '\\x00')"
                    ),
                    {"i": ids.uuid7(), "o": a, "s": site_b},
                )
        await db.dispose()

    _run(check)
