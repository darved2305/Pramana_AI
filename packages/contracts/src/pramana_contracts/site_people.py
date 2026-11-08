"""A person who can be asked at one site, as stored for that site."""

from __future__ import annotations

from datetime import datetime

from .common import StrictModel
from .participants import ParticipantSpec


class SitePerson(StrictModel):
    site_id: str
    person: ParticipantSpec
    version: int
    """Send it back as ``If-Match: "<version>"`` when changing this person."""
    created_at: datetime
    updated_at: datetime
