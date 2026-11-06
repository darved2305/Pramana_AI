"""P2 acceptance scenarios against separate simulator and core processes."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from e2e.harness import Services
from e2e.replay import all_events, canonical, last_logged_belief, replayed_belief
from participant_bot import PHRASES, answer_pending, run_to_conclusion

pytestmark = pytest.mark.e2e


def assert_replay_matches(core: httpx.Client, inv_id: str) -> None:
    events = all_events(core, inv_id)
    rebuilt = replayed_belief(events)
    assert rebuilt == last_logged_belief(events)
    state = core.get(f"/v1/investigations/{inv_id}").json()
    assert rebuilt == canonical(state["belief"])


def create_preset(core: httpx.Client, preset_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    response = core.get("/v1/investigations/presets")
    assert response.status_code == 200, response.text
    preset = next(item for item in response.json() if item["id"] == preset_id)
    created = core.post("/v1/investigations", json=preset["request"])
    assert created.status_code == 201, created.text
    return preset, created.json()


def test_s2_reconciliation_explains_context_and_asks_tie_break(
    core: httpx.Client, sim: httpx.Client
) -> None:
    _, inv = create_preset(core, "S2")
    final, _ = run_to_conclusion(core, sim, inv, max_steps=24)
    events = all_events(core, inv["id"])

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

    tie_questions = [
        event
        for event in events
        if event["type"] == "QuestionAsked"
        and event["payload"].get("tie_break_for") == explanation["explanation_id"]
    ]
    assert len(tie_questions) == 1
    assert tie_questions[0]["payload"]["action"]["probe_id"] == "wifi_access_point"
    assert any(
        event["type"] == "ContradictionResolved"
        and event["payload"]["question_id"] == tie_questions[0]["payload"]["question_id"]
        for event in events
    )
    assert final["status"] == "decided"
    assert final["plan"]["decision_class"] == "IT_REPLACE_AP_2A"
    assert_replay_matches(core, inv["id"])


def test_s7_false_presence_fails_then_another_person_resolves_after_crash(
    services: Services, core: httpx.Client, sim: httpx.Client
) -> None:
    preset, inv = create_preset(core, "S7")
    adversary = preset["adversarial_participant_id"]
    path: list[str] = []
    failure: dict[str, Any] | None = None

    for _ in range(32):
        question = inv["pending_question"]
        assert question is not None, f"S7 ended before challenge failure: {path}; {inv['plan']}"
        action = question["action"]
        path.append(
            f"{question['kind']}:{action['participant_id']}:{action['probe_id']}@{action['location_id']}"
        )

        if question["kind"] == "challenge":
            if action["participant_id"] != adversary:
                inv = answer_pending(core, sim, inv)["state"]
                continue

            before = all_events(core, inv["id"])
            services.crash_core()
            services.restart_core()
            inv = core.get(f"/v1/investigations/{inv['id']}").json()
            assert inv["pending_question"]["id"] == question["id"]
            assert all_events(core, inv["id"]) == before

            token_response = core.post(
                f"/v1/investigations/{inv['id']}/participants/{adversary}/token"
            )
            assert token_response.status_code == 200, token_response.text
            token = token_response.json()
            headers = {"Authorization": f"Bearer {token['token']}"}
            view = sim.get(f"/sim/v1/scenarios/{token['scenario_id']}/view", headers=headers)
            assert view.status_code == 200, view.text
            assert view.json()["location_id"] == "GUARD_DESK"
            assert view.json()["presence_tokens"] == []

            response = core.post(
                f"/v1/investigations/{inv['id']}/answers",
                json={
                    "question_id": question["id"],
                    "participant_id": adversary,
                    "text": "K 7 Q",
                },
            )
            assert response.status_code == 200, response.text
            failure = response.json()
            assert failure["passed"] is False
            moved = sim.post(
                f"/sim/v1/scenarios/{token['scenario_id']}/move",
                json={"to": "IDF2"},
                headers=headers,
            )
            assert moved.status_code == 200, moved.text
            retry = core.post(
                f"/v1/investigations/{inv['id']}/answers",
                json={
                    "question_id": question["id"],
                    "participant_id": adversary,
                    "text": "ABC",
                },
            )
            assert retry.status_code == 409
            inv = failure["state"]
            assert inv["pending_question"]["action"]["participant_id"] != adversary
            break

        if action["participant_id"] == adversary and action["location_id"] == "IDF2":
            false_answers = {
                "switch_leds": PHRASES["green"],
                "nvr_screen": PHRASES["on"],
                "closet_light": PHRASES["on"],
            }
            response = core.post(
                f"/v1/investigations/{inv['id']}/answers",
                json={
                    "question_id": question["id"],
                    "participant_id": adversary,
                    "text": false_answers[action["probe_id"]],
                },
            )
            assert response.status_code == 200, response.text
            inv = response.json()["state"]
            continue

        inv = answer_pending(core, sim, inv)["state"]
    else:
        raise AssertionError(f"S7 did not reject a false presence claim: {path}")

    assert failure is not None
    final, _ = run_to_conclusion(core, sim, inv, max_steps=24)
    assert final["status"] == "decided"
    assert final["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"
    events = all_events(core, inv["id"])
    results = [event["payload"] for event in events if event["type"] == "ChallengeResult"]
    assert any(r["participant_id"] == adversary and r["result"] == "failed" for r in results)
    assert any(r["participant_id"] != adversary and r["result"] == "passed" for r in results)
    serialized = str(events)
    assert "K 7 Q" not in serialized
    assert "K7Q" not in serialized
    assert_replay_matches(core, inv["id"])
