"""Queue email transactionally and record durable delivery attempts.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

APP_ROLE = "pramana_app"
ORG_CONTEXT = "nullif(current_setting('app.org_id', true), '')::uuid"
JOB_CONTEXT = "current_setting('app.job', true)"
BACKFILL_POLICY = f"{JOB_CONTEXT} = 'personal-data-backfill'"
RELAY_POLICY = f"{JOB_CONTEXT} = 'email-outbox-relay'"


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column(
            "invitation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("invitations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "consent_link_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("consent_links.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(48), server_default="invitation", nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("payload_enc", sa.LargeBinary(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("org_id", "id", name="email_outbox_org_id"),
        sa.UniqueConstraint("invitation_id", name="email_outbox_invitation"),
        sa.UniqueConstraint("consent_link_id", name="email_outbox_consent_link"),
        sa.CheckConstraint(
            "state in ('queued', 'sending', 'sent', 'dead')", name="email_outbox_state"
        ),
        sa.CheckConstraint(
            "(kind = 'invitation' and invitation_id is not null and consent_link_id is null) or "
            "(kind = 'consent_request' and consent_link_id is not null "
            "and invitation_id is null) or "
            "(kind not in ('invitation', 'consent_request') and invitation_id is null "
            "and consent_link_id is null)",
            name="email_outbox_source",
        ),
        sa.CheckConstraint("attempts between 0 and 5", name="email_outbox_attempts"),
        sa.CheckConstraint(
            "((state in ('queued', 'sending')) and payload_enc is not null) or "
            "((state in ('sent', 'dead')) and payload_enc is null)",
            name="email_outbox_payload_lifecycle",
        ),
    )
    op.create_index(
        "email_outbox_ready",
        "email_outbox",
        ["available_at", "created_at"],
        postgresql_where=sa.text("state = 'queued'"),
    )
    op.create_index(
        "email_outbox_expired",
        "email_outbox",
        ["locked_until"],
        postgresql_where=sa.text("state = 'sending'"),
    )
    op.create_table(
        "email_outbox_attempts",
        sa.Column("org_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("outbox_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("error_type", sa.String(80), nullable=True),
        sa.PrimaryKeyConstraint("org_id", "outbox_id", "attempt", name="email_outbox_attempts_pk"),
        sa.ForeignKeyConstraint(
            ["org_id", "outbox_id"],
            ["email_outbox.org_id", "email_outbox.id"],
            name="email_outbox_attempt_org_fk",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("attempt between 1 and 5", name="email_outbox_attempt_number"),
        sa.CheckConstraint(
            "result in ('sending', 'sent', 'retry', 'dead', 'uncertain')",
            name="email_outbox_attempt_result",
        ),
        sa.CheckConstraint(
            "(result = 'sending' and finished_at is null) or "
            "(result <> 'sending' and finished_at is not null)",
            name="email_outbox_attempt_finished",
        ),
    )
    op.create_index(
        "email_outbox_attempts_recent",
        "email_outbox_attempts",
        ["org_id", "outbox_id", "attempt"],
    )

    for table in ("email_outbox", "email_outbox_attempts"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        job_clause = f"({RELAY_POLICY})"
        op.execute(
            f"create policy tenant_or_job on {table} "
            f"using (org_id = {ORG_CONTEXT} or {job_clause}) "
            f"with check (org_id = {ORG_CONTEXT} or {job_clause})"
        )
        op.execute(
            f"""
            do $$ begin
              if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
                grant select, insert, update on {table} to {APP_ROLE};
              end if;
            end $$;
            """
        )

    # The backfill command can cross organization boundaries only while setting its job context.
    # Runtime users still cannot update the append-only event log: 0008 revoked that grant.
    for table in (
        "investigations",
        "events",
        "observations",
        "site_people",
        "person_keys",
        "personal_texts",
    ):
        op.execute(
            f"create policy personal_data_backfill on {table} "
            f"using ({BACKFILL_POLICY}) with check ({BACKFILL_POLICY})"
        )

    # Supabase's API roles must not gain access to the private schema or its new tables.
    op.execute(
        """
        do $$
        declare
          target_schema name := current_schema();
          api_role name;
        begin
          foreach api_role in array array['anon'::name, 'authenticated'::name] loop
            if exists (select 1 from pg_roles where rolname = api_role) then
              execute format('revoke all on schema %I from %I', target_schema, api_role);
              execute format(
                'revoke all on all tables in schema %I from %I', target_schema, api_role
              );
              execute format(
                'revoke all on all sequences in schema %I from %I', target_schema, api_role
              );
              execute format(
                'revoke all on all functions in schema %I from %I', target_schema, api_role
              );
            end if;
          end loop;
        end
        $$;
        """
    )


def downgrade() -> None:
    for table in (
        "investigations",
        "events",
        "observations",
        "site_people",
        "person_keys",
        "personal_texts",
    ):
        op.execute(f"drop policy if exists personal_data_backfill on {table}")
    op.drop_table("email_outbox_attempts")
    op.drop_table("email_outbox")
