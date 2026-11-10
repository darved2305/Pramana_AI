"""Onboarding, stored sandbox template and scoped idempotency (ADRs 0017, 0019).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-07
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEMO_ORG = "019a5e00-0000-7000-8000-000000000001"
TEMPLATE_ID = "019a5e00-0000-7000-8000-000000000010"
DEMO_SITE = "019a5e00-0000-7000-8000-000000000011"
DEMO_MODEL = "019a5e00-0000-7000-8000-000000000012"
ORG = "nullif(current_setting('app.org_id', true), '')::uuid"
USER = "nullif(current_setting('app.user_id', true), '')"
ACTOR = "nullif(current_setting('app.principal', true), '')"


def upgrade() -> None:
    op.drop_constraint("events_idempotency_key_key", "events", type_="unique")
    op.create_unique_constraint(
        "events_investigation_idempotency", "events", ["investigation_id", "idempotency_key"]
    )
    op.execute(
        f"alter policy organization_create on organizations with check "
        f"(created_by = {USER} and exists (select 1 from users u where u.id = {USER} "
        "and u.active and u.email_verified_at is not null))"
    )
    op.add_column(
        "organizations", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "onboarding_state",
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL")
        ),
        sa.Column("step", sa.String(24), nullable=False, server_default="welcome"),
        sa.Column("answers", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("answers_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "step in ('welcome','survey','org','sandbox','site','people','test_call','done','join','waiting')",
            name="onboarding_step",
        ),
        sa.CheckConstraint("answers_version = 1 and version > 0", name="onboarding_version"),
    )
    op.create_index("onboarding_org", "onboarding_state", ["org_id", "user_id"])
    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "last_org_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "last_site_by_org", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("home_layout", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    for table, org_col in (("onboarding_state", "org_id"), ("user_preferences", "last_org_id")):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(f"create policy own_state_read on {table} for select using (user_id = {USER})")
        check = (
            f"user_id = {USER} and ({org_col} is null or exists (select 1 from memberships m "
            f"where m.org_id = {table}.{org_col} and m.user_id = {USER} and m.status = 'active'))"
        )
        op.execute(f"create policy own_state_create on {table} for insert with check ({check})")
        op.execute(
            f"create policy own_state_update on {table} for update using (user_id = {USER}) with check ({check})"
        )
        op.execute(f"create policy own_state_delete on {table} for delete using (user_id = {USER})")

    op.create_table(
        "model_templates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec", pg.JSONB(), nullable=False),
        sa.Column("spec_sha256", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("purpose", "kind", "version", name="model_templates_version"),
        sa.CheckConstraint(
            "purpose in ('sandbox','live') and version > 0", name="model_templates_purpose"
        ),
        sa.CheckConstraint("octet_length(spec_sha256) = 32", name="model_templates_hash"),
    )
    spec = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "sandbox_v1.json").read_text(
            encoding="utf-8"
        )
    )
    canonical = json.dumps(
        spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    digest = hashlib.sha256(canonical).digest()
    template = sa.table(
        "model_templates",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("purpose", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("spec", pg.JSONB()),
        sa.column("spec_sha256", sa.LargeBinary()),
    )
    op.bulk_insert(
        template,
        [
            {
                "id": uuid.UUID(TEMPLATE_ID),
                "name": "Sample hostel (simulated)",
                "kind": "hostel",
                "purpose": "sandbox",
                "version": 1,
                "spec": spec,
                "spec_sha256": digest,
            }
        ],
    )
    op.execute(f"select set_config('app.org_id', '{DEMO_ORG}', true)")
    op.execute(
        f"insert into sites (id,org_id,name,kind,mode) values ('{DEMO_SITE}','{DEMO_ORG}','Sample hostel (simulated)','hostel','sandbox')"
    )
    op.execute(
        f"insert into site_models (id,org_id,site_id,version,status,spec,spec_sha256,published_at) select '{DEMO_MODEL}','{DEMO_ORG}','{DEMO_SITE}',1,'published',spec,spec_sha256,now() from model_templates where id = '{TEMPLATE_ID}'"
    )
    op.execute(f"update sites set current_model_id = '{DEMO_MODEL}' where id = '{DEMO_SITE}'")
    op.execute("select set_config('app.org_id', '', true)")

    op.create_table(
        "idempotency_keys",
        sa.Column("scope", sa.String(80), primary_key=True),
        sa.Column("principal", sa.String(128), primary_key=True),
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column(
            "org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE")
        ),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("owner_nonce", pg.UUID(as_uuid=True)),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", sa.LargeBinary()),
        sa.Column(
            "response_headers", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("key ~ '^[A-Za-z0-9_-]{16,128}$'", name="idempotency_key_format"),
        sa.CheckConstraint(
            "scope = case when org_id is null then principal else 'org:' || org_id::text end",
            name="idempotency_scope",
        ),
        sa.CheckConstraint("octet_length(request_sha256) = 32", name="idempotency_fingerprint"),
        sa.CheckConstraint(
            "response_status is not null or (owner_nonce is not null and locked_until is not null)",
            name="idempotency_claim",
        ),
    )
    op.create_index("idempotency_org_expiry", "idempotency_keys", ["org_id", "created_at"])
    op.execute("alter table idempotency_keys enable row level security")
    op.execute("alter table idempotency_keys force row level security")
    policy = f"principal = {ACTOR} and ((org_id = {ORG}) or (org_id is null and scope = 'user:' || {USER}))"
    op.execute(
        f"create policy tenant_isolation on idempotency_keys using ({policy}) with check ({policy})"
    )
    op.execute("""do $$ begin
      if exists (select 1 from pg_roles where rolname = 'pramana_app') then
        grant select, insert, update, delete on onboarding_state, user_preferences, idempotency_keys to pramana_app;
        grant select on model_templates to pramana_app;
      end if;
    end $$;""")


def downgrade() -> None:
    # If new data legitimately reused keys across investigations, refuse a lossy downgrade.
    op.execute("""do $$ begin
      if exists (select 1 from events where idempotency_key is not null
        group by idempotency_key having count(*) > 1) then
        raise exception 'cannot restore global event keys while cross-investigation duplicates exist';
      end if;
    end $$;""")
    op.drop_constraint("events_investigation_idempotency", "events", type_="unique")
    op.create_unique_constraint("events_idempotency_key_key", "events", ["idempotency_key"])
    op.execute(
        f"alter policy organization_create on organizations with check (created_by = {USER})"
    )
    op.drop_table("idempotency_keys")
    op.execute(f"select set_config('app.org_id', '{DEMO_ORG}', true)")
    op.execute("alter table site_models disable trigger site_models_immutable")
    op.execute(f"update sites set current_model_id = null where id = '{DEMO_SITE}'")
    op.execute(f"delete from site_models where id = '{DEMO_MODEL}'")
    op.execute(f"delete from sites where id = '{DEMO_SITE}'")
    op.execute("alter table site_models enable trigger site_models_immutable")
    op.execute("select set_config('app.org_id', '', true)")
    op.drop_table("model_templates")
    op.drop_table("user_preferences")
    op.drop_table("onboarding_state")
    op.drop_column("organizations", "version")
