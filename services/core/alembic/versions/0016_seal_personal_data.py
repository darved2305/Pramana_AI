"""Seal personal data with one key per person, and record consent.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

CONTEXT_ORG = "nullif(current_setting('app.org_id', true), '')::uuid"
APP_ROLE = "pramana_app"
TABLES = {
    "person_keys": "select, insert, update",
    "personal_texts": "select, insert, delete",
    "consents": "select, insert, update",
}


def upgrade() -> None:
    op.add_column("site_people", sa.Column("display_name_enc", sa.LargeBinary(), nullable=True))
    op.create_table(
        "person_keys",
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", sa.String(64), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("org_id", "site_id", "person_id", name="person_keys_pk"),
        sa.CheckConstraint(
            "(wrapped_key is null) = (erased_at is not null)", name="person_keys_erased"
        ),
    )
    op.create_table(
        "personal_texts",
        sa.Column("org_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("item", sa.String(64), nullable=False),
        sa.Column("site_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint(
            "org_id", "investigation_id", "kind", "item", name="personal_texts_pk"
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "site_id", "person_id"],
            ["person_keys.org_id", "person_keys.site_id", "person_keys.person_id"],
            name="personal_texts_person_fk",
        ),
        sa.CheckConstraint(
            "kind in ('name', 'report', 'transcript')", name="personal_texts_kind"
        ),
    )
    op.create_index(
        "personal_texts_person", "personal_texts", ["org_id", "site_id", "person_id"]
    )
    op.create_table(
        "consents",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("notice_version", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", pg.JSONB(), nullable=False),
        sa.CheckConstraint(
            "purpose in ('contact_for_investigations', 'voice_processing')",
            name="consents_purpose",
        ),
    )
    op.create_index(
        "consents_one_active",
        "consents",
        ["org_id", "site_id", "person_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("withdrawn_at is null"),
    )
    for table, grants in TABLES.items():
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")
        op.execute(
            f"create policy tenant_isolation on {table} "
            f"using (org_id = {CONTEXT_ORG}) with check (org_id = {CONTEXT_ORG})"
        )
        op.execute(
            f"""
            do $$ begin
              if exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
                grant {grants} on {table} to {APP_ROLE};
              end if;
            end $$;
            """
        )


def downgrade() -> None:
    op.drop_table("consents")
    op.drop_table("personal_texts")
    op.drop_table("person_keys")
    op.drop_column("site_people", "display_name_enc")
