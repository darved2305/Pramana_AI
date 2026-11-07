"""add approval requester

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-07 12:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The signed-in account that asked; it may not decide its own request (ADR 0010).
    op.add_column('approvals', sa.Column('requested_by', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('approvals', 'requested_by')
