"""Revoke API-facing grants and fail closed if a runtime role can cross its boundary."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from .migrations import require_database_name

API_ROLES = ("anon", "authenticated", "service_role")
"""Supabase's Data API roles (``service_role`` bypasses RLS). They must reach nothing of
Pramana's. Plain PostgreSQL has none of them; the audit then checks only what exists."""
RUNTIME_ROLES = ("pramana_app", "pramana_sim")
SCHEMAS = ("pramana", "pramana_sim")
FORBIDDEN = {"pramana": "pramana_sim", "pramana_sim": "pramana_app"}
"""The runtime role that must not reach each schema: the core never reads sealed truth."""
APPEND_ONLY = ("events",)
"""Tables the core runtime role may only insert into and read (ADR 0015)."""
NO_DELETE = ("investigations",)
"""Deleting a parent investigation would cascade and erase its sealed event log."""
_KINDS = ("tables", "sequences", "functions")


def revoke_statements(present_roles: Iterable[str]) -> list[str]:
    """Revokes to re-run after every migration: Supabase grants its API roles on new objects."""
    present = set(present_roles)
    statements = ["revoke all on public.alembic_version from public"]
    for schema in SCHEMAS:
        statements.append(f"revoke all on schema {schema} from public")
        statements += [
            f"revoke all on all {kind} in schema {schema} from public" for kind in _KINDS
        ]
    statements.append("alter default privileges revoke execute on functions from public")
    for role in (r for r in API_ROLES if r in present):
        statements.append(f"revoke all on public.alembic_version from {role}")
        statements += [
            f"alter default privileges revoke all on {kind} from {role}" for kind in _KINDS
        ]
        for schema in SCHEMAS:
            statements.append(f"revoke all on schema {schema} from {role}")
            for kind in _KINDS:
                statements.append(f"revoke all on all {kind} in schema {schema} from {role}")
                statements.append(
                    f"alter default privileges in schema {schema} revoke all on {kind} from {role}"
                )
    for schema, role in FORBIDDEN.items():
        if role in present:
            statements.append(f"revoke all on schema {schema} from {role}")
            statements += [
                f"revoke all on all {kind} in schema {schema} from {role}" for kind in _KINDS
            ]
    for role in (r for r in RUNTIME_ROLES if r in present):
        statements.append(f"revoke all on public.alembic_version from {role}")
    return statements


class GrantAuditError(RuntimeError):
    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(violations)
        super().__init__("database grant audit failed: " + "; ".join(self.violations))


