"""Allow the startup job to enumerate open investigations across tenants.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "create policy startup_recovery_candidates on investigations for select "
        "using (current_setting('app.job', true) = 'startup-recovery' and status <> 'closed')"
    )


def downgrade() -> None:
    op.execute("drop policy startup_recovery_candidates on investigations")
