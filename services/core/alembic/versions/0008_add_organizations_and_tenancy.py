"""add organizations, memberships, sites, site models and tenancy (ADR 0015)

Expand step. Every tenant table gains ``org_id`` and row-level security that fails closed. Rows
that exist today belong to one "Pramana demo" organization. Until the organization-scoped routes
land, a write that sets no organization context falls back to that organization through the column
default; that fallback only helps the table owner (migrations, today's tests), because for the
runtime role ``pramana_app`` the ``WITH CHECK`` policy rejects a row whose organization is not the
context. The contract step removes the fallback.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-07 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEMO_ORG_ID = "019a5e00-0000-7000-8000-000000000001"
APP_ROLE = "pramana_app"
CONTEXT_ORG = "nullif(current_setting('app.org_id', true), '')::uuid"
CONTEXT_USER = "nullif(current_setting('app.user_id', true), '')"

# Tables that existed before tenancy, and the organization column's default during the expand step.
LEGACY_TENANT_TABLES = (
    "investigations",
    "events",
    "questions",
    "observations",
    "approvals",
    "directory_participants",
)
NEW_TENANT_TABLES = ("sites", "site_models")
TENANT_TABLES = LEGACY_TENANT_TABLES + NEW_TENANT_TABLES


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("data_region", sa.String(32), nullable=False, server_default="asia-south1"),
        sa.Column("plan", sa.String(32), nullable=False, server_default="starter"),
        sa.Column("created_by", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'", name="organizations_slug"),
        sa.CheckConstraint(
            "kind in ('campus', 'hospital', 'office', 'hotel', 'retail', 'other')",
            name="organizations_kind",
        ),
    )
    op.execute(
        f"insert into organizations (id, slug, name, kind) values "
        f"('{DEMO_ORG_ID}', 'pramana-demo', 'Pramana demo', 'campus')"
    )

    op.create_table(
        "memberships",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("roles", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("org_id", "user_id"),
        sa.CheckConstraint(
            "cardinality(roles) > 0 and roles <@ "
            "array['owner', 'admin', 'operator', 'approver', 'viewer']::text[]",
            name="memberships_roles",
        ),
        sa.CheckConstraint(
            "status in ('active', 'pending', 'suspended')", name="memberships_status"
        ),
    )
    op.create_index("memberships_user", "memberships", ["user_id"])

    op.create_table(
        "sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False, server_default="live"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("current_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode in ('live', 'sandbox')", name="sites_mode"),
        sa.UniqueConstraint("org_id", "id", name="sites_org_id"),
    )
    op.create_index("sites_org", "sites", ["org_id", "created_at"])

    op.create_table(
        "site_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "site_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("spec_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("site_id", "version", name="site_models_site_version"),
        sa.UniqueConstraint("org_id", "site_id", "id", name="site_models_org_site_id"),
        sa.ForeignKeyConstraint(["org_id", "site_id"], ["sites.org_id", "sites.id"]),
        sa.CheckConstraint(
            "status in ('draft', 'published', 'retired')", name="site_models_status"
        ),
    )
    op.create_index("site_models_org", "site_models", ["org_id", "site_id"])
    op.create_foreign_key(
        "sites_current_model_fk", "sites", "site_models",
        ["org_id", "id", "current_model_id"], ["org_id", "site_id", "id"]
    )
    op.execute(
        """
        create function forbid_published_model_edits() returns trigger language plpgsql as $$
        begin
          if old.status in ('published', 'retired') then
            if tg_op = 'DELETE' then
              raise exception 'published site models are immutable; retire instead';
            end if;
            if new.spec is distinct from old.spec
               or new.spec_sha256 is distinct from old.spec_sha256
               or new.id is distinct from old.id
               or new.org_id is distinct from old.org_id
               or new.site_id is distinct from old.site_id
               or new.version is distinct from old.version
               or new.status = 'draft' then
              raise exception 'published site models are immutable; save a new version';
            end if;
          end if;
          if tg_op = 'DELETE' then return old; end if;
          return new;
        end $$;
        """
    )
    op.execute(
        "create trigger site_models_immutable before update or delete on site_models "
        "for each row execute function forbid_published_model_edits()"
    )

    # Expand: org_id on the tables that exist today, backfilled to the demo organization.
    for table in LEGACY_TENANT_TABLES:
        op.add_column(table, sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(f"update {table} set org_id = '{DEMO_ORG_ID}'")
        op.alter_column(
            table,
            "org_id",
            nullable=False,
            server_default=sa.text(f"coalesce({CONTEXT_ORG}, '{DEMO_ORG_ID}'::uuid)"),
        )
        op.create_foreign_key(f"{table}_org_fk", table, "organizations", ["org_id"], ["id"])
    op.create_index("investigations_org_recent", "investigations", ["org_id", "created_at"])
    op.create_index("events_org_inv", "events", ["org_id", "investigation_id", "seq"])

    # Row-level security: no context, no rows; never write into another organization.
    for table in TENANT_TABLES:
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(
            f"create policy tenant_isolation on {table} "
            f"using (org_id = {CONTEXT_ORG}) with check (org_id = {CONTEXT_ORG})"
        )
    # A person reads their own memberships across organizations (to choose one); everything else
    # about a membership is visible only inside its organization.
    op.execute("alter table memberships enable row level security")
    op.execute("alter table memberships force row level security")
    op.execute(
        f"create policy tenant_isolation on memberships "
        f"using (org_id = {CONTEXT_ORG}) "
        f"with check (org_id = {CONTEXT_ORG})"
    )
    op.execute(
        f"create policy own_memberships on memberships for select "
        f"using (user_id = {CONTEXT_USER})"
    )
    op.execute("alter table organizations enable row level security")
    op.execute("alter table organizations force row level security")
    op.execute(
        f"create policy organization_read on organizations for select using (id = {CONTEXT_ORG} "
        f"or exists (select 1 from memberships m where m.org_id = organizations.id "
        f"and m.user_id = {CONTEXT_USER} and m.status = 'active'))"
    )
    op.execute(
        f"create policy organization_create on organizations for insert "
        f"with check (created_by = {CONTEXT_USER})"
    )
    op.execute(
        f"create policy organization_update on organizations for update "
        f"using (id = {CONTEXT_ORG}) with check (id = {CONTEXT_ORG})"
    )
    op.execute(
        f"create policy organization_delete on organizations for delete using (id = {CONTEXT_ORG})"
    )

    # The runtime role (created by scripts/dev_db.py locally, mapped from IAM users in the cloud).
    op.execute(
        f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
            grant usage on schema public to {APP_ROLE};
            grant select, insert, update, delete on all tables in schema public to {APP_ROLE};
            grant usage, select on all sequences in schema public to {APP_ROLE};
            revoke update, delete, truncate on events from {APP_ROLE};
          end if;
        end $$;
        """
    )