async def audit_connection(
    connection: AsyncConnection, *, apply_revokes: bool = False
) -> list[str]:
    """Audit a SQLAlchemy async connection. Apply revokes first when this follows migration."""
    violations: list[str] = []
    present = set(
        await connection.scalars(
            text("select rolname from pg_roles where rolname = any(:names)"),
            {"names": [*API_ROLES, *RUNTIME_ROLES]},
        )
    )
    if apply_revokes:
        for statement in revoke_statements(present):
            await connection.exec_driver_sql(statement)
    api_roles = sorted(present & set(API_ROLES))
    reachers = ", ".join(f"'{role}'" for role in [*api_roles, "PUBLIC"])

    roles = await connection.execute(
        text(
            "select rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole from pg_roles "
            "where rolname in ('pramana_app', 'pramana_sim')"
        )
    )
    role_rows = {row.rolname: row for row in roles}
    for required in RUNTIME_ROLES:
        if required not in role_rows:
            violations.append(f"required database role {required} is missing")
    for runtime in ("pramana_app", "pramana_sim"):
        row = role_rows.get(runtime)
        if row is not None and (
            row.rolsuper or row.rolbypassrls or row.rolcreatedb or row.rolcreaterole
        ):
            violations.append(f"runtime role {runtime} is privileged")

    memberships = await connection.execute(
        text(
            "select member.rolname as member, parent.rolname as parent from pg_auth_members m "
            "join pg_roles member on member.oid = m.member "
            "join pg_roles parent on parent.oid = m.roleid "
            "where member.rolname in ('pramana_app', 'pramana_sim')"
        )
    )
    for row in memberships:
        violations.append(f"runtime role {row.member} is a member of {row.parent}")

    # pg_class ACLs, not information_schema: that view hides grants the auditor did not make.
    grants = await connection.execute(
        text(
            "select n.nspname, c.relname, a.privilege_type, "
            "case when a.grantee = 0 then 'PUBLIC' else g.rolname end as grantee "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "cross join lateral aclexplode(coalesce(c.relacl, acldefault("
            "(case when c.relkind = 'S' then 's' else 'r' end)::\"char\", c.relowner))) a "
            "left join pg_roles g on g.oid = a.grantee "
            "where c.relkind in ('r', 'p', 'v', 'm', 'f', 'S') "
            "and (a.grantee = 0 or g.rolname = any(:api)) "
            "and (n.nspname in ('pramana', 'pramana_sim') "
            "or (n.nspname = 'public' and c.relname = 'alembic_version'))"
        ),
        {"api": api_roles},
    )
    for row in grants:
        violations.append(f"{row.grantee} has {row.privilege_type} on {row.nspname}.{row.relname}")

    defaults = await connection.execute(
        text(
            "select coalesce(n.nspname, '<global>') as nspname, d.defaclobjtype, "
            "case when acl.grantee = 0 then 'PUBLIC' else grantee.rolname end as grantee, "
            "acl.privilege_type "
            "from pg_default_acl d "
            "left join pg_namespace n on n.oid = d.defaclnamespace "
            "cross join lateral aclexplode(d.defaclacl) acl "
            "left join pg_roles grantee on grantee.oid = acl.grantee "
            "where coalesce(grantee.rolname, case when acl.grantee = 0 then 'PUBLIC' end) "
            f"in ({reachers}) "
            "and d.defaclobjtype in ('r', 'S', 'f') "
            "and (n.nspname in ('pramana', 'pramana_sim') or "
            "(d.defaclnamespace = 0 and d.defaclrole in "
            "(select nspowner from pg_namespace where nspname in ('pramana', 'pramana_sim'))))"
        )
    )
    for row in defaults:
        violations.append(
            f"default {row.privilege_type} on {row.nspname} objects is granted to {row.grantee}"
        )

    implicit_function_defaults = await connection.execute(
        text(
            "select distinct owner.rolname from pg_namespace n "
            "join pg_roles owner on owner.oid = n.nspowner "
            "cross join lateral aclexplode(coalesce("
            "(select d.defaclacl from pg_default_acl d where d.defaclrole = owner.oid "
            "and d.defaclnamespace = 0 and d.defaclobjtype = 'f'), "
            "acldefault('f', owner.oid))) acl "
            "where n.nspname in ('pramana', 'pramana_sim') "
            "and acl.grantee = 0 and acl.privilege_type = 'EXECUTE'"
        )
    )
    for row in implicit_function_defaults:
        violations.append(f"PUBLIC has default function EXECUTE for schema owner {row.rolname}")

    ownership = await connection.execute(
        text(
            "select n.nspname, c.relname from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where c.relowner = (select oid from pg_roles where rolname = 'pramana_app') "
            "and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f') "
            "and n.nspname not in ('pg_catalog', 'information_schema')"
        )
    )
    for row in ownership:
        violations.append(f"pramana_app owns {row.nspname}.{row.relname}")

    sim_ownership = await connection.execute(
        text(
            "select n.nspname, c.relname from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where c.relowner = (select oid from pg_roles where rolname = 'pramana_sim') "
            "and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f') "
            "and n.nspname not in ('pg_catalog', 'information_schema')"
        )
    )
    for row in sim_ownership:
        violations.append(f"pramana_sim owns {row.nspname}.{row.relname}")

    schema_access = await connection.execute(
        text(
            "select r.rolname, n.nspname, p.privilege "
            "from (select unnest(cast(:roles as text[]))) r(rolname) "
            "cross join (values ('pramana'), ('pramana_sim')) n(nspname) "
            "cross join (values ('USAGE'), ('CREATE')) p(privilege) "
            "where exists (select 1 from pg_roles x where x.rolname = r.rolname) "
            "and exists (select 1 from pg_namespace x where x.nspname = n.nspname) "
            "and has_schema_privilege(r.rolname, n.nspname, p.privilege) "
            "and (r.rolname <> all(cast(:runtime as text[])) "
            "or (r.rolname = 'pramana_app' and n.nspname = 'pramana_sim') "
            "or (r.rolname = 'pramana_sim' and n.nspname = 'pramana'))"
        ),
        {"roles": [*api_roles, *RUNTIME_ROLES], "runtime": list(RUNTIME_ROLES)},
    )
    for row in schema_access:
        violations.append(f"{row.rolname} has {row.privilege} on schema {row.nspname}")

    cross_grants = await connection.execute(
        text(
            "select table_schema, table_name, grantee "
            "from information_schema.role_table_grants "
            "where (grantee = 'pramana_app' and table_schema = 'pramana_sim') "
            "or (grantee = 'pramana_sim' and table_schema = 'pramana')"
        )
    )
    for row in cross_grants:
        violations.append(
            f"runtime role {row.grantee} has access to {row.table_schema}.{row.table_name}"
        )

    append_only = await connection.execute(
        text(
            "select table_name, privilege_type from information_schema.role_table_grants "
            "where grantee = 'pramana_app' and table_schema = 'pramana' "
            "and table_name = any(:tables) and privilege_type in ('UPDATE', 'DELETE', 'TRUNCATE')"
        ),
        {"tables": list(APPEND_ONLY)},
    )
    for row in append_only:
        violations.append(f"pramana_app has {row.privilege_type} on append-only {row.table_name}")

    deletable_parents = await connection.execute(
        text(
            "select table_name, privilege_type from information_schema.role_table_grants "
            "where grantee = 'pramana_app' and table_schema = 'pramana' "
            "and table_name = any(:tables) and privilege_type in ('DELETE', 'TRUNCATE')"
        ),
        {"tables": list(NO_DELETE)},
    )
    for row in deletable_parents:
        violations.append(f"pramana_app has {row.privilege_type} on log-owning {row.table_name}")

    sim_table = await connection.execute(
        text("select to_regclass('pramana_sim.scenarios') is not null")
    )
    if not sim_table.scalar():
        violations.append("pramana_sim.scenarios table is missing")
    core_table = await connection.execute(
        text("select to_regclass('pramana.organizations') is not null")
    )
    if not core_table.scalar():
        violations.append("pramana.organizations table is missing")
    return violations


async def audit_database(database_url: str, *, apply_revokes: bool = False) -> list[str]:
    engine = create_async_engine(database_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            return await audit_connection(connection, apply_revokes=apply_revokes)
    finally:
        await engine.dispose()


async def _main(database_url: str, *, apply_revokes: bool) -> int:
    violations = await audit_database(database_url, apply_revokes=apply_revokes)
    if violations:
        raise GrantAuditError(violations)
    print("database grant audit passed")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply-revokes",
        action="store_true",
        help="revoke API-facing grants and cross-runtime schema access before auditing",
    )
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    try:
        require_database_name(database_url)
    except RuntimeError as exc:
        parser.error(str(exc))
    try:
        raise SystemExit(asyncio.run(_main(database_url, apply_revokes=args.apply_revokes)))
    except GrantAuditError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
