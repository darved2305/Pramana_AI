"""Let a person with a verified email see the open invitations sent to that address.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

CONTEXT_USER = "nullif(current_setting('app.user_id', true), '')"


def upgrade() -> None:
    # Read only, and only rows addressed to the signed-in person's verified email.
    op.execute(
        f"create policy invitee_read on invitations for select using ("
        f"email = (select lower(u.email) from users u where u.id = {CONTEXT_USER} "
        f"and u.active and u.email_verified_at is not null))"
    )
    # The workspace name is shown beside the invitation before the person has joined.
    op.execute(
        "create policy invited_read on organizations for select using ("
        "exists (select 1 from invitations i where i.org_id = organizations.id "
        "and i.accepted_at is null and i.revoked_at is null and i.expires_at > now()))"
    )


def downgrade() -> None:
    op.execute("drop policy invited_read on organizations")
    op.execute("drop policy invitee_read on invitations")
