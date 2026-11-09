"""Accounts, organization setup and versioned onboarding answers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from .common import StrictModel, TemplateLanguage
from .console import AuthSession


class OrganizationKind(StrEnum):
    CAMPUS = "campus"
    HOSPITAL = "hospital"
    OFFICE = "office"
    HOTEL = "hotel"
    RETAIL = "retail"
    OTHER = "other"


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    APPROVER = "approver"
    VIEWER = "viewer"


class OnboardingStep(StrEnum):
    WELCOME = "welcome"
    SURVEY = "survey"
    ORG = "org"
    SANDBOX = "sandbox"
    SITE = "site"
    PEOPLE = "people"
    TEST_CALL = "test_call"
    DONE = "done"
    JOIN = "join"
    WAITING = "waiting"


class OnboardingAnswers(StrictModel):
    version: Literal[1] = 1
    work: (
        Literal["facilities", "it", "duty_manager", "technician", "representative", "other"] | None
    ) = None
    organization_kind: OrganizationKind | None = None
    buildings: Literal["one", "two_to_five", "six_to_twenty", "more_than_twenty"] | None = None
    problem: (
        Literal["wifi", "power", "both", "water", "cooling", "lifts", "devices", "other"] | None
    ) = None
    other_problem: str | None = Field(default=None, max_length=500)
    languages: list[TemplateLanguage] = Field(default_factory=list, max_length=4)

    @field_validator("languages")
    @classmethod
    def unique_languages(cls, value: list[TemplateLanguage]) -> list[TemplateLanguage]:
        if len(set(value)) != len(value):
            raise ValueError("choose each language only once")
        return value


class OnboardingPatch(StrictModel):
    answers: OnboardingAnswers | None = None
    step: OnboardingStep | None = None
    dismissed: bool | None = None


class OnboardingState(StrictModel):
    step: OnboardingStep
    answers: OnboardingAnswers
    version: int
    org_id: str | None = None
    dismissed_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class OrganizationSummary(StrictModel):
    id: str
    slug: str
    name: str
    kind: OrganizationKind
    roles: list[OrganizationRole]
    timezone: str
    version: int
    created_at: datetime


class IdentitySummary(StrictModel):
    id: str
    provider: str
    email_at_link: str | None = None
    hosted_domain: str | None = None
    last_used_at: datetime | None = None


class PendingInvitation(StrictModel):
    id: str
    organization_id: str
    organization_name: str
    roles: list[OrganizationRole]
    expires_at: datetime


class JoinSuggestion(StrictModel):
    organization_id: str
    organization_name: str
    domain: str
    policy: Literal["request", "auto"]
    request_id: str | None = None
    request_status: Literal["pending"] | None = None


class HomeLayout(StrictModel):
    pins: list[str] = Field(default_factory=list, max_length=10)
    hides: list[str] = Field(default_factory=list, max_length=10)
    checklist_dismissed: bool = False


class AccountPreferences(StrictModel):
    last_org_id: str | None = None
    last_site_by_org: dict[str, str] = Field(default_factory=dict)
    home_layout: HomeLayout = Field(default_factory=HomeLayout)


class LastSite(StrictModel):
    org_id: str
    site_id: str


class PreferencesPatch(StrictModel):
    """Only the fields sent change. Workspaces and sites must be the person's own."""

    last_org_id: str | None = None
    last_site: LastSite | None = None
    home_layout: HomeLayout | None = None


class CurrentAccount(StrictModel):
    user: AuthSession
    identities: list[IdentitySummary]
    memberships: list[OrganizationSummary]
    onboarding: OnboardingState
    destination: str
    preferences: AccountPreferences
    pending_invitations: list[PendingInvitation] = Field(default_factory=list)
    join_suggestions: list[JoinSuggestion] = Field(default_factory=list)


class CreateOrganization(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(
        default=None, min_length=3, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"
    )
    kind: OrganizationKind | None = None


class SiteSummary(StrictModel):
    id: str
    org_id: str
    name: str
    kind: str
    mode: Literal["sandbox", "live"]
    current_model_id: str | None
    created_at: datetime


class OrganizationCreated(StrictModel):
    organization: OrganizationSummary
    sandbox_site: SiteSummary
    live_site: SiteSummary
    onboarding: OnboardingState
    destination: str
