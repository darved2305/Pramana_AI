"""Inviting someone into a workspace with a one-time link (no email provider needed)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .accounts import OrganizationSummary
from .common import StrictModel

InvitedRole = Literal["admin", "operator", "approver", "viewer"]


class CreateInvitation(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    roles: list[InvitedRole] = Field(min_length=1, max_length=4)

    @field_validator("email")
    @classmethod
    def _plain_address(cls, value: str) -> str:
        value = value.strip().lower()
        local, _, domain = value.partition("@")
        if not local or "." not in domain or " " in value:
            raise ValueError("enter an email address like name@example.com")
        return value

    @field_validator("roles")
    @classmethod
    def _unique(cls, value: list[InvitedRole]) -> list[InvitedRole]:
        return sorted(set(value))


class InvitationView(StrictModel):
    id: str
    email: str
    roles: list[InvitedRole]
    status: Literal["pending", "accepted", "revoked", "expired"]
    created_at: datetime
    expires_at: datetime
    invited_by: str | None


class InvitationCreated(StrictModel):
    invitation: InvitationView
    accept_path: str
    """``/invite/<token>``. Shown once: only a hash of the secret is stored."""


class AcceptInvitation(StrictModel):
    token: str = Field(min_length=20, max_length=200)


class InvitationAccepted(StrictModel):
    organization: OrganizationSummary
    destination: str
