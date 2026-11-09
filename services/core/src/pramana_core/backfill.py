"""Resumable sealing for site data written before migration 0016."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from .db import (
    Database,
    EventRow,
    InvestigationRow,
    ObservationRow,
    acting_as_job,
)
from .investigations import log_digest, tokenized_names
from .people import SitePersonRow
from .vault import SEALED, PersonRef, PersonVault

BACKFILL_JOB = "personal-data-backfill"


@dataclass
class BackfillCounts:
    directory_names: int = 0
    investigation_names: int = 0
    reports: int = 0
    transcripts: int = 0
    events_sanitized: int = 0
    outcomes_sanitized: int = 0
    log_seals_rehashed: int = 0


async def backfill_personal_data(
    db: Database, vault: PersonVault, *, batch_size: int = 100
) -> BackfillCounts:
    """Seal plaintext in bounded transactions; a restart safely scans completed rows again."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    counts = BackfillCounts()
    await _backfill_site_people(db, vault, batch_size, counts)
    await _backfill_investigations(db, vault, batch_size, counts)
    return counts


async def _backfill_site_people(
    db: Database, vault: PersonVault, batch_size: int, counts: BackfillCounts
) -> None:
    cursor: tuple[UUID, UUID, str] | None = None
    while True:
        with acting_as_job(BACKFILL_JOB):
            async with db.transaction() as session:
                stmt = select(SitePersonRow).order_by(
                    SitePersonRow.org_id, SitePersonRow.site_id, SitePersonRow.id
                )
                if cursor is not None:
                    stmt = stmt.where(
                        tuple_(SitePersonRow.org_id, SitePersonRow.site_id, SitePersonRow.id)
                        > cursor
                    )
                rows = list(await session.scalars(stmt.with_for_update().limit(batch_size)))
                if not rows:
                    return
                for row in rows:
                    name = row.spec.get("display_name")
                    if not isinstance(name, str) or name == SEALED:
                        continue
                    if row.display_name_enc is None:
                        ref = PersonRef(row.org_id, row.site_id, row.id)
                        key = await vault.data_key(session, ref)
                        if key is not None:
                            row.display_name_enc = vault.encrypt(key, ref, "display_name", name)
                    row.spec = {**row.spec, "display_name": SEALED}
                    counts.directory_names += 1
                last = rows[-1]
                cursor = (last.org_id, last.site_id, last.id)


async def _backfill_investigations(
    db: Database, vault: PersonVault, batch_size: int, counts: BackfillCounts
) -> None:
    cursor: tuple[UUID, str] | None = None
    while True:
        with acting_as_job(BACKFILL_JOB):
            async with db.transaction() as session:
                stmt = (
                    select(InvestigationRow)
                    .where(InvestigationRow.site_id.is_not(None))
                    .order_by(InvestigationRow.org_id, InvestigationRow.id)
                )
                if cursor is not None:
                    stmt = stmt.where(tuple_(InvestigationRow.org_id, InvestigationRow.id) > cursor)
                rows = list(await session.scalars(stmt.with_for_update().limit(batch_size)))
                if not rows:
                    return
                ids = [row.id for row in rows]
                observations = list(
                    await session.scalars(
                        select(ObservationRow)
                        .where(ObservationRow.investigation_id.in_(ids))
                        .order_by(ObservationRow.investigation_id, ObservationRow.id)
                        .with_for_update()
                    )
                )
                events = list(
                    await session.scalars(
                        select(EventRow)
                        .where(EventRow.investigation_id.in_(ids))
                        .order_by(EventRow.investigation_id, EventRow.seq)
                        .with_for_update()
                    )
                )
                by_inv_observations: dict[str, list[ObservationRow]] = {}
                by_inv_events: dict[str, list[EventRow]] = {}
                for observation in observations:
                    by_inv_observations.setdefault(observation.investigation_id, []).append(
                        observation
                    )
                for event in events:
                    by_inv_events.setdefault(event.investigation_id, []).append(event)
                for row in rows:
                    assert row.site_id is not None
                    changed = await _seal_investigation(
                        session,
                        vault,
                        row,
                        by_inv_observations.get(row.id, []),
                        by_inv_events.get(row.id, []),
                        counts,
                    )
                    if changed:
                        counts.events_sanitized += changed
                last = rows[-1]
                cursor = (last.org_id, last.id)


