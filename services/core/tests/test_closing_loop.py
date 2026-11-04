"""Decision -> human approval -> capability -> repair in the simulator -> verification."""

from __future__ import annotations

from typing import Any

import pytest
from core_testkit import body
from fastapi.testclient import TestClient
from participant_bot import answer_pending, run_to_conclusion

pytestmark = pytest.mark.db


def decided(core: TestClient, sim: TestClient, fault: str, **kw: Any) -> dict[str, Any]:
    r = core.post("/v1/investigations", json=body(fault=fault))
    assert r.status_code == 201, r.text
    final, _ = run_to_conclusion(core, sim, r.json(), **kw)
    assert final["status"] == "decided", final["plan"]["reason"]
    assert final["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"
    return final


def approve(core: TestClient, inv: dict[str, Any]) -> tuple[dict[str, Any], str]:
    url = f"/v1/investigations/{inv['id']}/approvals"
    r = core.post(
        url, json={"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_imran"}
    )
    assert r.status_code == 201, r.text
    state = r.json()
    assert state["status"] == "awaiting_approval"
    aid = state["approvals"][0]["id"]
    assert state["approvals"][0]["risk"] == "medium"
    assert "DISPATCH_ELECTRICIAN_DB_C2" in state["approvals"][0]["rationale"]
    r = core.post(f"{url}/{aid}/decision", json={"decision": "approve", "approver_id": "u_mgr"})
    assert r.json()["status"] == "acting"
    return r.json(), aid


def reset_in_simulator(core: TestClient, sim: TestClient, inv_id: str, aid: str) -> None:
    grant = core.post(
        f"/v1/investigations/{inv_id}/approvals/{aid}/capability",
        params={"participant_id": "p_imran"},
    )
    assert grant.status_code == 200, grant.text
    g = grant.json()
    assert (
        "breaker" in g["instructions"].lower()
        or "ब्रेकर" in g["instructions"]
        or "CB_C2_7" in g["instructions"]
    )
    tok = core.post(f"/v1/investigations/{inv_id}/participants/p_imran/token").json()
    h = {"Authorization": f"Bearer {tok['token']}"}
    sid = tok["scenario_id"]
    sim.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "DB_C2_PANEL"}, headers=h)
    done = sim.post(
        f"/sim/v1/scenarios/{sid}/act",
        headers=h,
        json={"action": "reset_breaker", "target": "CB_C2_7", "capability": g["capability"]},
    )
    assert done.status_code == 200, done.text


def verify(core: TestClient, sim: TestClient, state: dict[str, Any]) -> dict[str, Any]:
    for _ in range(8):
        if state["pending_question"] is None:
            return state
        assert state["status"] == "verifying"
        state = answer_pending(core, sim, state)["state"]
    raise AssertionError("verification did not finish")


