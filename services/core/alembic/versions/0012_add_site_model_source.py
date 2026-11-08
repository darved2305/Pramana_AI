"""Keep each model version's site description, and freeze it with the version on publish.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TRIGGER = """
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
       {extra} then
      raise exception 'published site models are immutable; save a new version';
    end if;
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $$;
"""


def upgrade() -> None:
    op.add_column("site_models", sa.Column("source", pg.JSONB(), nullable=True))
    op.execute(
        TRIGGER.format(
            extra="or new.source is distinct from old.source "
            "or new.validation is distinct from old.validation"
        )
    )
    # One open draft per site, so two editors cannot fork a site's next version.
    op.create_index(
        "site_models_one_draft",
        "site_models",
        ["org_id", "site_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )


def downgrade() -> None:
    op.drop_index("site_models_one_draft", table_name="site_models")
    op.execute(TRIGGER.format(extra=""))
    op.drop_column("site_models", "source")
