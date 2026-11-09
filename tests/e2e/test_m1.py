"""M1 acceptance, against real simulator and core processes over HTTP.

Scenario S1: breaker CB_C2_7 has tripped (sealed in the simulator). Riya (student, floor 3),
Mahesh (guard) and Imran (electrician) answer in text, each seeing the world only through the
simulator with their own participant token. The core never sees the fault.

Acceptance (docs/PLAN.md section 26, Thu Nov 5):
1. The engine reaches DISPATCH_ELECTRICIAN_DB_C2 in 6 questions or fewer.
2. Approval: request, deny, request again, approve; collect the capability; act in the
   simulator; report the intervention; answer verification questions; reach ``verified``.
   A misled diagnosis instead fails verification and reopens.
3. Replaying the event log reproduces the final belief byte for byte.
Plus: a hard crash of the core mid-investigation loses nothing.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx
import pytest
from core_testkit import body
from participant_bot import answer_pending, run_to_conclusion

from e2e.harness import Services
from e2e.replay import all_events, canonical, last_logged_belief, replayed_belief
from pramana_contracts.tokens import mint_capability, private_key_from_b64

pytestmark = pytest.mark.e2e

S1 = "CB_C2_7.tripped"
DISPATCH = "DISPATCH_ELECTRICIAN_DB_C2"
KEYS = ("belief", "plan", "pending_question", "status")
LIES = {"nvr_screen": "off", "breaker_c2_7": "tripped"}  # misreports that frame the breaker


def create(core: httpx.Client, fault: str) -> dict[str, Any]:
    r = core.post("/v1/investigations", json=body(fault=fault))
    assert r.status_code == 201, r.text
    inv: dict[str, Any] = r.json()
    assert inv["status"] == "investigating"
    assert len(inv["sealed_commitment"]) == 64  # SHA-256 published before the first question
    assert inv["pending_question"] is not None
    return inv


def token(core: httpx.Client, inv_id: str, pid: str) -> tuple[str, dict[str, str]]:
    r = core.post(f"/v1/investigations/{inv_id}/participants/{pid}/token")
    assert r.status_code == 200, r.text
    return r.json()["scenario_id"], {"Authorization": f"Bearer {r.json()['token']}"}


def assert_replay_matches(core: httpx.Client, inv_id: str) -> str:
    events = all_events(core, inv_id)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(set(seqs)), "events out of order or duplicated"
    assert seqs == [e["seq"] for e in core.get(f"/v1/investigations/{inv_id}/events").json()]
    rebuilt = replayed_belief(events)
    assert rebuilt == last_logged_belief(events)
    state = core.get(f"/v1/investigations/{inv_id}").json()
    assert rebuilt == canonical(state["belief"])
    return rebuilt


def approve_and_repair(
    services: Services, core: httpx.Client, sim: httpx.Client, inv: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Deny once, approve the second request, then carry out the reset with the capability."""
    url = f"/v1/investigations/{inv['id']}/approvals"
    req = {"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_imran"}

    first = core.post(url, json=req)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "awaiting_approval"
    a1 = first.json()["approvals"][0]
    assert (a1["risk"], a1["reversible"], a1["status"]) == ("medium", True, "pending")
    assert core.post(url, json=req).status_code == 409  # one pending request at a time
    denied = core.post(
        f"{url}/{a1['id']}/decision",
        json={"decision": "deny", "approver_id": "u_mgr", "note": "check again"},
    )
    assert denied.status_code == 200, denied.text
    assert denied.json()["status"] == "decided"
    no_cap = core.post(f"{url}/{a1['id']}/capability", params={"participant_id": "p_imran"})
    assert no_cap.status_code == 409  # a denied approval yields nothing

    second = core.post(url, json=req)
    assert second.status_code == 201, second.text
    aid = second.json()["approvals"][-1]["id"]
    approved = core.post(
        f"{url}/{aid}/decision", json={"decision": "approve", "approver_id": "u_mgr"}
    )
    assert approved.json()["status"] == "acting"

    assert (
        core.post(f"{url}/{aid}/capability", params={"participant_id": "p_mahesh"}).status_code
        == 403
    )
    grant = core.post(f"{url}/{aid}/capability", params={"participant_id": "p_imran"})
    assert grant.status_code == 200, grant.text
    g = grant.json()
    ttl = datetime.fromisoformat(g["expires_at"]).timestamp() - time.time()
    assert 240 < ttl <= 301  # five minutes
    again = core.post(f"{url}/{aid}/capability", params={"participant_id": "p_imran"})
    assert again.status_code == 200, again.text  # a reload gets the same, still single-use
    assert again.json()["capability"] == g["capability"]

    sid, imran = token(core, inv["id"], "p_imran")
    act = f"/sim/v1/scenarios/{sid}/act"
    action = {"action": "reset_breaker", "target": "CB_C2_7"}

    # The capability names Imran: Mahesh cannot use it, even holding the token.
    _, mahesh = token(core, inv["id"], "p_mahesh")
    stolen = sim.post(act, headers=mahesh, json=action | {"capability": g["capability"]})
    assert stolen.status_code == 403, stolen.text

    # The capability carries no clock override, so expiry is shown with a token signed by the
    # same core key whose 5-minute lifetime ended ten minutes ago.
    stale, _ = mint_capability(
        private_key_from_b64(services.signing_key),
        scenario_id=sid,
        investigation_id=inv["id"],
        participant_id="p_imran",
        action="reset_breaker",
        target="CB_C2_7",
        now=time.time() - 900,
    )
    expired = sim.post(act, headers=imran, json=action | {"capability": stale})
    assert expired.status_code == 403
    assert "expired" in expired.text

    # Imran may already be at the panel (he could have been asked to read the breaker): step
    # out first, to show the simulator refuses an action from anywhere but the target.
    if sim.get(f"/sim/v1/scenarios/{sid}/view", headers=imran).json()["location_id"] != (
        "MAINT_ROOM"
    ):
        out = sim.post(f"/sim/v1/scenarios/{sid}/move", headers=imran, json={"to": "MAINT_ROOM"})
        assert out.status_code == 200, out.text
    away = sim.post(act, headers=imran, json=action | {"capability": g["capability"]})
    assert away.status_code == 409, away.text  # must stand at the panel
    assert "NOT_AT_TARGET" in away.text
    moved = sim.post(f"/sim/v1/scenarios/{sid}/move", headers=imran, json={"to": "DB_C2_PANEL"})
    assert moved.status_code == 200, moved.text
    done = sim.post(act, headers=imran, json=action | {"capability": g["capability"]})
    assert done.status_code == 200, done.text
    assert set(done.json()) == {"action", "target", "performed"}  # says nothing about the fault
    reused = sim.post(act, headers=imran, json=action | {"capability": g["capability"]})
    assert reused.status_code == 409
    assert "CAPABILITY_USED" in reused.text

    reported = core.post(
        f"/v1/investigations/{inv['id']}/interventions",
        json={"approval_id": aid, "participant_id": "p_imran"},
    )
    assert reported.status_code == 200, reported.text
    state: dict[str, Any] = reported.json()
    assert state["status"] == "verifying"
    assert state["belief"]["repair"]["post_repair_observations"] == 0
    assert state["pending_question"] is not None
    twice = core.post(
        f"/v1/investigations/{inv['id']}/interventions",
        json={"approval_id": aid, "participant_id": "p_imran"},
    )
    assert twice.status_code == 409
    return state, aid


