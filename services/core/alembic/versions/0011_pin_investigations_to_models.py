"""Pin saved-site investigations to an immutable model version.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A parent delete would otherwise erase append-only events through ON DELETE CASCADE.
    # Retention/export deletion needs a separate, explicitly authorized maintenance role.
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'pramana_app') then
            revoke delete on investigations from pramana_app;
          end if;
        end $$;
    """)
    op.create_unique_constraint("investigations_org_id", "investigations", ["org_id", "id"])
    for table in ("events", "questions", "observations", "approvals"):
        op.create_foreign_key(
            f"{table}_org_investigation_fk", table, "investigations",
            ["org_id", "investigation_id"], ["org_id", "id"], ondelete="CASCADE",
        )
    op.add_column("investigations", sa.Column("site_id", pg.UUID(as_uuid=True), nullable=True))
    op.add_column("investigations", sa.Column("site_model_id", pg.UUID(as_uuid=True), nullable=True))
    # Only the frozen, provisioned sandbox can explain an old file-backed investigation.
    # Unknown legacy packs remain unpinned and cannot be opened through production routes.
    op.execute("""
        with candidates as (
          select i.id, s.id as site_id, m.id as model_id,
            row_number() over (partition by i.id order by s.created_at, s.id, m.version) as rank
          from investigations i
          join sites s on s.org_id = i.org_id and s.mode = 'sandbox'
          join site_models m on m.site_id = s.id and m.org_id = s.org_id
          join model_templates t on t.spec_sha256 = m.spec_sha256 and t.purpose = 'sandbox'
          where m.spec->>'pack' = i.pack_id and m.status in ('published', 'retired')
        )
        update investigations i set site_id = c.site_id, site_model_id = c.model_id
        from candidates c where c.id = i.id and c.rank = 1
    """)
    op.create_check_constraint(
        "investigations_model_pin_pair", "investigations",
        "(site_id is null) = (site_model_id is null)",
    )
    op.create_foreign_key(
        "investigations_model_pin_fk", "investigations", "site_models",
        ["org_id", "site_id", "site_model_id"], ["org_id", "site_id", "id"],
    )
    op.create_index("investigations_site", "investigations", ["org_id", "site_id", "created_at"])
    op.execute("""
        create function forbid_investigation_model_repin() returns trigger language plpgsql as $$
        begin
          if old.site_model_id is not null and (
            new.org_id is distinct from old.org_id or new.site_id is distinct from old.site_id
            or new.site_model_id is distinct from old.site_model_id
          ) then
            raise exception 'an investigation keeps its original site model';
          end if;
          return new;
        end $$;
    """)
    op.execute("create trigger investigations_model_pin_immutable before update on investigations "
               "for each row execute function forbid_investigation_model_repin()")


def downgrade() -> None:
    op.execute("""
        do $$ begin
          if exists (select 1 from pg_roles where rolname = 'pramana_app') then
            grant delete on investigations to pramana_app;
          end if;
        end $$;
    """)
    op.execute("drop trigger investigations_model_pin_immutable on investigations")
    op.execute("drop function forbid_investigation_model_repin()")
    op.drop_index("investigations_site", table_name="investigations")
    op.drop_constraint("investigations_model_pin_fk", "investigations", type_="foreignkey")
    op.drop_constraint("investigations_model_pin_pair", "investigations", type_="check")
    op.drop_column("investigations", "site_model_id")
    op.drop_column("investigations", "site_id")
    for table in ("events", "questions", "observations", "approvals"):
        op.drop_constraint(f"{table}_org_investigation_fk", table, type_="foreignkey")
    op.drop_constraint("investigations_org_id", "investigations", type_="unique")
