"""Invitations to a workspace: a one-time link for one email address and a set of roles.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

CONTEXT_ORG = "nullif(current_setting('app.org_id', true), '')::uuid"
APP_ROLE = "pramana_app"


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("roles", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("invited_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="invitations_token_hash"),
        sa.CheckConstraint(
            "cardinality(roles) > 0 and roles <@ array['admin', 'operator', 'approver', 'viewer']::text[]",
            name="invitations_roles",
        ),
        sa.CheckConstraint("email = lower(email)", name="invitations_email_lower"),
    )
    op.create_index("invitations_token", "invitations", ["org_id", "token_hash"], unique=True)
    # One open invitation per address per workspace; a new one replaces it after revoking.
    op.create_index(
        "invitations_open_email",
        "invitations",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at is null and revoked_at is null"),
    )
    op.execute("alter table invitations enable row level security")
    op.execute("alter table invitations force row level security")
    op.execute(
        f"create policy tenant_isolation on invitations "
        f"using (org_id = {CONTEXT_ORG}) with check (org_id = {CONTEXT_ORG})"
    )
    op.execute(
        f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
            grant select, insert, update on invitations to {APP_ROLE};
          end if;
        end $$;
        """
    )


def downgrade() -> None:
    op.drop_table("invitations")