def test_s1_text_mode_end_to_end(services: Services, core: httpx.Client, sim: httpx.Client) -> None:
    inv = create(core, S1)
    sid, riya = token(core, inv["id"], "p_riya")
    view = sim.get(f"/sim/v1/scenarios/{sid}/view", headers=riya)
    assert view.status_code == 200, view.text
    assert sim.get(f"/sim/v1/scenarios/{sid}/truth").status_code in (403, 404)

    decided, path = run_to_conclusion(core, sim, inv)
    assert decided["status"] == "decided", decided["plan"]["reason"]
    assert decided["plan"]["decision_class"] == DISPATCH
    assert decided["questions_asked"] <= 6, path
    assert len(path) <= 6
    assert decided["belief"]["map_decision"] == DISPATCH
    assert_replay_matches(core, inv["id"])

    state, _ = approve_and_repair(services, core, sim, decided)
    for _ in range(8):
        if state["pending_question"] is None:
            break
        assert state["status"] == "verifying"
        state = answer_pending(core, sim, state)["state"]
    assert state["status"] == "verified", state["plan"]["reason"]
    assert state["belief"]["repair"]["fixed_probability"] >= 0.97
    statuses = [a["status"] for a in state["approvals"]]
    assert statuses == ["denied", "executed"]

    final_belief = assert_replay_matches(core, inv["id"])
    revealed = core.post(f"/v1/investigations/{inv['id']}/reveal")
    assert revealed.status_code == 200, revealed.text
    gt = revealed.json()["ground_truth"]
    assert gt["reveal"]["commitment_verified"] is True
    assert gt["reveal"]["commitment"] == inv["sealed_commitment"]
    assert gt["correct"] is True
    assert [f["component_id"] for f in gt["reveal"]["fault_spec"]["faults"]] == ["CB_C2_7"]
    assert revealed.json()["status"] == "closed"
    assert assert_replay_matches(core, inv["id"]) == final_belief  # reveal changes no belief

    types = [e["type"] for e in all_events(core, inv["id"])]
    for t in (
        "InvestigationCreated",
        "QuestionAsked",
        "ObservationRecorded",
        "DecisionReached",
        "ApprovalRequested",
        "ApprovalDecided",
        "CapabilityIssued",
        "InterventionReported",
        "VerificationResult",
        "GroundTruthRevealed",
    ):
        assert t in types, t
    assert types.count("ApprovalDecided") == 2


