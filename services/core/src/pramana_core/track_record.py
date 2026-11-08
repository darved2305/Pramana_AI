"""How often each person's answers matched what was later shown to be true.

Only investigations whose truth is known count: a revealed sealed fault (practice runs today;
a technician's confirmed cause once live mode exists). For each committed answer given before
any repair, the site model pinned by that investigation says what the true fault would have
shown at that check; the answer either matches or not. Nothing is inferred from investigations
whose cause is still uncertain, so the record never rewards agreeing with Pramana's own guess.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import CheckRecord, PersonTrackRecord
from pramana_domain import World
from pramana_domain.spec_storage import load_spec

from .db import EventRow, InvestigationRow, ObservationRow, SiteModelRow

COUNTED_STATES = ("committed", "superseded")


async def track_records(
    session: AsyncSession, org_id: uuid.UUID, site_id: uuid.UUID
) -> list[PersonTrackRecord]:
    investigations = list(
        await session.scalars(
            select(InvestigationRow).where(
                InvestigationRow.org_id == org_id,
                InvestigationRow.site_id == site_id,
                InvestigationRow.ground_truth.is_not(None),
            )
        )
    )
    if not investigations:
        return []
    inv_ids = [i.id for i in investigations]
    model_ids = {i.site_model_id for i in investigations if i.site_model_id}
    models = {
        m.id: load_spec(m.spec)
        for m in await session.scalars(
            select(SiteModelRow).where(
                SiteModelRow.org_id == org_id, SiteModelRow.id.in_(model_ids)
            )
        )
    }
    repaired_at: dict[str, datetime] = dict(
        (
            await session.execute(
                select(EventRow.investigation_id, func.min(EventRow.ts))
                .where(
                    EventRow.investigation_id.in_(inv_ids),
                    EventRow.type == "InterventionReported",
                )
                .group_by(EventRow.investigation_id)
            )
        ).all()
    )
    observations = list(
        await session.scalars(
            select(ObservationRow).where(
                ObservationRow.investigation_id.in_(inv_ids),
                ObservationRow.state.in_(COUNTED_STATES),
            )
        )
    )

    worlds: dict[str, tuple[Any, World]] = {}
    for inv in investigations:
        pack = models.get(inv.site_model_id) if inv.site_model_id else None
        reveal = (inv.ground_truth or {}).get("reveal") or {}
        faults = {
            (f["component_id"], f["mode"])
            for f in (reveal.get("fault_spec") or {}).get("faults", [])
        }
        if pack is not None:
            try:
                worlds[inv.id] = (pack, World(pack, frozenset(faults)))
            except ValueError:
                continue  # a fault the model cannot express: no basis for judging answers

    per: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    seen_in: dict[str, set[str]] = defaultdict(set)
    for obs in observations:
        found = worlds.get(obs.investigation_id)
        if found is None:
            continue
        cutoff = repaired_at.get(obs.investigation_id)
        if cutoff is not None and obs.committed_at >= cutoff:
            continue  # after a repair the world changed; the revealed fault no longer applies
        pack, world = found
        probe = pack.probe_by_id.get(obs.probe_id)
        if probe is None or obs.outcome not in probe.outcomes:
            continue
        try:
            truth = world.observe(probe, obs.location_id)
        except ValueError:
            continue
        counts = per[obs.participant_id][probe.probe_class]
        counts[0] += 1
        counts[1] += int(obs.outcome == truth)
        seen_in[obs.participant_id].add(obs.investigation_id)

    records = []
    for person, classes in sorted(per.items()):
        checked = sum(c[0] for c in classes.values())
        matched = sum(c[1] for c in classes.values())
        records.append(
            PersonTrackRecord(
                person_id=person,
                investigations=len(seen_in[person]),
                checked=checked,
                matched=matched,
                by_kind=[
                    CheckRecord(kind=kind, checked=c[0], matched=c[1])
                    for kind, c in sorted(classes.items())
                ],
            )
        )
    return records
