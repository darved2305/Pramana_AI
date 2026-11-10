"""People per site: who can be asked, with roles from that site's own catalogue.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

CONTEXT_ORG = "nullif(current_setting('app.org_id', true), '')::uuid"
APP_ROLE = "pramana_app"


def upgrade() -> None:
    op.create_table(
        "site_people",
        sa.Column("org_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("spec", pg.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("org_id", "site_id", "id", name="site_people_pk"),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id"],
            ["sites.org_id", "sites.id"],
            name="site_people_site_fk",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("version > 0", name="site_people_version"),
    )
    op.execute("alter table site_people enable row level security")
    op.execute("alter table site_people force row level security")
    op.execute(
        f"create policy tenant_isolation on site_people "
        f"using (org_id = {CONTEXT_ORG}) with check (org_id = {CONTEXT_ORG})"
    )
    op.execute(
        f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
            grant select, insert, update, delete on site_people to {APP_ROLE};
          end if;
        end $$;
        """
    )


def downgrade() -> None:
    op.drop_table("site_people")
