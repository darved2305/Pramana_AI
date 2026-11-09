"""A person who can be asked at one site, as stored for that site."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from .common import Identifier, Role, Skill, StrictModel
from .participants import ConsentPurpose, LanguageProfile, ParticipantSpec


class QuietHours(StrictModel):
    """A person's local time window when new questions should wait."""

    enabled: bool = True
    start: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)

    @model_validator(mode="after")
    def _valid_window_and_timezone(self) -> QuietHours:
        if self.start == self.end:
            raise ValueError("quiet hours start and end must be different")
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("choose a valid timezone, such as Asia/Kolkata") from exc
        return self


class SitePersonPatch(StrictModel):
    """A site person edit, including private contact and availability settings."""

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    roles: list[Role] | None = Field(default=None, min_length=1)
    skill: Skill | None = None
    location_id: Identifier | None = None
    languages: LanguageProfile | None = None
    available: bool | None = None
    question_budget: int | None = Field(default=None, ge=0, le=20)
    contact_email: str | None = Field(default=None, max_length=254)
    quiet_hours: QuietHours | None = None

    @field_validator("contact_email")
    @classmethod
    def _valid_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
            raise ValueError("enter a valid email address")
        return value


class SitePerson(StrictModel):
    site_id: str
    person: ParticipantSpec
    contact_email: str | None = None
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    version: int
    """Send it back as ``If-Match: "<version>"`` when changing this person."""
    created_at: datetime
    updated_at: datetime


class CheckRecord(StrictModel):
    kind: Literal["device", "visual", "panel"]
    checked: int
    matched: int


class PersonTrackRecord(StrictModel):
    """Answers this person gave in investigations whose true cause is known, and how many
    matched it. Only revealed or confirmed causes count, never Pramana's own conclusion."""

    person_id: str
    investigations: int
    checked: int
    matched: int
    by_kind: list[CheckRecord]


class ConsentRequestCreated(StrictModel):
    link_path: str
    expires_at: datetime
    email_delivery: Literal["sent", "failed", "not_configured", "no_email"]


class ConsentLinkView(StrictModel):
    purpose: ConsentPurpose
    language: str
    notice_version: str
    expires_at: datetime


class SubmitConsentResponse(StrictModel):
    decision: Literal["granted", "refused"]


class ConsentResponseView(StrictModel):
    decision: Literal["granted", "refused"]
    recorded_at: datetime


class QuestioningAvailability(StrictModel):
    evaluated_at: datetime
    eligible_count: int
    no_consent_count: int
    quiet_hours_count: int
    unavailable_count: int


class QuietHoursOverrideView(StrictModel):
    reason: str
    actor_id: str
    created_at: datetime


class QuietHoursOverrideRequest(StrictModel):
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def _nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("give a short reason for this emergency override")
        return value
