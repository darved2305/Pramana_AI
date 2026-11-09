"""Deployment database boundaries: the private schemas, the grant audit, the runtime roles and
the simulator's durable state."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx
import pytest
import uvicorn
from core_testkit import OPERATOR_KEY, SIGNING_KEY, core_settings, truncate_all
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from db_guard import require_listed_url, setting_database_url
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from test_closing_loop import approve, decided, reset_in_simulator, verify
from test_recovery import assert_identical

from pramana_contracts.tokens import mint, mint_capability, private_key_from_b64, public_key_b64
from pramana_core.db_roles import (
    credentials_work,
    ensure_roles,
    role_passwords,
    role_statement_template,
    scram_verifier,
)
from pramana_core.grant_audit import audit_connection, audit_database, revoke_statements
from pramana_core.main import create_app as create_core_app
from pramana_domain import load_pack
from pramana_domain.spec_storage import spec_digest
from pramana_sim.app import SimSettings, create_app

TEST_DB_URL = setting_database_url("TEST_DATABASE_URL")
KEY = Ed25519PrivateKey.generate()
OPERATOR = {"X-Operator-Key": "deploy-database-test"}
FAULT = {"faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]}
PEOPLE = [
    {"id": "p_riya", "location_id": "F3_R304", "roles": ["student"]},
    {"id": "p_mahesh", "location_id": "GUARD_DESK", "roles": ["guard"]},
    {"id": "p_imran", "location_id": "MAINT_ROOM", "roles": ["electrician"]},
]


def test_direct_test_database_url_is_allowlisted() -> None:
    assert require_listed_url(TEST_DB_URL) == TEST_DB_URL


def test_grant_audit_fails_for_table_and_future_default_access(migrated_db: str) -> None:
    async def check() -> None:
        engine = create_async_engine(TEST_DB_URL)
        try:
            assert await audit_database(TEST_DB_URL, apply_revokes=True) == []
            async with engine.begin() as connection:
                await connection.exec_driver_sql("grant select on pramana.organizations to anon")
            violations = await audit_database(TEST_DB_URL)
            assert any("anon has SELECT on pramana.organizations" in item for item in violations)
            async with engine.begin() as connection:
                await connection.exec_driver_sql("revoke select on pramana.organizations from anon")
                await connection.exec_driver_sql("grant select on pramana.organizations to public")
            violations = await audit_database(TEST_DB_URL)
            assert any("PUBLIC has SELECT on pramana.organizations" in item for item in violations)
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    "revoke select on pramana.organizations from public"
                )
                await connection.exec_driver_sql(
                    "alter default privileges in schema pramana "
                    "grant select on tables to authenticated"
                )
            violations = await audit_database(TEST_DB_URL)
            assert any(
                "default SELECT on pramana objects is granted to authenticated" in item
                for item in violations
            )
        finally:
            await audit_database(TEST_DB_URL, apply_revokes=True)
            await engine.dispose()

    asyncio.run(check())


def test_grant_audit_rejects_privileged_and_owning_runtime_role(migrated_db: str) -> None:
    async def check() -> None:
        engine = create_async_engine(migrated_db)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.exec_driver_sql("alter role pramana_app bypassrls")
                    violations = await audit_connection(connection)
                    assert "runtime role pramana_app is privileged" in violations
                finally:
                    await transaction.rollback()
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.exec_driver_sql(
                        "create table pramana.audit_owner_test (id int)"
                    )
                    await connection.exec_driver_sql(
                        "alter table pramana.audit_owner_test owner to pramana_app"
                    )
                    violations = await audit_connection(connection)
                    assert "pramana_app owns pramana.audit_owner_test" in violations
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

        for role, table in (
            ("pramana_app", "pramana_sim.scenarios"),
            ("pramana_sim", "pramana.organizations"),
        ):
            url = make_url(migrated_db).set(username=role).render_as_string(hide_password=False)
            runtime = create_async_engine(url)
            try:
                async with runtime.connect() as connection:
                    with pytest.raises(DBAPIError):
                        await connection.exec_driver_sql(f"select * from {table} limit 1")
            finally:
                await runtime.dispose()

    asyncio.run(check())


def test_simulator_state_survives_restart_with_seal_and_single_use_replay(
    migrated_db: str,
) -> None:
    sim_url = (
        make_url(migrated_db).set(username="pramana_sim").render_as_string(hide_password=False)
    )
    settings = SimSettings(
        mode="production",
        operator_key=SecretStr(OPERATOR["X-Operator-Key"]),
        participant_public_key=public_key_b64(KEY),
        database_url=sim_url,
        oracle_key=None,
        local_production_test=True,
    )
    pack = load_pack("campus_block_c")
    model = {
        "spec": pack.model_dump(mode="json"),
        "sha256": spec_digest(pack.model_dump(mode="json")).hex(),
    }
    body = {
        "pack_id": "campus_block_c",
        "seed": 3,
        "fault": FAULT,
        "participants": PEOPLE,
        "documented_model": model,
    }

    with TestClient(create_app(settings)) as first:
        created = first.post("/sim/v1/scenarios", headers=OPERATOR, json=body)
        assert created.status_code == 201, created.text
        sid = created.json()["scenario_id"]
        commitment = created.json()["commitment"]
        participant = "Bearer " + mint(KEY, participant_id="p_imran", scenario_id=sid)
        moved = first.post(
            f"/sim/v1/scenarios/{sid}/move",
            headers={"Authorization": participant},
            json={"to": "DB_C2_PANEL"},
        )
        assert moved.status_code == 200, moved.text
        capability, _ = mint_capability(
            KEY,
            scenario_id=sid,
            investigation_id="inv_deploy_test",
            participant_id="p_imran",
            action="reset_breaker",
            target="CB_C2_7",
        )
        before_restart = first.post(
            f"/sim/v1/scenarios/{sid}/observe",
            headers={"Authorization": participant},
            json={"probe_id": "breaker_c2_7"},
        ).json()

    try:
        with (
            TestClient(create_app(settings)) as restarted,
            TestClient(create_app(settings)) as peer,
        ):
            view = restarted.get(
                f"/sim/v1/scenarios/{sid}/view", headers={"Authorization": participant}
            )
            assert view.status_code == 200
            assert view.json()["location_id"] == "DB_C2_PANEL"
            observation = restarted.post(
                f"/sim/v1/scenarios/{sid}/observe",
                headers={"Authorization": participant},
                json={"probe_id": "breaker_c2_7"},
            )
            assert observation.json() == before_restart

            def repair(client: TestClient) -> int:
                return client.post(
                    f"/sim/v1/scenarios/{sid}/act",
                    headers={"Authorization": participant},
                    json={"action": "reset_breaker", "target": "CB_C2_7", "capability": capability},
                ).status_code

            with ThreadPoolExecutor(max_workers=2) as workers:
                statuses = list(workers.map(repair, (restarted, peer)))
            assert sorted(statuses) == [200, 409]
            assert (
                peer.post(
                    f"/sim/v1/scenarios/{sid}/observe",
                    headers={"Authorization": participant},
                    json={"probe_id": "breaker_c2_7"},
                ).json()["value"]
                == "up"
            )
            assert (
                restarted.post(f"/sim/v1/scenarios/{sid}/close", headers=OPERATOR).status_code
                == 204
            )
            reveal = restarted.post(f"/sim/v1/scenarios/{sid}/reveal", headers=OPERATOR)
            assert reveal.json()["commitment"] == commitment
            assert reveal.json()["commitment_verified"] is True
    finally:

        async def remove_scenario() -> None:
            engine = create_async_engine(TEST_DB_URL)
            try:
                async with engine.begin() as connection:
                    await connection.exec_driver_sql(
                        "delete from pramana_sim.scenarios where id = $1", (sid,)
                    )
            finally:
                await engine.dispose()

        asyncio.run(remove_scenario())


def _sim_url(db_url: str) -> str:
    return make_url(db_url).set(username="pramana_sim").render_as_string(hide_password=False)


def test_migration_leaves_only_the_version_table_in_public_and_needs_no_extra_revokes(
    migrated_db: str,
) -> None:
    """The test database grants Supabase's API roles on new public tables by default (as
    Supabase does); after migrating, nothing of Pramana's is reachable by them."""

    async def check() -> None:
        engine = create_async_engine(migrated_db)
        try:
            async with engine.connect() as connection:
                left = await connection.scalars(
                    text(
                        "select c.relname from pg_class c "
                        "join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = 'public' and c.relkind in ('r', 'p', 'S', 'v', 'm')"
                    )
                )
                assert list(left) == ["alembic_version"]
                moved = await connection.scalar(
                    text("select count(*) from pg_tables where schemaname = 'pramana'")
                )
                assert moved >= 26
                assert not await connection.scalar(
                    text(
                        "select has_table_privilege('pramana_app', "
                        "'pramana.investigations', 'DELETE')"
                    )
                )
                assert await audit_connection(connection) == []
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.parametrize(
    ("grant", "expected"),
    [
        ("grant select on pramana.users to service_role", "service_role has SELECT"),
        ("grant usage on pramana.events_seq_seq to anon", "anon has USAGE"),
        ("grant update on pramana.events to pramana_app", "UPDATE on append-only events"),
        (
            "grant delete on pramana.investigations to pramana_app",
            "DELETE on log-owning investigations",
        ),
        ("grant usage on schema pramana to authenticated", "authenticated has USAGE"),
        ("grant select on pramana_sim.scenarios to pramana_app", "pramana_app has access"),
    ],
)
def test_grant_audit_catches_api_roles_cross_reads_and_append_only_writes(
    migrated_db: str, grant: str, expected: str
) -> None:
    async def check() -> None:
        engine = create_async_engine(migrated_db)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.exec_driver_sql(grant)
                    violations = await audit_connection(connection)
                    assert any(expected in item for item in violations), violations
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_revokes_skip_supabase_roles_a_plain_database_does_not_have() -> None:
    plain = " ".join(revoke_statements({"pramana_app", "pramana_sim"}))
    assert not any(role in plain for role in ("anon", "authenticated", "service_role"))
    supabase = " ".join(revoke_statements({"anon", "authenticated", "service_role"}))
    assert "revoke all on all tables in schema pramana from service_role" in supabase
    assert "alter default privileges in schema pramana revoke all on tables from anon" in supabase


