"""The people with an account in a workspace (not the people asked during investigations)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .accounts import OrganizationRole
from .common import StrictModel


class WorkspaceMember(StrictModel):
    display_name: str
    email: str | None
    """Shown to owners and admins only."""
    roles: list[OrganizationRole]
    status: Literal["active", "pending", "suspended"]
    joined_at: datetime
    you: bool