async def _seal_investigation(
    session: AsyncSession,
    vault: PersonVault,
    row: InvestigationRow,
    observations: list[ObservationRow],
    events: list[EventRow],
    counts: BackfillCounts,
) -> int:
    assert row.site_id is not None
    request = copy.deepcopy(row.request)
    people = request.get("participants", [])
    names: dict[str, str] = {}
    event_created = next((event for event in events if event.type == "InvestigationCreated"), None)
    event_people = (
        event_created.payload.get("participants", []) if event_created is not None else []
    )
    for person in event_people:
        if isinstance(person, dict) and isinstance(person.get("id"), str):
            name = person.get("display_name")
            if isinstance(name, str) and name != SEALED:
                names[person["id"]] = name
    for person in people:
        if not isinstance(person, dict) or not isinstance(person.get("id"), str):
            continue
        person_id = person["id"]
        name = person.get("display_name")
        if isinstance(name, str) and name != SEALED:
            names[person_id] = name
        if person_id not in names:
            continue
        await vault.keep(
            session,
            PersonRef(row.org_id, row.site_id, person_id),
            investigation_id=row.id,
            kind="name",
            item=person_id,
            text=names[person_id],
        )
        if person.get("display_name") != SEALED:
            person["display_name"] = SEALED
            counts.investigation_names += 1

    report = request.get("report")
    report_event = next((event for event in events if event.type == "ReportReceived"), None)
    if isinstance(report, dict):
        reporter_id = report.get("reporter_id")
        report_text = report.get("text")
        if report_text == SEALED and report_event is not None:
            report_text = report_event.payload.get("text")
        if isinstance(reporter_id, str) and isinstance(report_text, str) and report_text != SEALED:
            await vault.keep(
                session,
                PersonRef(row.org_id, row.site_id, reporter_id),
                investigation_id=row.id,
                kind="report",
                item=reporter_id,
                text=report_text,
            )
            report["text"] = SEALED
            counts.reports += 1
    row.request = request
    if isinstance(row.outcome, dict):
        outcome = tokenized_names(row.outcome, names)
        if outcome != row.outcome:
            row.outcome = outcome
            counts.outcomes_sanitized += 1

    for observation in observations:
        transcript = observation.transcript
        if transcript is None:
            continue
        if transcript:
            await vault.keep(
                session,
                PersonRef(row.org_id, row.site_id, observation.participant_id),
                investigation_id=row.id,
                kind="transcript",
                item=observation.id,
                text=transcript,
            )
            counts.transcripts += 1
        observation.transcript = None

    changed_events = 0
    seal_event: EventRow | None = None
    ordered_log: list[tuple[str, dict[str, Any]]] = []
    for event in sorted(events, key=lambda item: item.seq):
        payload = copy.deepcopy(event.payload)
        changed = False
        if event.type == "InvestigationCreated":
            for person in payload.get("participants", []):
                if not isinstance(person, dict):
                    continue
                person_id = person.get("id")
                if person.get("display_name") != SEALED and person.get("display_name") is not None:
                    if isinstance(person_id, str):
                        names.setdefault(person_id, person["display_name"])
                    person["display_name"] = SEALED
                    changed = True
        elif event.type == "ReportReceived":
            if payload.get("text") != SEALED and payload.get("text") is not None:
                payload["text"] = SEALED
                changed = True
        elif event.type == "ObservationRecorded":
            extraction = payload.get("extraction")
            if isinstance(extraction, dict) and extraction.get("evidence"):
                extraction["evidence"] = []
                changed = True
        elif event.type == "IntakeUnmapped":
            if payload.get("evidence"):
                payload["evidence"] = []
                changed = True
        elif event.type in {
            "DisagreementExplained",
            "PlanComputed",
            "VerificationResult",
            "Reopened",
            "DecisionReached",
            "Abstained",
        }:
            sanitized = tokenized_names(payload, names)
            if sanitized != payload:
                payload = sanitized
                changed = True
        if event.type == "GroundTruthRevealed":
            seal_event = event
        if changed:
            event.payload = payload
            changed_events += 1
        ordered_log.append((event.type, payload))

    if changed_events and seal_event is not None:
        seal_index = next(
            index for index, event in enumerate(events) if event.seq == seal_event.seq
        )
        reveal = copy.deepcopy(seal_event.payload)
        reveal["log"] = {
            "sha256": log_digest(ordered_log[:seal_index]),
            "events": seal_index,
        }
        seal_event.payload = reveal
        counts.log_seals_rehashed += 1
    return changed_events
