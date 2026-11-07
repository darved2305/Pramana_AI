"""The reveal seals the event log: editing any earlier event afterwards is detected.

Replay proves the belief follows from the log. It cannot notice an edit that leaves the belief
alone (a reason, a transcript, an extraction) or an edit made consistently to evidence and
belief. The digest recorded at reveal covers every event before it, in order.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core_testkit import body
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.db


def _revealed(core: TestClient) -> dict[str, Any]:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    r = core.post("/v1/investigations", json=body(fault="DNS.down"))
    final, _ = run_to_conclusion(core, sim, r.json())
    assert final["status"] in ("decided", "abstained")
    assert core.post(f"/v1/investigations/{final['id']}/reveal").status_code == 200
    return final


def _sql(db_url: str, statement: str) -> None:
    async def run() -> None:
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(statement)
        await engine.dispose()

    asyncio.run(run())


def test_the_reveal_records_a_digest_of_everything_before_it(core: TestClient) -> None:
    inv = _revealed(core)
    events = core.get(f"/v1/investigations/{inv['id']}/events?limit=500").json()
    revealed = next(e for e in events if e["type"] == "GroundTruthRevealed")["payload"]
    before = [
        e
        for e in events
        if e["seq"] < next(e["seq"] for e in events if e["type"] == "GroundTruthRevealed")
    ]
    assert revealed["log"]["events"] == len(before)
    assert len(revealed["log"]["sha256"]) == 64
    replay = core.get(f"/v1/investigations/{inv['id']}/replay").json()
    assert replay["identical"] is True
    assert replay["log_sealed"] is True
    assert replay["log_intact"] is True


def test_an_edit_after_the_reveal_is_detected_even_when_the_belief_is_unchanged(
    core: TestClient, migrated_db: str
) -> None:
    inv = _revealed(core)
    # Rewrite what someone said, leaving the evidence (and so the belief) untouched.
    _sql(
        migrated_db,
        "update events set payload = jsonb_set(payload, '{reason}', '\"edited later\"') "
        f"where investigation_id = '{inv['id']}' and type = 'ObservationRecorded' "
        "and seq = (select min(seq) from events where investigation_id = "
        f"'{inv['id']}' and type = 'ObservationRecorded')",
    )
    replay = core.get(f"/v1/investigations/{inv['id']}/replay").json()
    assert replay["identical"] is True  # replay alone cannot see this edit
    assert replay["log_intact"] is False


def test_deleting_an_event_or_changing_the_order_is_detected(
    core: TestClient, migrated_db: str
) -> None:
    inv = _revealed(core)
    _sql(
        migrated_db,
        f"delete from events where investigation_id = '{inv['id']}' and type = 'PlanComputed' "
        "and seq = (select min(seq) from events where investigation_id = "
        f"'{inv['id']}' and type = 'PlanComputed')",
    )
    assert core.get(f"/v1/investigations/{inv['id']}/replay").json()["log_intact"] is False


def test_an_open_investigation_is_not_sealed_yet(core: TestClient) -> None:
    r = core.post("/v1/investigations", json=body(fault="DNS.down"))
    replay = core.get(f"/v1/investigations/{r.json()['id']}/replay").json()
    assert replay["log_sealed"] is False
    assert replay["log_intact"] is None