def downgrade() -> None:
    for policy in ("organization_read", "organization_create", "organization_update", "organization_delete"):
        op.execute(f"drop policy if exists {policy} on organizations")
    op.execute("drop policy if exists own_memberships on memberships")
    op.execute(
        f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
            revoke all on all tables in schema public from {APP_ROLE};
            revoke all on all sequences in schema public from {APP_ROLE};
            revoke usage on schema public from {APP_ROLE};
          end if;
        end $$;
        """
    )
    for table in (*TENANT_TABLES, "memberships"):
        op.execute(f"drop policy if exists tenant_isolation on {table}")
        op.execute(f"alter table {table} no force row level security")
        op.execute(f"alter table {table} disable row level security")
    op.drop_index("events_org_inv", table_name="events")
    op.drop_index("investigations_org_recent", table_name="investigations")
    for table in LEGACY_TENANT_TABLES:
        op.drop_constraint(f"{table}_org_fk", table, type_="foreignkey")
        op.drop_column(table, "org_id")
    op.drop_constraint("sites_current_model_fk", "sites", type_="foreignkey")
    op.execute("drop trigger if exists site_models_immutable on site_models")
    op.execute("drop function if exists forbid_published_model_edits()")
    op.drop_table("site_models")
    op.drop_table("sites")
    op.drop_index("memberships_user", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("organizations")
