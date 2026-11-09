"""Keep Pramana tables in a private schema and persist sealed simulator worlds separately.

Supabase exposes the ``public`` schema through its Data API and gives new ``public`` objects
default grants for its API roles. Pramana does not use that API, so every Pramana table moves to
the ``pramana`` schema, which no API role can reach. The simulator gets its own ``pramana_sim``
schema that only the ``pramana_sim`` role can use: the core runtime role cannot read sealed truth.

The move takes every table, standalone sequence and function in ``public`` owned by the migrating
role (``alembic_version`` stays in ``public``), so it is independent of which other migrations
landed before it. Per-role search paths are set with ``ALTER ROLE ... IN DATABASE`` because the
Supabase session pooler does not forward connection startup settings.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

API_ROLES = ("anon", "authenticated", "service_role")
"""Supabase's Data API roles. Revoked when present; absent in plain PostgreSQL."""


def _move(source: str, target: str) -> None:
    op.execute(
        f"""
        do $$
        declare r record;
        begin
          for r in
            select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = '{source}' and c.relkind in ('r', 'p')
              and c.relname <> 'alembic_version' and c.relowner = current_user::regrole
          loop
            execute format('alter table %I.%I set schema {target}', '{source}', r.relname);
          end loop;
          for r in
            select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = '{source}' and c.relkind = 'S' and c.relowner = current_user::regrole
              and not exists (
                select 1 from pg_depend d
                where d.objid = c.oid and d.deptype in ('a', 'i')
                  and d.refclassid = 'pg_class'::regclass
              )
          loop
            execute format('alter sequence %I.%I set schema {target}', '{source}', r.relname);
          end loop;
          for r in
            select p.oid::regprocedure::text as signature from pg_proc p
            join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = '{source}' and p.proowner = current_user::regrole
          loop
            execute format('alter routine %s set schema {target}', r.signature);
          end loop;
          if exists (
            select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = '{source}' and c.relkind in ('r', 'p', 'v', 'm', 'f')
              and c.relname <> 'alembic_version' and c.relowner = current_user::regrole
          ) then
            raise exception 'a relation owned by the migrator is still in schema {source}';
          end if;
        end $$;
        """
    )


def _revoke_api_roles(statement: str) -> str:
    """A DO block body that runs ``statement`` (with %s for the role) for each present API role."""
    roles = ", ".join(f"'{role}'" for role in API_ROLES)
    return f"""
      for r in select rolname from pg_roles where rolname in ({roles}) loop
        execute format('{statement}', r.rolname);
      end loop;
    """


def upgrade() -> None:
    op.execute("create schema if not exists pramana")
    op.execute("create schema if not exists pramana_sim")
    _move("public", "pramana")
    op.execute(
        """
        create table pramana_sim.scenarios (
          id text primary key,
          snapshot jsonb not null,
          status text not null default 'open',
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index scenarios_eviction on pramana_sim.scenarios (status, updated_at)")
    revokes = "".join(
        _revoke_api_roles(statement)
        for statement in (
            "revoke all on schema pramana, pramana_sim from %I",
            "revoke all on all tables in schema pramana, pramana_sim from %I",
            "revoke all on all sequences in schema pramana, pramana_sim from %I",
            "revoke all on all functions in schema pramana, pramana_sim from %I",
            "revoke all on public.alembic_version from %I",
            "alter default privileges in schema pramana, pramana_sim revoke all on tables from %I",
            "alter default privileges in schema pramana, pramana_sim "
            "revoke all on sequences from %I",
            "alter default privileges in schema pramana, pramana_sim "
            "revoke all on functions from %I",
        )
    )
    op.execute(
        f"""
        do $$
        declare r record;
        begin
          revoke all on schema pramana, pramana_sim from public;
          revoke all on all tables in schema pramana, pramana_sim from public;
          revoke all on all sequences in schema pramana, pramana_sim from public;
          revoke all on all functions in schema pramana, pramana_sim from public;
          revoke all on public.alembic_version from public;
          alter default privileges revoke execute on functions from public;
          alter default privileges in schema pramana, pramana_sim
            revoke execute on functions from public;
          {revokes}
          if exists (select 1 from pg_roles where rolname = 'pramana_app') then
            grant usage on schema pramana to pramana_app;
            revoke update, delete, truncate on pramana.events from pramana_app;
            revoke delete, truncate on pramana.investigations from pramana_app;
            revoke all on schema pramana_sim from pramana_app;
            revoke all on public.alembic_version from pramana_app;
            execute format('alter role pramana_app in database %I set search_path to pramana',
                           current_database());
          end if;
          if exists (select 1 from pg_roles where rolname = 'pramana_sim') then
            grant usage on schema pramana_sim to pramana_sim;
            grant select, insert, update, delete on pramana_sim.scenarios to pramana_sim;
            alter default privileges in schema pramana_sim
              grant select, insert, update, delete on tables to pramana_sim;
            revoke all on schema pramana from pramana_sim;
            execute format('alter role pramana_sim in database %I set search_path to pramana_sim',
                           current_database());
          end if;
        end $$;
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists pramana_sim.scenarios")
    op.execute("drop schema if exists pramana_sim")
    _move("pramana", "public")
    op.execute("drop schema if exists pramana")
    op.execute(
        """
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'pramana_app') then
            execute format('alter role pramana_app in database %I reset search_path',
                           current_database());
          end if;
          if exists (select 1 from pg_roles where rolname = 'pramana_sim') then
            execute format('alter role pramana_sim in database %I reset search_path',
                           current_database());
          end if;
        end $$;
        """
    )
