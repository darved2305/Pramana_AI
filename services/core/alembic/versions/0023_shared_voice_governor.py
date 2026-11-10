"""Coordinate voice usage across core instances.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_reservations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("service", sa.String(16), nullable=False),
        sa.Column("cost_inr", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "voice_rate_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("service", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("voice_rate_events_window", "voice_rate_events", ["service", "created_at"])
    for table in ("voice_reservations", "voice_rate_events"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(
            f"create policy voice_governor on {table} "
            "using (current_setting('app.job', true) = 'voice-governor') "
            "with check (current_setting('app.job', true) = 'voice-governor')"
        )
        op.execute(
            f"do $$ begin if exists (select 1 from pg_roles where rolname = 'pramana_app') "
            f"then grant select, insert, update, delete on {table} to pramana_app; end if; end $$"
        )
    op.execute("""
        do $$ declare r name; s name := current_schema(); begin
          foreach r in array array['anon'::name, 'authenticated'::name] loop
            if exists (select 1 from pg_roles where rolname = r) then
              execute format('revoke all on schema %I from %I', s, r);
              execute format('revoke all on all tables in schema %I from %I', s, r);
              execute format('revoke all on all sequences in schema %I from %I', s, r);
              execute format('revoke all on all functions in schema %I from %I', s, r);
            end if;
          end loop;
        end $$
    """)


def downgrade() -> None:
    op.drop_table("voice_rate_events")
    op.drop_table("voice_reservations")