def test_misled_diagnosis_fails_verification_and_reopens(
    services: Services, core: httpx.Client, sim: httpx.Client
) -> None:
    """The switch is dead, but two people misreport the closet. The reset changes nothing."""
    inv = create(core, "SW_C2.dead")
    decided, _ = run_to_conclusion(core, sim, inv, override=LIES)
    assert decided["status"] == "decided"
    assert decided["plan"]["decision_class"] == DISPATCH
    state, _ = approve_and_repair(services, core, sim, decided)
    for _ in range(10):
        if state["status"] != "verifying":
            break
        state = answer_pending(core, sim, state, override=LIES)["state"]
    events = all_events(core, inv["id"])
    verdicts = [e["payload"] for e in events if e["type"] == "VerificationResult"]
    assert verdicts[-1]["rule"] == "verification_failed"
    assert "Reopened" in [e["type"] for e in events]
    assert state["belief"]["repair"] is None
    assert state["status"] in ("investigating", "decided", "abstained")
    assert_replay_matches(core, inv["id"])


def _answer_n(
    core: httpx.Client, sim: httpx.Client, inv: dict[str, Any], n: int
) -> tuple[dict[str, Any], list[str]]:
    path = []
    for _ in range(n):
        assert inv["pending_question"] is not None
        a = inv["pending_question"]["action"]
        path.append(f"{a['participant_id']}:{a['probe_id']}@{a['location_id']}")
        inv = answer_pending(core, sim, inv)["state"]
    return inv, path


def test_core_crash_mid_investigation_loses_nothing(
    services: Services, core: httpx.Client, sim: httpx.Client
) -> None:
    """Kill the core (no graceful shutdown) after two answers, restart it, and finish.

    The outcome must equal an uninterrupted run with the same answers, byte for byte.
    """
    straight = create(core, S1)
    straight_final, straight_path = run_to_conclusion(core, sim, straight)

    inv = create(core, S1)
    mid, path = _answer_n(core, sim, inv, 2)
    before = canonical({k: mid[k] for k in KEYS})

    services.crash_core()
    with pytest.raises(httpx.TransportError):
        core.get(f"/v1/investigations/{inv['id']}", timeout=2)
    services.restart_core()

    with services.client(services.core_url) as fresh:
        after = fresh.get(f"/v1/investigations/{inv['id']}").json()
        assert canonical({k: after[k] for k in KEYS}) == before
        final, rest = run_to_conclusion(fresh, sim, after)
        assert path + rest == straight_path
        assert final["status"] == straight_final["status"] == "decided"
        assert canonical(final["belief"]) == canonical(straight_final["belief"])
        assert canonical(final["plan"]) == canonical(straight_final["plan"])
        assert assert_replay_matches(fresh, inv["id"]) == canonical(straight_final["belief"])


def test_answering_after_a_restart_is_still_single_writer(
    services: Services, core: httpx.Client, sim: httpx.Client
) -> None:
    """A question answered before a crash stays answered after it (409, not a second answer)."""
    inv = create(core, S1)
    q = inv["pending_question"]
    first = answer_pending(core, sim, inv)["state"]
    services.restart_core()
    with services.client(services.core_url) as fresh:
        dup = fresh.post(
            f"/v1/investigations/{inv['id']}/answers",
            json={
                "question_id": q["id"],
                "participant_id": q["action"]["participant_id"],
                "outcome": q["outcomes"][0],
            },
        )
        assert dup.status_code == 409
        assert dup.json()["error"]["code"] == "QUESTION_NOT_PENDING"
        now = fresh.get(f"/v1/investigations/{inv['id']}").json()
        assert canonical(now["belief"]) == canonical(first["belief"])
