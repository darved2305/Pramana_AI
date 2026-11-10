"""Google identities, browser flows and bounded sessions (ADR 0016).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", nullable=True)
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.execute("update users set email_verified_at = created_at where password_hash is not null")
    op.create_index("users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_table(
        "user_identities",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email_at_link", sa.String(254)),
        sa.Column("hosted_domain", sa.String(253)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("provider", "subject", name="user_identities_provider_subject"),
        sa.CheckConstraint(
            "provider in ('google', 'password', 'saml', 'passkey')", name="user_identities_provider"
        ),
    )
    op.create_index("user_identities_user", "user_identities", ["user_id"])
    op.create_table(
        "auth_flows",
        sa.Column("id_hash", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(128), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("pkce_verifier", sa.String(128), nullable=False),
        sa.Column("next_path", sa.String(2048), nullable=False),
        sa.Column("link_user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("link_session_hash", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("auth_flows_expiry", "auth_flows", ["expires_at"])
    op.add_column(
        "sessions",
        sa.Column("auth_method", sa.String(16), nullable=False, server_default="password"),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "idle_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '60 minutes'"),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "absolute_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '12 hours'"),
        ),
    )
    op.add_column("sessions", sa.Column("user_agent", sa.String(512)))
    op.execute(
        "update sessions set last_seen_at = created_at, absolute_expires_at = expires_at, idle_expires_at = least(expires_at, created_at + interval '60 minutes')"
    )
    op.create_check_constraint(
        "sessions_auth_method", "sessions", "auth_method in ('google', 'password', 'passkey')"
    )
    op.create_table(
        "rate_limits",
        sa.Column("scope", sa.String(32), primary_key=True),
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("failures", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id")),
        sa.Column("actor_kind", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_kind", sa.String(32)),
        sa.Column("target_id", sa.String(64)),
        sa.Column("ip_prefix", pg.INET()),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("details", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("audit_log_org_recent", "audit_log", ["org_id", "ts"])
    op.execute("alter table audit_log enable row level security")
    op.execute("alter table audit_log force row level security")
    org = "nullif(current_setting('app.org_id', true), '')::uuid"
    user = "nullif(current_setting('app.user_id', true), '')"
    op.execute(
        f"create policy tenant_isolation on audit_log using (org_id = {org}) with check (org_id = {org})"
    )
    op.execute(
        f"create policy own_auth_audit on audit_log for insert with check (org_id is null and actor_kind = 'user' and actor_id = {user})"
    )
    op.execute(
        f"create policy own_auth_audit_read on audit_log for select using (org_id is null and actor_kind = 'user' and actor_id = {user})"
    )
    op.execute("""do $$ begin
      if exists (select 1 from pg_roles where rolname = 'pramana_app') then
        grant select, insert, update, delete on user_identities, auth_flows, rate_limits to pramana_app;
        grant select, insert on audit_log to pramana_app;
      end if;
    end $$;""")


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("rate_limits")
    op.drop_constraint("sessions_auth_method", "sessions", type_="check")
    for column in (
        "user_agent",
        "absolute_expires_at",
        "idle_expires_at",
        "last_seen_at",
        "auth_method",
    ):
        op.drop_column("sessions", column)
    op.drop_table("auth_flows")
    op.drop_table("user_identities")
    op.drop_index("users_email_lower", table_name="users")
    op.drop_column("users", "email_verified_at")
    # A Google-only account never gains a usable password when older code is restored.
    op.execute(
        "update users set password_hash = 'disabled-google-account' where password_hash is null"
    )
    op.alter_column("users", "password_hash", nullable=False)
