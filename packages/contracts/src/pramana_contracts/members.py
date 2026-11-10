"""The people with an account in a workspace (not the people asked during investigations)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .accounts import OrganizationRole
from .common import StrictModel


class WorkspaceMember(StrictModel):
    id: str
    """The member's account id, used to change their roles or remove them."""
    display_name: str
    email: str | None
    """Shown to owners and admins only."""
    roles: list[OrganizationRole]
    status: Literal["active", "pending", "suspended"]
    joined_at: datetime
    you: bool


class UpdateMemberRoles(StrictModel):
    roles: list[OrganizationRole] = Field(min_length=1, max_length=5)

    @field_validator("roles")
    @classmethod
    def _unique(cls, value: list[OrganizationRole]) -> list[OrganizationRole]:
        return sorted(set(value))
