"""Console contracts: sign-in, the participant directory, investigation lists, packs and
evaluation reports. None of these carry simulator state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .common import Identifier, Role, Skill, StrictModel
from .investigation import InvestigationStatus
from .participants import LanguageProfile, ParticipantSpec


class StaffRole(StrEnum):
    """What a signed-in person may do. Participants never sign in: they hold a signed link."""

    OPERATOR = "operator"
    """Creates investigations, manages the directory, requests approvals, reveals."""
    APPROVER = "approver"
    """Approves or denies consequential actions. The approval records this person's id."""


class LoginRequest(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AuthSession(StrictModel):
    user_id: str
    display_name: str
    email: str
    roles: list[StaffRole]
    expires_at: datetime
    method: str = "session"
    """``session`` (browser cookie) or ``automation`` (scripts holding the automation key)."""
    email_verified: bool = False


class SessionDevice(StrictModel):
    """An opaque device reference, never the browser's session token."""

    id: str
    current: bool
    auth_method: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    user_agent: str | None = None


class DirectoryParticipant(StrictModel):
    """A person in the site directory, ready to be added to an investigation."""

    pack_id: Identifier
    participant: ParticipantSpec
    created_at: datetime
    updated_at: datetime


class ParticipantPatch(StrictModel):
    """Fields to change on a directory entry. The id never changes."""

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    roles: list[Role] | None = Field(default=None, min_length=1)
    skill: Skill | None = None
    location_id: Identifier | None = None
    languages: LanguageProfile | None = None
    available: bool | None = None
    question_budget: int | None = Field(default=None, ge=0, le=20)


class InvestigationSummary(StrictModel):
    id: str
    pack_id: str
    status: InvestigationStatus
    created_at: datetime
    updated_at: datetime
    report_text: str
    reporter_id: str
    participant_count: int
    decision_class: str | None = None
    decision_probability: float | None = None


class InvestigationPage(StrictModel):
    items: list[InvestigationSummary]
    total: int
    limit: int
    offset: int


class PackSummary(StrictModel):
    id: str
    version: str
    title: str
    locations: int
    probes: int


class EvaluationReportSummary(StrictModel):
    run_id: str
    git_sha: str | None = None
    seeds: list[int] | None = None
    policies: list[str]
    modified_at: datetime


class EvaluationReport(StrictModel):
    run_id: str
    modified_at: datetime
    summary: dict[str, Any]
    """The harness's ``summary.json`` as written, with non-finite numbers turned into null."""
