"""Rebuild an investigation's belief from nothing but its public event log.

This is a client-side replay: it reads ``GET /v1/investigations/{id}/events`` and folds the
events into a fresh engine, using only what the events carry. If it reproduces the server's
belief byte for byte, the log is a complete record of the investigation (ADR 0003).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from pramana_contracts import Directness, Hedge, Modality, ParticipantSpec
from pramana_domain import load_pack
from pramana_engine import Engine, Evidence, compile_pack


def canonical(obj: Any) -> str:
    """One byte representation per value: sorted keys, no whitespace, exact float repr."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def all_events(core: httpx.Client, inv_id: str, page: int = 7) -> list[dict[str, Any]]:
    """Read the whole log in small pages, resuming from the last ``seq`` seen."""
    out: list[dict[str, Any]] = []
    after = 0
    while True:
        r = core.get(
            f"/v1/investigations/{inv_id}/events", params={"after_seq": after, "limit": page}
        )
        r.raise_for_status()
        batch: list[dict[str, Any]] = r.json()
        if not batch:
            return out
        out.extend(batch)
        after = batch[-1]["seq"]


def replay(events: list[dict[str, Any]]) -> Engine:
    created = next(e for e in events if e["type"] == "InvestigationCreated")["payload"]
    people = [ParticipantSpec.model_validate(p) for p in created["participants"]]
    engine = Engine(compile_pack(load_pack(created["pack_id"])), people)
    for e in events:
        t, p = e["type"], e["payload"]
        if t == "QuestionAsked":
            engine.record_question(p["action"]["participant_id"])
        elif t == "ObservationRecorded":
            ev = p["evidence"]
            engine.observe(
                Evidence(
                    ev["participant_id"],
                    ev["probe_id"],
                    ev["location_id"],
                    ev["outcome"],
                    Hedge(ev["hedge"]),
                    Directness(ev["directness"]),
                    Modality(ev.get("modality", "text")),
                )
            )
        elif t == "ParticipantUnavailable":
            engine.set_available(p["participant_id"], False)
        elif t == "ObservationConfirmed" and p.get("agreed") is not None:
            engine.confirm(p["participant_id"], p["probe_id"], p["location_id"], bool(p["agreed"]))
        elif t == "Reopened":
            engine.reopen()
        elif t == "InterventionReported":
            engine.apply_intervention(p["action"], p["target"], p["participant_id"])
    return engine


def replayed_belief(events: list[dict[str, Any]]) -> str:
    return canonical(replay(events).snapshot().model_dump(mode="json"))


def last_logged_belief(events: list[dict[str, Any]]) -> str:
    return canonical([e for e in events if e["type"] == "BeliefUpdated"][-1]["payload"])
