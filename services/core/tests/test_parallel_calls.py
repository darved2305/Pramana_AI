"""Parallel questions in one investigation (docs/adr/0011): several people asked at once, a
question withdrawn when another answer makes it pointless, one writer, replay unchanged."""

from __future__ import annotations

from typing import Any

import pytest
from core_testkit import body
from fastapi.testclient import TestClient
from participant_bot import answer_pending

from pramana_contracts import InvestigationState
from pramana_core.visibility import for_participant

pytestmark = pytest.mark.db


def create(core: TestClient, parallel: int, fault: str = "CB_C2_7.tripped") -> dict[str, Any]:
    r = core.post("/v1/investigations", json={**body(fault=fault), "max_parallel_calls": parallel})
    assert r.status_code == 201, r.text
    return dict(r.json())


def answer(core: TestClient, sim: TestClient, inv_id: str, q: dict[str, Any]) -> dict[str, Any]:
    result = answer_pending(core, sim, {"id": inv_id, "pending_question": q})
    return dict(result["state"])


def run(core: TestClient, inv: dict[str, Any], pick: int = 0) -> tuple[dict[str, Any], int]:
    """Answer the questions in flight (``pick``: which one answers first) until a conclusion.
    Returns the final state and the most questions that were in flight at once."""
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    most = 0
    for _ in range(20):
        waiting = inv["pending_questions"]
        if not waiting:
            return inv, most
        most = max(most, len(waiting))
        inv = answer(core, sim, inv["id"], waiting[min(pick, len(waiting) - 1)])
    raise AssertionError("no conclusion")


def events(core: TestClient, inv_id: str) -> list[dict[str, Any]]:
    return list(core.get(f"/v1/investigations/{inv_id}/events").json())


def test_sequential_by_default(core: TestClient) -> None:
    r = core.post("/v1/investigations", json=body(fault="CB_C2_7.tripped"))
    inv = r.json()
    assert inv["max_parallel_calls"] == 1
    assert len(inv["pending_questions"]) == 1
    assert inv["pending_questions"][0] == inv["pending_question"]


@pytest.mark.parametrize("bad", [0, 4])
def test_parallel_is_capped_at_three(core: TestClient, bad: int) -> None:
    r = core.post("/v1/investigations", json={**body(), "max_parallel_calls": bad})
    assert r.status_code == 422


def test_several_people_are_asked_at_once(core: TestClient) -> None:
    inv = create(core, 3)
    waiting = inv["pending_questions"]
    assert 2 <= len(waiting) <= 3
    people = [q["action"]["participant_id"] for q in waiting]
    assert len(set(people)) == len(people)
    assert inv["pending_question"] == waiting[0]
    asked = [e for e in events(core, inv["id"]) if e["type"] == "QuestionAsked"]
    assert len(asked) == len(waiting)
    assert "parallel" not in asked[0]["payload"]
    for e in asked[1:]:
        extra = e["payload"]["parallel"]
        assert extra["conditional_decision_bits"] > 0
        assert extra["net_value_min"] > 0


