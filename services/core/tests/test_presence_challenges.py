from __future__ import annotations

from typing import Any

import pytest
from core_testkit import PEOPLE, body
from fastapi.testclient import TestClient
from participant_bot import PHRASES, answer_pending, run_to_conclusion

pytestmark = pytest.mark.db

STAFF = [
    *[{**person, "question_budget": 12} for person in PEOPLE],
    {
        "id": "p_ravi",
        "display_name": "Ravi",
        "roles": ["it_tech"],
        "skill": "technician",
        "location_id": "IDF1",
        "languages": {"stt_candidates": ["en-IN"], "template_language": "en"},
        "question_budget": 12,
    },
]


def _events(core: TestClient, inv_id: str) -> list[dict[str, Any]]:
    response = core.get(f"/v1/investigations/{inv_id}/events", params={"after_seq": 0})
    assert response.status_code == 200, response.text
    return response.json()


def _create(core: TestClient) -> dict[str, Any]:
    request = body(fault="CB_C2_7.tripped", people=STAFF)
    request["scenario"]["seed"] = 2007
    created = core.post("/v1/investigations", json=request)
    assert created.status_code == 201, created.text
    return created.json()


def _advance_to_challenge(
    core: TestClient, sim: TestClient, inv: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    for _ in range(24):
        question = inv["pending_question"]
        assert question is not None, "investigation ended before a presence challenge"
        if question["kind"] == "challenge":
            return inv, question
        inv = answer_pending(core, sim, inv)["state"]
    raise AssertionError("no presence challenge was issued")


def test_refused_presence_challenge_fails_neutrally_and_replays(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv, question = _advance_to_challenge(core, sim, _create(core))
    assert question["presence_token_id"] == "idf2_switch_label"
    participant_id = question["action"]["participant_id"]
    assert participant_id in {"p_mahesh", "p_imran"}
    events_before = _events(core, inv["id"])
    assert any(event["type"] == "ChallengeIssued" for event in events_before)
    core.app.state.investigations._cache.pop(inv["id"], None)
    recovered_mid_challenge = core.get(f"/v1/investigations/{inv['id']}").json()
    assert recovered_mid_challenge["pending_question"]["id"] == question["id"]
    assert _events(core, inv["id"]) == events_before
    inv = recovered_mid_challenge

    response = core.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={
            "question_id": question["id"],
            "participant_id": participant_id,
            "text": "I cannot see the label",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["passed"] is False
    expected_message = {
        "p_mahesh": "मी जागेची खात्री करू शकलो नाही; मी दुसऱ्या व्यक्तीला विचारेन.",
        "p_imran": "मैं जगह की पुष्टि नहीं कर पाया; मैं किसी और से पूछूँगा।",
    }[participant_id]
    assert result["message"] == expected_message
    assert "observation" not in result
    assert "extraction" not in result

    events = _events(core, inv["id"])
    challenge_result = next(event for event in events if event["type"] == "ChallengeResult")
    assert challenge_result["payload"]["result"] == "failed"
    serialized = str(events)
    assert "I cannot see the label" not in serialized

    service = core.app.state.investigations
    service._cache.pop(inv["id"], None)
    rebuilt = core.get(f"/v1/investigations/{inv['id']}").json()
    assert rebuilt == result["state"]
    assert _events(core, inv["id"]) == events

    final, _ = run_to_conclusion(core, sim, rebuilt, max_steps=24)
    assert final["status"] == "decided"
    assert final["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("en", "I couldn't confirm the location; I'll ask someone else."),
        ("hi", "मैं जगह की पुष्टि नहीं कर पाया; मैं किसी और से पूछूँगा।"),
        ("mr", "मी जागेची खात्री करू शकलो नाही; मी दुसऱ्या व्यक्तीला विचारेन."),
        ("hi-en", "Location confirm nahi ho saki; main kisi aur se poochunga."),
    ],
)
def test_presence_failure_copy_is_neutral_in_every_language(
    core: TestClient, language: str, message: str
) -> None:
    people = [
        {
            **person,
            "languages": {**person["languages"], "template_language": language},
        }
        for person in STAFF
    ]
    request = body(fault="CB_C2_7.tripped", people=people)
    request["scenario"]["seed"] = 2007
    created = core.post("/v1/investigations", json=request)
    assert created.status_code == 201, created.text
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv, question = _advance_to_challenge(core, sim, created.json())
    response = core.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={
            "question_id": question["id"],
            "participant_id": question["action"]["participant_id"],
            "text": "I cannot see the label",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["passed"] is False
    assert response.json()["message"] == message


def test_honest_presence_challenge_passes_and_reweights_location_evidence(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    created = _create(core)
    final, _ = run_to_conclusion(core, sim, created, max_steps=24)
    results = [
        event for event in _events(core, created["id"]) if event["type"] == "ChallengeResult"
    ]
    assert results
    assert all(event["payload"]["result"] == "passed" for event in results)
    assert final["status"] == "decided"
    assert final["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"


def test_conclusive_schedule_withdraws_pending_presence_challenge(
    core: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pramana_contracts import PlanDecision, PlanKind
    from pramana_core import investigations as investigations_module
    from pramana_engine.scheduler import Schedule

    presets = core.get("/v1/investigations/presets")
    preset = next(item for item in presets.json() if item["id"] == "S7")
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv, challenge = _advance_to_challenge(
        core, sim, core.post("/v1/investigations", json=preset["request"]).json()
    )
    decision = PlanDecision(
        kind=PlanKind.DECIDE,
        decision_class="DISPATCH_ELECTRICIAN_DB_C2",
        decision_probability=0.99,
        reason="the remaining observations support a confident decision",
        rule="confident",
        candidates=[],
        infeasible=[],
    )
    monkeypatch.setattr(
        investigations_module,
        "schedule",
        lambda engine, pending, max_parallel: Schedule(plan=decision),
    )
    service = core.app.state.investigations  # type: ignore[attr-defined]

    async def conclude_with_pending_challenge() -> None:
        async with service._lock(inv["id"]), service.db.transaction() as session:
            row = await service._load_row(session, inv["id"], lock=True)
            engine = await service._engine(session, row)
            await service._schedule(session, row, engine)
            row.version += 1

    core.portal.call(conclude_with_pending_challenge)  # type: ignore[union-attr]
    service._cache.pop(inv["id"], None)
    final = core.get(f"/v1/investigations/{inv['id']}").json()
    assert final["status"] == "decided"
    assert final["pending_questions"] == []

    challenge_results = [
        event for event in _events(core, inv["id"]) if event["type"] == "ChallengeResult"
    ]
    assert any(
        event["payload"]["challenge_id"] == challenge["id"]
        and event["payload"]["result"] == "withdrawn"
        for event in challenge_results
    )
    assert core.get(f"/v1/investigations/{inv['id']}/replay").json()["identical"]


def test_s7_guard_false_presence_is_rejected_and_planner_asks_someone_else(
    core: TestClient,
) -> None:
    presets = core.get("/v1/investigations/presets")
    assert presets.status_code == 200, presets.text
    preset = next(item for item in presets.json() if item["id"] == "S7")
    created = core.post("/v1/investigations", json=preset["request"])
    assert created.status_code == 201, created.text
    inv = created.json()
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]

    challenged_guard = False
    path: list[str] = []
    for _ in range(16):
        question = inv["pending_question"]
        assert question is not None, (
            f"S7 ended before the guard's IDF-2 question: {path}; plan={inv['plan']}"
        )
        action = question["action"]
        path.append(
            f"{question['kind']}:{action['participant_id']}:{action['probe_id']}@{action['location_id']}"
        )
        if question["kind"] == "challenge":
            if action["participant_id"] != preset["adversarial_participant_id"]:
                # The other guard makes a real move and answers the label challenge.
                inv = answer_pending(core, sim, inv)["state"]
                continue
            assert action["location_id"] == "IDF2"
            token = core.post(
                f"/v1/investigations/{inv['id']}/participants/{action['participant_id']}/token"
            ).json()
            headers = {"Authorization": f"Bearer {token['token']}"}
            off_site = sim.get(f"/sim/v1/scenarios/{token['scenario_id']}/view", headers=headers)
            assert off_site.status_code == 200
            assert off_site.json()["location_id"] == "GUARD_DESK"
            assert off_site.json()["presence_tokens"] == [], (
                f"guard was already at the challenged site after {path}: {off_site.json()}"
            )
            answered = core.post(
                f"/v1/investigations/{inv['id']}/answers",
                json={
                    "question_id": question["id"],
                    "participant_id": action["participant_id"],
                    "text": "K 7 Q",
                },
            )
            assert answered.status_code == 200, answered.text
            result = answered.json()
            assert result["passed"] is False
            moved_after_answer = sim.post(
                f"/sim/v1/scenarios/{token['scenario_id']}/move",
                json={"to": "IDF2"},
                headers=headers,
            )
            assert moved_after_answer.status_code == 200
            retry = core.post(
                f"/v1/investigations/{inv['id']}/answers",
                json={
                    "question_id": question["id"],
                    "participant_id": action["participant_id"],
                    "text": "ABC",
                },
            )
            assert retry.status_code == 409
            next_question = result["state"]["pending_question"]
            assert next_question is not None
            assert next_question["action"]["participant_id"] != action["participant_id"]
            inv = result["state"]
            challenged_guard = True
            break
        if (
            action["participant_id"] == preset["adversarial_participant_id"]
            and action["location_id"] == "IDF2"
        ):
            claimed_answer = {
                "switch_leds": PHRASES["green"],
                "nvr_screen": PHRASES["on"],
                "closet_light": PHRASES["on"],
            }[action["probe_id"]]
            answer = core.post(
                f"/v1/investigations/{inv['id']}/answers",
                json={
                    "question_id": question["id"],
                    "participant_id": action["participant_id"],
                    "text": claimed_answer,
                },
            )
            assert answer.status_code == 200, answer.text
            inv = answer.json()["state"]
            continue
        inv = answer_pending(core, sim, inv)["state"]
    else:
        raise AssertionError("S7 did not issue an IDF-2 presence challenge")
    assert challenged_guard

    final, final_path = run_to_conclusion(core, sim, inv, max_steps=20)
    observed = [
        (o["participant_id"], o["probe_id"], o["outcome"], o["state"])
        for o in final["observations"]
    ]
    challenge_results = [
        (event["payload"]["participant_id"], event["payload"]["result"])
        for event in _events(core, created.json()["id"])
        if event["type"] == "ChallengeResult"
    ]
    assert ("p_suresh", "passed") in challenge_results
    assert final["status"] == "decided", f"{final_path}; {observed}; {final['plan']}"
    assert final["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"
    event_text = str(_events(core, created.json()["id"]))
    assert "K 7 Q" not in event_text
    assert "K7Q" not in event_text
    events = _events(core, created.json()["id"])
    service = core.app.state.investigations
    service._cache.pop(created.json()["id"], None)
    replayed = core.get(f"/v1/investigations/{created.json()['id']}").json()
    assert replayed == final
    assert _events(core, created.json()["id"]) == events
