"""Engine outputs surfaced by the core: contradictions, two-fault conclusions, sealed reveal."""

from __future__ import annotations

from typing import Any

import pytest
from core_testkit import PEOPLE, body
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion

pytestmark = pytest.mark.db

STAFF = [
    *PEOPLE,
    {
        "id": "p_ravi",
        "display_name": "Ravi",
        "roles": ["it_tech"],
        "skill": "technician",
        "location_id": "IDF1",
        "languages": {"stt_candidates": ["en-IN"], "template_language": "en"},
    },
]


def _events(core: TestClient, inv_id: str) -> list[dict[str, Any]]:
    r = core.get(f"/v1/investigations/{inv_id}/events", params={"after_seq": 0})
    assert r.status_code == 200, r.text
    out: list[dict[str, Any]] = r.json()
    return out


def test_intake_hints_are_logged_but_are_not_evidence(core: TestClient) -> None:
    report = "Floor 3 pe WiFi nahi chal raha, room 304 mein lights bhi band hain"
    inv = core.post("/v1/investigations", json=body(fault="CB_C2_7.tripped", report=report))
    assert inv.status_code == 201, inv.text
    data = inv.json()
    parsed = [e for e in _events(core, data["id"]) if e["type"] == "IntakeParsed"]
    assert parsed[0]["payload"] == {
        "floors": [3],
        "locations": ["F3_R304"],
        "symptoms": ["wifi", "power"],
    }
    # Only the intake probe at the reporter's location is evidence; the lights are a hint.
    assert [(o["probe_id"], o["outcome"]) for o in data["observations"]] == [
        ("internet_works", "no")
    ]


def test_a_report_about_the_lights_alone_is_not_internet_evidence(core: TestClient) -> None:
    inv = core.post(
        "/v1/investigations", json=body(report="corridor ki bijli chali gayi floor 3 pe")
    ).json()
    assert inv["observations"] == []


def test_explainable_answers_log_no_contradiction(core: TestClient) -> None:
    inv = core.post("/v1/investigations", json=body(fault="CB_C2_7.tripped")).json()
    final, _ = run_to_conclusion(core, TestClient(core.sim_app), inv)  # type: ignore[attr-defined]
    assert final["status"] == "decided"
    assert not any(e["type"] == "ContradictionDetected" for e in _events(core, inv["id"]))


def test_contradiction_event_names_the_clashing_answers(core: TestClient) -> None:
    """Intake says websites open; then the phone shows no Wi-Fi network at all."""
    report = "Floor 3 pe sab websites khul rahi hain, internet chal raha hai"
    req = body(fault="AP_3A.dead", report=report, people=[PEOPLE[0]])
    inv = core.post("/v1/investigations", json=req).json()
    assert [(o["probe_id"], o["outcome"]) for o in inv["observations"]] == [
        ("internet_works", "yes")
    ]
    # Phone checks that cannot be true when websites open on the same phone in the same room.
    impossible = {"wifi_status": "no_network", "web_by_ip": "no"}
    for _ in range(6):
        q = inv["pending_question"]
        assert q is not None, "Riya was never asked a phone check"
        a = q["action"]
        clash = impossible.get(a["probe_id"]) if a["location_id"] == "F3_R304" else None
        r = core.post(
            f"/v1/investigations/{inv['id']}/answers",
            json={
                "question_id": q["id"],
                "participant_id": "p_riya",
                "outcome": clash or q["outcomes"][0],
            },
        )
        assert r.status_code == 200, r.text
        inv = r.json()["state"]
        if clash:
            break
    else:
        raise AssertionError("no phone check was asked")
    clashes = [e for e in _events(core, inv["id"]) if e["type"] == "ContradictionDetected"]
    assert clashes, "an impossible combination must be logged"
    assert "p_riya:internet_works@F3_R304=yes" in clashes[-1]["payload"]["conflicts_with"]


def test_two_fault_world_is_concluded_and_scored_against_the_seal(core: TestClient) -> None:
    req = body(people=STAFF)
    req["scenario"]["fault"] = {
        "faults": [
            {"component_id": "CB_C2_7", "mode": "tripped"},
            {"component_id": "ISP_LINK", "mode": "down"},
        ]
    }
    created = core.post("/v1/investigations", json=req)
    assert created.status_code == 201, created.text
    inv = created.json()
    commitment = inv["sealed_commitment"]
    events = _events(core, inv["id"])
    first_question = next(e["seq"] for e in events if e["type"] == "QuestionAsked")
    sealed = next(e for e in events if e["type"] == "InvestigationCreated")
    assert sealed["seq"] < first_question
    assert sealed["payload"]["commitment"] == commitment

    final, _ = run_to_conclusion(core, TestClient(core.sim_app), inv)  # type: ignore[attr-defined]
    assert final["status"] == "decided"
    assert final["belief"]["map_decision"] == "MULTIPLE_FAULTS"
    revealed = core.post(f"/v1/investigations/{inv['id']}/reveal").json()
    gt = revealed["ground_truth"]
    assert "MULTIPLE_FAULTS" in gt["true_decision_classes"]
    assert gt["correct"] is True
    assert gt["reveal"]["commitment_verified"] is True
    assert len(commitment) == 64
