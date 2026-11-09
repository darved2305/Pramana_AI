"""Workspace domain claims and requests to join them."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .accounts import OrganizationRole
from .common import StrictModel


class CreateDomain(StrictModel):
    domain: str = Field(min_length=3, max_length=253)
    verification: Literal["google_hd", "dns_txt"]
    join_policy: Literal["off", "request", "auto"] = "request"


class OrganizationDomain(StrictModel):
    domain: str
    verification: Literal["google_hd", "dns_txt"]
    verified_at: datetime | None
    join_policy: Literal["off", "request", "auto"]
    verification_name: str | None = None
    verification_value: str | None = None


class UpdateDomainPolicy(StrictModel):
    join_policy: Literal["off", "request", "auto"]


class RequestJoin(StrictModel):
    organization_id: str = Field(min_length=8, max_length=40)


class JoinRequestDecision(StrictModel):
    role: Literal["admin", "operator", "approver", "viewer"] = "viewer"


class JoinRequestView(StrictModel):
    id: str
    organization_id: str
    organization_name: str
    requester_name: str
    requester_email: str
    status: Literal["pending", "approved", "declined", "cancelled"]
    role: OrganizationRole | None = None
    decision_source: Literal["admin", "auto"] | None = None
    requested_at: datetime
    decided_at: datetime | None = None


class JoinRequestCreated(StrictModel):
    request: JoinRequestView
    joined: bool
    destination: str | None = None
