"""A person who can be asked at one site, as stored for that site."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .common import StrictModel
from .participants import ParticipantSpec


class SitePerson(StrictModel):
    site_id: str
    person: ParticipantSpec
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