def test_scram_verifier_matches_the_rfc_7677_vector() -> None:
    salt = base64.b64decode("W22ZaJ0SNY7soEsUEjb6gQ==")
    verifier = scram_verifier("pencil", salt=salt)
    method, rest = verifier.split("$", 1)
    params, keys = rest.split("$")
    assert method == "SCRAM-SHA-256"
    assert params == "4096:W22ZaJ0SNY7soEsUEjb6gQ=="
    stored_key, server_key = (base64.b64decode(part) for part in keys.split(":"))
    nonce = "rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0"
    auth_message = (
        f"n=user,r=rOprNGfwEbeRWgbNEkqO,r={nonce},s=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096,"
        f"c=biws,r={nonce}"
    ).encode()
    server_signature = hmac.digest(server_key, auth_message, "sha256")
    assert base64.b64encode(server_signature) == b"6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4="
    proof = base64.b64decode("dHzbZapWIk4jUhN+Ute9ytag9zjfMHgsqmmiz7AndVQ=")
    client_signature = hmac.digest(stored_key, auth_message, "sha256")
    client_key = bytes(a ^ b for a, b in zip(proof, client_signature, strict=True))
    assert hashlib.sha256(client_key).digest() == stored_key


def test_runtime_roles_can_be_created_on_postgres(migrated_db: str) -> None:
    async def check() -> None:
        app_url = make_url(migrated_db).set(username="pramana_app", password="app-test-password")
        sim_url = make_url(migrated_db).set(username="pramana_sim", password="sim-test-password")
        await ensure_roles(
            migrated_db,
            app_url.render_as_string(hide_password=False),
            sim_url.render_as_string(hide_password=False),
        )

    asyncio.run(check())


