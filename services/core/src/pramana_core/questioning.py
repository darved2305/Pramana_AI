"""Consent and local quiet-hours decisions made before the deterministic planner runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from pramana_contracts import QuietHours


@dataclass(frozen=True)
class AvailabilityDecision:
    available: bool
    reason: str


def in_quiet_hours(window: QuietHours, at: datetime) -> bool:
    """Check a local clock window, including windows that cross midnight."""
    if not window.enabled:
        return False
    local = at.astimezone(ZoneInfo(window.timezone))
    now_minute = local.hour * 60 + local.minute
    start_hour, start_minute = map(int, window.start.split(":"))
    end_hour, end_minute = map(int, window.end.split(":"))
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if start < end:
        return start <= now_minute < end
    return now_minute >= start or now_minute < end


def decide_availability(
    *,
    listed_available: bool,
    has_web_contact_consent: bool,
    quiet_hours: QuietHours,
    at: datetime,
    quiet_hours_overridden: bool = False,
    declined_in_investigation: bool = False,
) -> AvailabilityDecision:
    """Pure inputs make the eligibility rule easy to test and deterministic to record."""
    if not listed_available:
        return AvailabilityDecision(False, "unavailable")
    if declined_in_investigation:
        return AvailabilityDecision(False, "declined")
    if not has_web_contact_consent:
        return AvailabilityDecision(False, "no_consent")
    if not quiet_hours_overridden and in_quiet_hours(quiet_hours, at):
        return AvailabilityDecision(False, "quiet_hours")
    return AvailabilityDecision(True, "eligible")