def test_full_closing_loop_verifies_the_repair(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv = decided(core, sim, "CB_C2_7.tripped")
    _, aid = approve(core, inv)
    reset_in_simulator(core, sim, inv["id"], aid)
    r = core.post(
        f"/v1/investigations/{inv['id']}/interventions",
        json={"approval_id": aid, "participant_id": "p_imran"},
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["status"] == "verifying"
    assert state["belief"]["repair"]["post_repair_observations"] == 0
    assert state["pending_question"] is not None  # a confident diagnosis is not a verification
    final = verify(core, sim, state)
    assert final["status"] == "verified", final["plan"]["reason"]
    assert final["belief"]["repair"]["fixed_probability"] >= 0.97
    assert final["approvals"][0]["status"] == "executed"
    gt = core.post(f"/v1/investigations/{inv['id']}/reveal").json()["ground_truth"]
    assert gt["correct"] is True
    types = [e["type"] for e in core.get(f"/v1/investigations/{inv['id']}/events").json()]
    for t in (
        "ApprovalRequested",
        "ApprovalDecided",
        "CapabilityIssued",
        "InterventionReported",
        "VerificationResult",
        "GroundTruthRevealed",
    ):
        assert t in types


def test_misled_diagnosis_fails_verification_and_reopens(core: TestClient) -> None:
    """People misreported the closet; the switch was dead. The reset changes nothing, so
    verification fails and the investigation reopens with the alternatives promoted."""
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
    events = core.get(f"/v1/investigations/{inv['id']}/events").json()
    verdicts = [e["payload"] for e in events if e["type"] == "VerificationResult"]
    assert verdicts[-1]["rule"] == "verification_failed"
    assert "Reopened" in [e["type"] for e in events]
    assert state["status"] in ("investigating", "decided", "abstained")
    assert state["belief"]["repair"] is None


def test_approval_rules(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv = decided(core, sim, "CB_C2_7.tripped")
    url = f"/v1/investigations/{inv['id']}/approvals"
    student = core.post(
        url, json={"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_riya"}
    )
    assert student.status_code == 403
    wrong_target = core.post(
        url, json={"action": "reset_breaker", "target": "SW_C2", "participant_id": "p_imran"}
    )
    assert wrong_target.status_code == 422
    state = core.post(
        url, json={"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_imran"}
    ).json()
    aid = state["approvals"][0]["id"]
    early = core.post(f"{url}/{aid}/capability", params={"participant_id": "p_imran"})
    assert early.status_code == 409  # not approved yet
    core.post(f"{url}/{aid}/decision", json={"decision": "approve", "approver_id": "u_mgr"})
    assert (
        core.post(
            f"{url}/{aid}/decision", json={"decision": "deny", "approver_id": "u_mgr"}
        ).status_code
        == 409
    )
    other = core.post(f"{url}/{aid}/capability", params={"participant_id": "p_mahesh"})
    assert other.status_code == 403
    no_cap = core.post(
        f"/v1/investigations/{inv['id']}/interventions",
        json={"approval_id": aid, "participant_id": "p_imran"},
    )
    assert no_cap.status_code == 409
    assert (
        core.post(f"{url}/{aid}/capability", params={"participant_id": "p_imran"}).status_code
        == 200
    )
    again = core.post(f"{url}/{aid}/capability", params={"participant_id": "p_imran"})
    assert again.status_code == 409  # one capability per approval


def test_denied_approval_returns_to_the_decision(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv = decided(core, sim, "CB_C2_7.tripped")
    url = f"/v1/investigations/{inv['id']}/approvals"
    aid = core.post(
        url, json={"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_imran"}
    ).json()["approvals"][0]["id"]
    r = core.post(
        f"{url}/{aid}/decision",
        json={"decision": "deny", "approver_id": "u_mgr", "note": "after hours"},
    )
    assert r.json()["status"] == "decided"
    assert r.json()["approvals"][0]["status"] == "denied"


def test_approval_needs_a_decision_that_calls_for_it(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    r = core.post("/v1/investigations", json=body(fault="DNS.down"))
    final, _ = run_to_conclusion(core, sim, r.json())
    res = core.post(
        f"/v1/investigations/{final['id']}/approvals",
        json={"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_imran"},
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ACTION_NOT_INDICATED"


def test_verification_survives_an_engine_rebuild(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv = decided(core, sim, "CB_C2_7.tripped")
    _, aid = approve(core, inv)
    reset_in_simulator(core, sim, inv["id"], aid)
    state = core.post(
        f"/v1/investigations/{inv['id']}/interventions",
        json={"approval_id": aid, "participant_id": "p_imran"},
    ).json()
    state = answer_pending(core, sim, state)["state"]
    live = core.get(f"/v1/investigations/{inv['id']}").json()
    core.app.state.investigations.evict(inv["id"])  # type: ignore[attr-defined]
    rebuilt = core.get(f"/v1/investigations/{inv['id']}").json()
    assert rebuilt["belief"] == live["belief"]
