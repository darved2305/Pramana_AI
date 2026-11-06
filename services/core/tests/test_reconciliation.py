from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion

pytestmark = pytest.mark.db


def _events(core: TestClient, inv_id: str) -> list[dict[str, Any]]:
    response = core.get(f"/v1/investigations/{inv_id}/events", params={"after_seq": 0})
    assert response.status_code == 200, response.text
    return response.json()


def test_different_ap_reconciliation_is_explained_and_tie_break_is_asked(core: TestClient) -> None:
    presets = core.get("/v1/investigations/presets")
    assert presets.status_code == 200, presets.text
    preset = next(item for item in presets.json() if item["id"] == "S2")
    created = core.post("/v1/investigations", json=preset["request"])
    assert created.status_code == 201, created.text
    inv = created.json()
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    final, _ = run_to_conclusion(core, sim, inv, max_steps=24)
    events = _events(core, inv["id"])

    explanations = [event for event in events if event["type"] == "ContradictionExplained"]
    assert explanations
    explanation = explanations[0]["payload"]
    families = {family["code"]: family for family in explanation["families"]}
    assert families["different_access_points"]["posterior_mass"] > 0
    context = explanation["contexts"][0]
    assert dict(zip(context["participant_ids"], context["access_points"], strict=True)) == {
        "p_aarav": "AP_2B",
        "p_neha": "AP_2A",
    }
    assert explanation["tie_break_action"]["participant_id"] == "p_aarav"

    tie_questions = [
        event
        for event in events
        if event["type"] == "QuestionAsked"
        and event["payload"].get("tie_break_for") == explanation["explanation_id"]
    ]
    assert len(tie_questions) == 1
    assert tie_questions[0]["payload"]["action"]["probe_id"] == "wifi_access_point"
    resolved = [event for event in events if event["type"] == "ContradictionResolved"]
    assert resolved
    assert resolved[0]["payload"]["question_id"] == tie_questions[0]["payload"]["question_id"]
    assert final["status"] == "decided"
    assert final["plan"]["decision_class"] == "IT_REPLACE_AP_2A"
