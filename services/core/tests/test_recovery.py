"""Deterministic recovery: replay from the event log reproduces the recorded belief exactly,
and a restarted core continues an investigation where the previous process stopped."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from core_testkit import body, core_settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from participant_bot import answer_pending, run_to_conclusion
from sqlalchemy.ext.asyncio import create_async_engine
from test_closing_loop import approve, decided, reset_in_simulator, verify

from pramana_core.main import create_app
from pramana_engine import MODEL_VERSION

pytestmark = pytest.mark.db


def replay(core: TestClient, inv_id: str) -> dict[str, Any]:
    r = core.get(f"/v1/investigations/{inv_id}/replay")
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def assert_identical(core: TestClient, inv_id: str) -> dict[str, Any]:
    rep = replay(core, inv_id)
    assert rep["identical"], (rep["replayed_sha256"], rep["recorded_sha256"])
    assert rep["replayed_sha256"] == rep["recorded_sha256"]
    assert rep["final_belief"] == rep["recorded_belief"]
    live = core.get(f"/v1/investigations/{inv_id}").json()["belief"]
    assert rep["final_belief"] == live
    return rep


def restart(migrated_db: str, sim_app: FastAPI) -> TestClient:
    """A brand-new core process on the same database (nothing carried over in memory)."""
    app = create_app(core_settings(migrated_db), sim_transport=httpx.ASGITransport(app=sim_app))
    return TestClient(app)


def test_replay_is_identical_through_repair_and_verification(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv = decided(core, sim, "CB_C2_7.tripped")
    assert_identical(core, inv["id"])
    _, aid = approve(core, inv)
    reset_in_simulator(core, sim, inv["id"], aid)
    state = core.post(
        f"/v1/investigations/{inv['id']}/interventions",
        json={"approval_id": aid, "participant_id": "p_imran"},
    ).json()
    assert_identical(core, inv["id"])
    final = verify(core, sim, state)
    assert final["status"] == "verified"
    rep = assert_identical(core, inv["id"])
    assert rep["final_belief"]["repair"]["fixed_probability"] >= 0.97
    core.post(f"/v1/investigations/{inv['id']}/reveal")
    rep = assert_identical(core, inv["id"])
    assert rep["status"] == "closed"
    assert rep["events_replayed"] == len(core.get(f"/v1/investigations/{inv['id']}/events").json())


def test_replay_is_identical_after_a_failed_verification_reopens(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    lies = {"nvr_screen": "off", "breaker_c2_7": "tripped"}
    inv = decided(core, sim, "SW_C2.dead", override=lies)
    _, aid = approve(core, inv)
    reset_in_simulator(core, sim, inv["id"], aid)
    state = core.post(
        f"/v1/investigations/{inv['id']}/interventions",
        json={"approval_id": aid, "participant_id": "p_imran"},
    ).json()
    while state["status"] == "verifying":
        state = answer_pending(core, sim, state, override=lies)["state"]
        assert_identical(core, inv["id"])
    types = [e["type"] for e in core.get(f"/v1/investigations/{inv['id']}/events").json()]
    assert "Reopened" in types
    final, _ = run_to_conclusion(core, sim, state, override=lies)
    assert_identical(core, inv["id"])
    assert final["belief"]["repair"] is None


def test_replay_is_identical_while_a_spoken_answer_awaits_confirmation(
    core: TestClient,
) -> None:
    """A decision-critical spoken answer moves the belief before it is confirmed; the log
    records that, so replay and the console agree during the confirmation."""
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    state = core.post("/v1/investigations", json=body(fault="CB_C2_7.tripped")).json()
    confirming = False
    for _ in range(12):
        q = state["pending_question"]
        if q is None:
            break
        if q["kind"] == "confirm":
            confirming = True
            assert_identical(core, state["id"])
        tok = core.post(
            f"/v1/investigations/{state['id']}/participants/{q['action']['participant_id']}/token"
        ).json()
        h = {"Authorization": f"Bearer {tok['token']}"}
        if q["action"]["requires_move"]:
            sim.post(
                f"/sim/v1/scenarios/{tok['scenario_id']}/move",
                json={"to": q["action"]["location_id"]},
                headers=h,
            )
        seen = sim.post(
            f"/sim/v1/scenarios/{tok['scenario_id']}/observe",
            json={"probe_id": q["action"]["probe_id"]},
            headers=h,
        ).json()
        r = core.post(
            f"/v1/investigations/{state['id']}/answers",
            json={
                "question_id": q["id"],
                "participant_id": q["action"]["participant_id"],
                "outcome": seen["value"],
                "modality": "voice",
            },
        )
        assert r.status_code == 200, r.text
        state = r.json()["state"]
        assert_identical(core, state["id"])
    assert confirming, "no spoken answer was decision-critical in this run"


def test_restarted_core_recovers_and_continues(
    core: TestClient, migrated_db: str, sim_app: FastAPI
) -> None:
    sim = TestClient(sim_app)
    state = core.post("/v1/investigations", json=body(fault="CB_C2_7.tripped")).json()
    state = answer_pending(core, sim, state)["state"]
    before = core.get(f"/v1/investigations/{state['id']}").json()
    # The first process "crashes": its in-memory engines are gone. A new one boots.
    with restart(migrated_db, sim_app) as core2:
        report = core2.app.state.recovery  # type: ignore[attr-defined]
        assert report["checked"] >= 1
        assert report["mismatched"] == []
        assert report["failed"] == []
        after = core2.get(f"/v1/investigations/{state['id']}").json()
        assert after == before
        final, path = run_to_conclusion(core2, sim, after)
        assert final["status"] == "decided"
        assert final["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"
        assert len(path) + 1 <= 6  # one question was answered before the crash
        assert_identical(core2, state["id"])
        # The old process's question is gone: answering it again is refused.
        q = before["pending_question"]
        stale = core2.post(
            f"/v1/investigations/{state['id']}/answers",
            json={
                "question_id": q["id"],
                "participant_id": q["action"]["participant_id"],
                "text": "haan",
            },
        )
        assert stale.status_code == 409


def test_recovery_flags_a_log_that_does_not_replay(
    core: TestClient, migrated_db: str, sim_app: FastAPI
) -> None:
    state = core.post("/v1/investigations", json=body(fault="CB_C2_7.tripped")).json()
    inv_id = state["id"]

    async def tamper() -> None:
        engine = create_async_engine(migrated_db)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "update events set payload = jsonb_set(payload, '{hypothesis_entropy_bits}', "
                "'0.5') where seq = (select max(seq) from events where investigation_id = $1 "
                "and type = 'BeliefUpdated')",
                (inv_id,),
            )
        await engine.dispose()

    asyncio.run(tamper())
    with restart(migrated_db, sim_app) as core2:
        report = core2.app.state.recovery  # type: ignore[attr-defined]
        assert inv_id in report["mismatched"]
        assert replay(core2, inv_id)["identical"] is False
        events = core2.get(f"/v1/investigations/{inv_id}/events").json()
        err = [e["payload"] for e in events if e["type"] == "EngineError"]
        assert err
        assert err[-1]["reason"] == "replay_mismatch"


def test_replay_of_unknown_investigation_is_404(core: TestClient) -> None:
    assert core.get("/v1/investigations/inv_nope/replay").status_code == 404


def test_a_log_from_an_older_engine_is_an_upgrade_not_corruption(
    core: TestClient, migrated_db: str, sim_app: FastAPI
) -> None:
    state = core.post("/v1/investigations", json=body(fault="CB_C2_7.tripped")).json()
    inv_id = state["id"]
    created = core.get(f"/v1/investigations/{inv_id}/events").json()[0]
    assert created["type"] == "InvestigationCreated"
    assert created["payload"]["engine_model_version"] == MODEL_VERSION

    async def as_if_written_by_model_1() -> None:
        # An old log: no version stamp, and a belief the current model would not produce.
        engine = create_async_engine(migrated_db)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "update events set payload = payload - 'engine_model_version' "
                "where investigation_id = $1 and type = 'InvestigationCreated'",
                (inv_id,),
            )
            await conn.exec_driver_sql(
                "update events set payload = jsonb_set(payload, '{hypothesis_entropy_bits}', "
                "'0.5') where seq = (select max(seq) from events where investigation_id = $1 "
                "and type = 'BeliefUpdated')",
                (inv_id,),
            )
        await engine.dispose()

    asyncio.run(as_if_written_by_model_1())
    with restart(migrated_db, sim_app) as core2:
        report = core2.app.state.recovery  # type: ignore[attr-defined]
        assert inv_id in report["engine_changed"]
        assert inv_id not in report["mismatched"]
        check = replay(core2, inv_id)
        assert check["identical"] is False
        assert check["engine_changed"] is True
        assert check["recorded_model_version"] == "1"
        assert check["current_model_version"] == MODEL_VERSION
        events = core2.get(f"/v1/investigations/{inv_id}/events").json()
        assert not [e for e in events if e["type"] == "EngineError"]