def test_runtime_role_statements_use_safe_managed_postgres_defaults() -> None:
    # Even NOSUPERUSER requires superuser privileges on managed PostgreSQL.
    assert role_statement_template(exists=False) == "create role %I login password %L"
    assert role_statement_template(exists=True) == "alter role %I login password %L"


@pytest.mark.parametrize(
    ("sqlstate", "expected"), [(None, True), ("28P01", False), ("08006", None)]
)
def test_runtime_credential_probe_only_treats_bad_password_as_rotation(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str | None, expected: bool | None
) -> None:
    class OriginalError(Exception):
        pass

    class Connection:
        async def __aenter__(self) -> Connection:
            if sqlstate:
                error = OriginalError()
                error.sqlstate = sqlstate  # type: ignore[attr-defined]
                raise DBAPIError(None, None, error)
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def scalar(self, statement: object) -> int:
            return 1

    class Engine:
        disposed = False

        def connect(self) -> Connection:
            return Connection()

        async def dispose(self) -> None:
            self.disposed = True

    engine = Engine()
    monkeypatch.setattr("pramana_core.db_roles.create_async_engine", lambda *a, **kw: engine)
    if expected is None:
        with pytest.raises(DBAPIError):
            asyncio.run(credentials_work("unused"))
    else:
        assert asyncio.run(credentials_work("unused")) is expected
    assert engine.disposed