@pytest.mark.parametrize("pick", [0, -1])
def test_a_parallel_run_reaches_the_right_decision(core: TestClient, pick: int) -> None:
    inv = create(core, 3)
    final, most = run(core, inv, pick=pick if pick >= 0 else 9)
    assert most >= 2
    assert final["status"] == "decided", final["plan"]["reason"]
    assert final["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"
    assert final["pending_question"] is None
    assert final["pending_questions"] == []
    log = events(core, inv["id"])
    asked = {e["payload"]["question_id"] for e in log if e["type"] == "QuestionAsked"}
    withdrawn = [e for e in log if e["type"] == "QuestionWithdrawn"]
    answered = len([e for e in log if e["type"] == "ObservationRecorded"]) - 1  # minus intake
    answered_challenges = len(
        [
            e
            for e in log
            if e["type"] == "ChallengeResult" and e["payload"]["result"] in {"passed", "failed"}
        ]
    )
    assert answered + answered_challenges + len(withdrawn) == len(asked), (
        answered,
        answered_challenges,
        len(withdrawn),
        len(asked),
    )
    assert all(e["payload"]["question_id"] in asked for e in withdrawn)
    replay = core.get(f"/v1/investigations/{inv['id']}/replay").json()
    assert replay["identical"], replay


def test_a_withdrawn_question_cannot_be_answered(core: TestClient) -> None:
    inv = create(core, 3)
    run(core, inv)
    withdrawn = [e for e in events(core, inv["id"]) if e["type"] == "QuestionWithdrawn"]
    if not withdrawn:
        pytest.skip("this run ended with nothing in flight")
    qid = withdrawn[0]["payload"]["question_id"]
    pid = withdrawn[0]["payload"]["participant_id"]
    assert withdrawn[0]["payload"]["reason"]
    reopened = core.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={"question_id": qid, "participant_id": pid, "text": "haan"},
    )
    assert reopened.status_code == 409


def test_a_question_made_pointless_mid_run_is_withdrawn(
    core: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When an answer makes another question in flight pointless (``Engine.moot``), that one is
    withdrawn while the investigation goes on, and it can no longer be answered."""
    from pramana_engine import Engine

    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv = create(core, 3)
    oldest, second, *_ = inv["pending_questions"]
    target = (oldest["action"]["participant_id"], oldest["action"]["probe_id"])
    monkeypatch.setattr(
        Engine,
        "moot",
        lambda self, pending: [(a.participant_id, a.probe_id) == target for a in pending],
    )
    after = answer(core, sim, inv["id"], second)
    assert after["status"] == "investigating"
    assert oldest["id"] not in {q["id"] for q in after["pending_questions"]}
    gone = [e["payload"] for e in events(core, inv["id"]) if e["type"] == "QuestionWithdrawn"]
    assert [g["question_id"] for g in gone] == [oldest["id"]]
    assert gone[0]["reason"] == "another answer made this question pointless"
    r = core.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={"question_id": oldest["id"], "participant_id": target[0], "text": "haan"},
    )
    assert r.status_code == 409
    assert "withdrawn" in r.json()["error"]["message"]
    # The engine is unchanged by a withdrawal, so replay still agrees.
    assert core.get(f"/v1/investigations/{inv['id']}/replay").json()["identical"]


def test_each_participant_sees_only_their_own_question(core: TestClient) -> None:
    inv = create(core, 3)
    state = InvestigationState.model_validate(inv)
    for q in state.pending_questions:
        pid = q.action.participant_id
        seen = for_participant(state, pid)
        assert seen.pending_question == q
        assert seen.pending_questions == [q]
    asked = {q.action.participant_id for q in state.pending_questions}
    for p in state.participants:
        if p.id not in asked:
            seen = for_participant(state, p.id)
            assert seen.pending_question is None
            assert seen.pending_questions == []


def test_declining_a_call_keeps_the_other_questions(core: TestClient) -> None:
    inv = create(core, 3)
    first, *rest = inv["pending_questions"]
    svc = core.app.state.investigations  # type: ignore[attr-defined]
    pid = first["action"]["participant_id"]
    after = core.portal.call(  # type: ignore[union-attr]
        svc.record_consent, inv["id"], pid, False, "consent: no"
    ).model_dump(mode="json")
    log = events(core, inv["id"])
    assert any(
        e["type"] == "QuestionCancelled" and e["payload"]["question_id"] == first["id"] for e in log
    )
    left = {q["id"] for q in after["pending_questions"]}
    gone = {e["payload"]["question_id"] for e in log if e["type"] == "QuestionWithdrawn"}
    assert {q["id"] for q in rest} <= left | gone  # the others are kept unless now pointless
    assert all(q["action"]["participant_id"] != pid for q in after["pending_questions"])
