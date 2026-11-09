"""Add restorable workspace deletion state and keyset-list indexes.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURGE_AWARE_TRIGGER = """
create or replace function forbid_published_model_edits() returns trigger language plpgsql as $$
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
       or new.status = 'draft'
       or ((new.source is distinct from old.source
            or new.validation is distinct from old.validation)
           and not (coalesce(current_setting('app.purge_personal_data', true), '') = 'on'
                    and new.source is null and new.validation is null
                    and exists (select 1 from pg_roles where rolname = current_user
                                and (rolsuper or rolbypassrls))
                    and exists (select 1 from organizations o where o.id = old.org_id
                                and o.deleted_at is not null and o.purge_after <= now()
                                and o.purged_at is null))) then
      raise exception 'published site models are immutable; save a new version';
    end if;
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $$;
"""

ORIGINAL_TRIGGER = """
create or replace function forbid_published_model_edits() returns trigger language plpgsql as $$
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
       or new.status = 'draft'
       or new.source is distinct from old.source
       or new.validation is distinct from old.validation then
      raise exception 'published site models are immutable; save a new version';
    end if;
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $$;
"""


def upgrade() -> None:
    op.add_column("organizations", sa.Column("deleted_by", sa.String(32), nullable=True))
    op.add_column(
        "organizations", sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "organizations_deleted_by_fk",
        "organizations",
        "users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "organizations_deletion_window",
        "organizations",
        "(deleted_at is null) = (purge_after is null)",
    )
    op.execute(PURGE_AWARE_TRIGGER)
    op.create_index(
        "organizations_purge_due",
        "organizations",
        ["purge_after", "id"],
        postgresql_where=sa.text("deleted_at is not null and purged_at is null"),
    )

    op.create_index(
        "investigations_org_created_cursor",
        "investigations",
        ["org_id", sa.text("created_at desc"), sa.text("id desc")],
    )
    op.create_index(
        "sites_org_created_cursor",
        "sites",
        ["org_id", sa.text("created_at desc"), sa.text("id desc")],
        postgresql_where=sa.text("archived_at is null"),
    )
    op.create_index(
        "site_models_org_site_created_cursor",
        "site_models",
        ["org_id", "site_id", sa.text("created_at desc"), sa.text("id desc")],
        postgresql_where=sa.text("status in ('published', 'retired')"),
    )
    op.create_index(
        "site_people_org_site_created_cursor",
        "site_people",
        ["org_id", "site_id", sa.text("created_at desc"), sa.text("id desc")],
    )
    op.create_index(
        "observations_org_person_inv_cursor",
        "observations",
        ["org_id", "participant_id", "investigation_id"],
        postgresql_where=sa.text("state in ('committed', 'superseded')"),
    )
    op.create_index(
        "memberships_org_created_cursor",
        "memberships",
        ["org_id", sa.text("created_at desc"), sa.text("user_id desc")],
    )
    op.create_index(
        "invitations_org_created_cursor",
        "invitations",
        ["org_id", sa.text("created_at desc"), sa.text("id desc")],
    )
    op.create_index(
        "consents_person_created_cursor",
        "consents",
        ["org_id", "site_id", "person_id", sa.text("granted_at desc"), sa.text("id desc")],
    )
    op.create_index(
        "audit_log_org_cursor",
        "audit_log",
        ["org_id", sa.text("ts desc"), sa.text("id desc")],
    )


def downgrade() -> None:
    for name, table in (
        ("audit_log_org_cursor", "audit_log"),
        ("consents_person_created_cursor", "consents"),
        ("invitations_org_created_cursor", "invitations"),
        ("memberships_org_created_cursor", "memberships"),
        ("observations_org_person_inv_cursor", "observations"),
        ("site_people_org_site_created_cursor", "site_people"),
        ("site_models_org_site_created_cursor", "site_models"),
        ("sites_org_created_cursor", "sites"),
        ("investigations_org_created_cursor", "investigations"),
    ):
        op.drop_index(name, table_name=table)
    op.drop_index("organizations_purge_due", table_name="organizations")
    op.drop_constraint("organizations_deletion_window", "organizations", type_="check")
    op.drop_constraint("organizations_deleted_by_fk", "organizations", type_="foreignkey")
    op.drop_column("organizations", "purged_at")
    op.drop_column("organizations", "purge_after")
    op.drop_column("organizations", "deleted_by")
    op.execute(ORIGINAL_TRIGGER)