def test_working_runtime_credentials_are_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        async def __aenter__(self) -> Connection:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def scalar(self, statement: object, parameters: object = None) -> bool:
            return True

        async def execute(self, statement: object) -> list[object]:
            return []

        async def exec_driver_sql(self, statement: str) -> None:
            pytest.fail("working credentials must not be rewritten")

    class Engine:
        def begin(self) -> Connection:
            return Connection()

        async def dispose(self) -> None:
            pass

    async def works(url: str) -> bool:
        return True

    monkeypatch.setattr("pramana_core.db_roles.create_async_engine", lambda *a, **kw: Engine())
    monkeypatch.setattr("pramana_core.db_roles.credentials_work", works)
    asyncio.run(
        ensure_roles(
            "postgresql://migrator/test",
            "postgresql://pramana_app:a@test/db",
            "postgresql://pramana_sim:b@test/db",
        )
    )


def test_postgres_stores_the_verifier_as_is_so_no_password_reaches_the_server(
    migrated_db: str,
) -> None:
    async def check() -> None:
        engine = create_async_engine(migrated_db)
        verifier = scram_verifier("a-long-runtime-password-for-tests")
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.exec_driver_sql(
                        f"create role pramana_verifier_test login password '{verifier}'"
                    )
                    stored = await connection.scalar(
                        text(
                            "select rolpassword from pg_authid "
                            "where rolname = 'pramana_verifier_test'"
                        )
                    )
                    assert stored == verifier
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.parametrize(
    ("app_url", "sim_url", "message"),
    [
        ("postgresql://pramana_app@h/db", "postgresql://pramana_sim:s@h/db", "passwords"),
        ("postgresql://postgres:a@h/db", "postgresql://pramana_sim:s@h/db", "pramana_app"),
        ("postgresql://pramana_app.ref:a@h/db", "postgresql://other:s@h/db", "pramana_sim"),
        ("postgresql://pramana_app:same@h/db", "postgresql://pramana_sim:same@h/db", "different"),
    ],
)
def test_runtime_role_urls_are_checked_before_any_change(
    app_url: str, sim_url: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        role_passwords(app_url, sim_url)
    assert role_passwords(
        "postgresql://pramana_app.ref:a@h/db", "postgresql://pramana_sim.ref:b@h/db"
    ) == {"pramana_app": "a", "pramana_sim": "b"}


def _documented_body() -> dict[str, object]:
    spec = load_pack("campus_block_c").model_dump(mode="json")
    return {
        "pack_id": "campus_block_c",
        "seed": 1,
        "fault": FAULT,
        "participants": PEOPLE,
        "documented_model": {"spec": spec, "sha256": spec_digest(spec).hex()},
    }


def _remove_scenarios(ids: list[str]) -> None:
    async def remove() -> None:
        engine = create_async_engine(TEST_DB_URL)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("delete from pramana_sim.scenarios where id = any(:ids)"), {"ids": ids}
                )
        finally:
            await engine.dispose()

    asyncio.run(remove())


