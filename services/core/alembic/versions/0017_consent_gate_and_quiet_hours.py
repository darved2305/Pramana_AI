"""Gate site questions on consent and person quiet hours.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

CONTEXT_ORG = "nullif(current_setting('app.org_id', true), '')::uuid"
APP_ROLE = "pramana_app"


def upgrade() -> None:
    op.add_column("site_people", sa.Column("contact_email_enc", sa.LargeBinary(), nullable=True))
    op.add_column(
        "site_people",
        sa.Column("quiet_hours_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "site_people",
        sa.Column("quiet_hours_start", sa.String(5), nullable=False, server_default="22:00"),
    )
    op.add_column(
        "site_people",
        sa.Column("quiet_hours_end", sa.String(5), nullable=False, server_default="08:00"),
    )
    op.add_column(
        "site_people",
        sa.Column(
            "quiet_hours_timezone", sa.String(64), nullable=False, server_default="Asia/Kolkata"
        ),
    )
    op.create_check_constraint(
        "site_people_quiet_hours_start",
        "site_people",
        "quiet_hours_start ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
    )
    op.create_check_constraint(
        "site_people_quiet_hours_end",
        "site_people",
        "quiet_hours_end ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
    )

    op.add_column(
        "consents",
        sa.Column("decision", sa.String(16), nullable=False, server_default="granted"),
    )
    op.create_check_constraint(
        "consents_decision", "consents", "decision in ('granted', 'refused')"
    )
    op.drop_index("consents_one_active", table_name="consents")
    op.create_index(
        "consents_one_active",
        "consents",
        ["org_id", "site_id", "person_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("withdrawn_at is null and decision = 'granted'"),
    )

    op.create_table(
        "consent_links",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("notice_version", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(16), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id", "person_id"],
            ["site_people.org_id", "site_people.site_id", "site_people.id"],
            name="consent_links_person_fk",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="consent_links_token_hash_key"),
        sa.CheckConstraint("purpose = 'contact_for_investigations'", name="consent_links_purpose"),
        sa.CheckConstraint("channel = 'web'", name="consent_links_channel"),
        sa.CheckConstraint(
            "(consumed_at is null and decision is null) or "
            "(consumed_at is not null and decision in ('granted', 'refused'))",
            name="consent_links_decision",
        ),
        sa.CheckConstraint("expires_at > created_at", name="consent_links_expiry"),
    )
    op.create_index(
        "consent_links_person_open",
        "consent_links",
        ["org_id", "site_id", "person_id", "created_at"],
    )
    op.execute("alter table consent_links enable row level security")
    op.execute("alter table consent_links force row level security")
    op.execute(
        f"create policy tenant_isolation on consent_links "
        f"using (org_id = {CONTEXT_ORG}) with check (org_id = {CONTEXT_ORG})"
    )
    op.execute(
        f"""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
            grant select, insert, update on consent_links to {APP_ROLE};
          end if;
        end $$;
        """
    )


def downgrade() -> None:
    op.drop_table("consent_links")
    op.drop_index("consents_one_active", table_name="consents")
    # The previous schema has no refusal state and permits only one unwithdrawn
    # record per purpose. Preserve refusals as inactive history on rollback.
    op.execute(
        "update consents set withdrawn_at = granted_at "
        "where decision = 'refused' and withdrawn_at is null"
    )
    op.create_index(
        "consents_one_active",
        "consents",
        ["org_id", "site_id", "person_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("withdrawn_at is null"),
    )
    op.drop_constraint("consents_decision", "consents", type_="check")
    op.drop_column("consents", "decision")
    op.drop_constraint("site_people_quiet_hours_end", "site_people", type_="check")
    op.drop_constraint("site_people_quiet_hours_start", "site_people", type_="check")
    op.drop_column("site_people", "quiet_hours_timezone")
    op.drop_column("site_people", "quiet_hours_end")
    op.drop_column("site_people", "quiet_hours_start")
    op.drop_column("site_people", "quiet_hours_enabled")
    op.drop_column("site_people", "contact_email_enc")