@contextmanager
def _simulator_server(app: FastAPI) -> Iterator[str]:
    """Run a simulator process on a loop separate from the core test client."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical"))
    thread = threading.Thread(target=server.run, name="durable-simulator-test", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=10)
        raise RuntimeError("simulator test server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("simulator test server did not stop")


def test_a_full_simulator_forgets_closed_worlds_first(migrated_db: str) -> None:
    asyncio.run(_execute(migrated_db, "delete from pramana_sim.scenarios"))
    settings = SimSettings(
        operator_key=SecretStr(OPERATOR["X-Operator-Key"]),
        participant_public_key=public_key_b64(KEY),
        database_url=_sim_url(migrated_db),
        max_scenarios=2,
    )
    created: list[str] = []
    try:
        with TestClient(create_app(settings)) as sim:

            def create() -> str:
                reply = sim.post("/sim/v1/scenarios", headers=OPERATOR, json=_documented_body())
                assert reply.status_code == 201, reply.text
                sid: str = reply.json()["scenario_id"]
                created.append(sid)
                return sid

            create()
            closed = create()
            assert (
                sim.post(f"/sim/v1/scenarios/{closed}/close", headers=OPERATOR).status_code == 204
            )
            create()
            assert sim.get("/ready").json() == {"status": "ready", "database": "ok"}
            alive = []
            for sid in created:
                token = "Bearer " + mint(KEY, participant_id="p_riya", scenario_id=sid)
                view = sim.get(f"/sim/v1/scenarios/{sid}/view", headers={"Authorization": token})
                alive.append(view.status_code)
            assert alive == [200, 404, 200]
    finally:
        _remove_scenarios(created)


async def _execute(db_url: str, statement: str) -> None:
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({}, "SIM_DATABASE_URL"),
        (
            {
                "database_url": "postgresql://pramana_sim:x@db.example.com/postgres",
                "oracle_key": SecretStr("o"),
            },
            "oracle",
        ),
        ({"database_url": "postgresql://pramana_sim@localhost/postgres"}, "remote"),
        (
            {
                "database_url": "postgresql://pramana_sim:x@db.example.com/postgres",
                "state_file": "state.json",
            },
            "PostgreSQL",
        ),
    ],
)
def test_production_simulator_refuses_state_that_would_not_survive(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SimSettings(
            mode="production",
            operator_key=SecretStr("k"),
            participant_public_key=public_key_b64(KEY),
            **overrides,  # type: ignore[arg-type]
        )


def test_investigation_survives_a_simulator_and_core_restart_and_replays_exactly(
    migrated_db: str,
) -> None:
    """Sealed truth and the participants' world live in PostgreSQL: a new simulator process and a
    new core process finish the run, and the event log still replays to the same belief."""
    asyncio.run(truncate_all(migrated_db))
    settings = SimSettings(
        operator_key=SecretStr(OPERATOR_KEY),
        oracle_key=SecretStr("test-oracle-key"),
        participant_public_key=public_key_b64(private_key_from_b64(SIGNING_KEY)),
        database_url=_sim_url(migrated_db),
    )

    first_sim_app = create_app(settings)
    with _simulator_server(first_sim_app) as sim_url, httpx.Client(base_url=sim_url) as sim:
        core_app = create_core_app(core_settings(migrated_db, SIM_URL=sim_url))
        with TestClient(core_app) as core:
            inv = decided(core, sim, "CB_C2_7.tripped")
            assert_identical(core, inv["id"])
            _, aid = approve(core, inv)

    second_sim_app = create_app(settings)
    with _simulator_server(second_sim_app) as sim_url, httpx.Client(base_url=sim_url) as sim:
        core_app = create_core_app(core_settings(migrated_db, SIM_URL=sim_url))
        with TestClient(core_app) as core:
            reset_in_simulator(core, sim, inv["id"], aid)
            state = core.post(
                f"/v1/investigations/{inv['id']}/interventions",
                json={"approval_id": aid, "participant_id": "p_imran"},
            ).json()
            assert verify(core, sim, state)["status"] == "verified"
            assert core.post(f"/v1/investigations/{inv['id']}/reveal").status_code == 200
            rep = assert_identical(core, inv["id"])
            assert rep["status"] == "closed"
