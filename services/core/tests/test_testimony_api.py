"""Scenario tests through the API: S7 (a false claim of being in a closet, caught by a presence
check) and S2 (two students disagree; the engine explains how both can be right)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from core_testkit import PEOPLE, body
from fastapi.testclient import TestClient
from participant_bot import PHRASES

from pramana_contracts import InvestigationState
from pramana_core.visibility import for_participant

pytestmark = pytest.mark.db

LIE = {
    "off": "green",
    "green": "off",
    "amber": "green",
    "on": "off",
    "tripped": "up",
    "up": "tripped",
}


def _sim(core: TestClient) -> TestClient:
    return TestClient(core.sim_app)  # type: ignore[attr-defined]


def _token(core: TestClient, inv_id: str, pid: str) -> tuple[str, dict[str, str]]:
    tok = core.post(f"/v1/investigations/{inv_id}/participants/{pid}/token").json()
    return tok["scenario_id"], {"Authorization": f"Bearer {tok['token']}"}


def _post(core: TestClient, inv_id: str, q: dict[str, Any], text: str) -> dict[str, Any]:
    r = core.post(
        f"/v1/investigations/{inv_id}/answers",
        json={
            "question_id": q["id"],
            "participant_id": q["action"]["participant_id"],
            "text": text,
        },
    )
    assert r.status_code == 200, r.text
    return dict(r.json()["state"])


def _answer(
    core: TestClient, inv_id: str, q: dict[str, Any], liar: str | None, seen_labels: list[str]
) -> dict[str, Any]:
    """Truthful people go where asked and report what their card shows. ``liar`` claims to have
    gone, does not move, and reports the opposite of what is there."""
    sim = _sim(core)
    a = q["action"]
    pid = a["participant_id"]
    sid, h = _token(core, inv_id, pid)
    if q["kind"] == "challenge":
        if pid == liar:
            return _post(core, inv_id, q, "I can't see any label from here, sorry")
        view = sim.get(f"/sim/v1/scenarios/{sid}/view", headers=h).json()
        (label,) = view["labels"]
        seen_labels.append(label["value"])
        spaced = " ".join(label["value"])  # read out one character at a time
        return _post(core, inv_id, q, f"it says {spaced}")
    home = next((p["location_id"] for p in PEOPLE if p["id"] == pid), a["location_id"])
    if pid == liar and a["location_id"] != home:
        # Pretend: never leave, peek at what is really there, say the opposite. A consistent
        # liar keeps pretending wherever they have claimed to be.
        sim.post(f"/sim/v1/scenarios/{sid}/move", json={"to": a["location_id"]}, headers=h)
        truth = sim.post(
            f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": a["probe_id"]}, headers=h
        ).json()["value"]
        sim.post(f"/sim/v1/scenarios/{sid}/move", json={"to": home}, headers=h)
        return _post(core, inv_id, q, PHRASES[LIE.get(truth, truth)])
    if a["requires_move"]:
        sim.post(f"/sim/v1/scenarios/{sid}/move", json={"to": a["location_id"]}, headers=h)
    seen = sim.post(f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": a["probe_id"]}, headers=h)
    return _post(core, inv_id, q, PHRASES[seen.json()["value"]])


def _run(
    core: TestClient, fault: str, liar: str | None = None, checks: bool = True, people: Any = None
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    r = core.post(
        "/v1/investigations",
        json={**body(fault=fault, people=people), "presence_checks": checks},
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    asked: list[dict[str, Any]] = []
    labels: list[str] = []
    for _ in range(25):
        if not inv["pending_questions"]:
            return inv, asked, labels
        q = inv["pending_questions"][0]
        asked.append(q)
        inv = _answer(core, inv["id"], q, liar, labels)
    raise AssertionError("no conclusion")


def _events(core: TestClient, inv_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = core.get(
        f"/v1/investigations/{inv_id}/events?after=0&limit=500"
    ).json()
    return out


# -- S7 ------------------------------------------------------------------------------------------


GUARD_ONLY = [p for p in PEOPLE if p["id"] != "p_imran"]
S2_PEOPLE = [
    {
        **PEOPLE[0],
        "id": "p_neha",
        "display_name": "Neha",
        "location_id": "F2_R210",
        "languages": {"stt_candidates": ["en-IN"], "template_language": "en"},
    },
    {
        **PEOPLE[0],
        "id": "p_aarav",
        "display_name": "Aarav",
        "location_id": "F2_R205",
        "languages": {"stt_candidates": ["en-IN"], "template_language": "en"},
    },
]


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _replay_identical(core: TestClient, inv_id: str) -> bool:
    return bool(core.get(f"/v1/investigations/{inv_id}/replay").json()["identical"])


def _label_value(core: TestClient, inv_id: str, pid: str, at: str) -> str:
    sid, h = _token(core, inv_id, pid)
    _sim(core).post(f"/sim/v1/scenarios/{sid}/move", json={"to": at}, headers=h)
    (label,) = _sim(core).get(f"/sim/v1/scenarios/{sid}/view", headers=h).json()["labels"]
    return str(label["value"])


def test_s1_electrician_reading_is_checked_and_passes(core: TestClient) -> None:
    inv, asked, labels = _run(core, "CB_C2_7.tripped")
    assert inv["status"] == "decided"
    assert inv["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"
    (check,) = inv["presence_checks"]
    assert (check["participant_id"], check["location_id"], check["status"]) == (
        "p_imran",
        "DB_C2_PANEL",
        "passed",
    )
    challenge = next(q for q in asked if q["kind"] == "challenge")
    assert challenge["outcomes"] == []
    assert "पैनल" in challenge["text"]  # Imran is asked in Hindi
    assert len(labels) == 1
    assert _replay_identical(core, inv["id"])
    full = InvestigationState.model_validate(inv)
    assert for_participant(full, "p_riya").presence_checks == []
    assert len(for_participant(full, "p_imran").presence_checks) == 1


def test_lying_electrician_fails_the_check_and_is_not_believed(core: TestClient) -> None:
    """Imran says the breaker is up without going to the panel. The check fails, his claim
    keeps counting for little, others are asked, and the decision is still right."""
    inv, asked, _ = _run(core, "CB_C2_7.tripped", liar="p_imran")
    imran = [c for c in inv["presence_checks"] if c["participant_id"] == "p_imran"]
    assert [c["status"] for c in imran] == ["failed"], (
        imran,
        [(q["action"], q["kind"]) for q in asked],
    )
    assert inv["status"] == "decided"
    assert inv["plan"]["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"
    assert len(asked) > 5  # more people asked than in the honest run
    assert _replay_identical(core, inv["id"])
    value = _label_value(core, inv["id"], "p_imran", "DB_C2_PANEL")
    # The core never learned it: no string anywhere in the log holds it as a token. (A bare
    # substring test is wrong: a value like "979" can occur inside a timestamp.)
    leaves = _strings([e["payload"] for e in _events(core, inv["id"])])
    assert not any(re.search(rf"(?<![A-Z0-9]){value}(?![A-Z0-9])", s.upper()) for s in leaves)


def test_s7_guard_claiming_the_closet_is_caught(core: TestClient) -> None:
    """S7: the guard reports the closet without going there. Nobody is accused, and the
    engine abstains rather than decide on his word."""
    inv, _asked, _ = _run(core, "SW_C2.dead", liar="p_mahesh", people=GUARD_ONLY)
    assert [c["status"] for c in inv["presence_checks"]] == ["failed"]
    assert inv["status"] == "abstained" or inv["plan"]["decision_class"] == "IT_ONSITE_SW_C2"
    types = [e["type"] for e in _events(core, inv["id"])]
    assert types.index("ChallengeIssued") < types.index("ChallengeResult")
    assert _replay_identical(core, inv["id"])


def test_s7_honest_guard_passes(core: TestClient) -> None:
    inv, _, labels = _run(core, "SW_C2.dead", people=GUARD_ONLY)
    assert [c["status"] for c in inv["presence_checks"]] == ["passed"]
    assert len(labels) == 1
    assert _replay_identical(core, inv["id"])


def test_without_presence_checks_nobody_is_challenged(core: TestClient) -> None:
    inv, asked, _ = _run(core, "CB_C2_7.tripped", liar="p_imran", checks=False)
    assert inv["presence_checks"] == []
    assert inv["presence_checks_enabled"] is False
    assert all(q["kind"] != "challenge" for q in asked)


def test_a_check_must_be_answered_with_a_reading(core: TestClient) -> None:
    r = core.post(
        "/v1/investigations", json={**body(fault="CB_C2_7.tripped"), "presence_checks": True}
    )
    inv = r.json()
    for _ in range(10):
        q = inv["pending_questions"][0]
        if q["kind"] == "challenge":
            break
        inv = _answer(core, inv["id"], q, None, [])
    else:
        raise AssertionError("no check was asked")
    bad = core.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={"question_id": q["id"], "participant_id": "p_imran", "outcome": "up"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "READING_REQUIRED"
    still = core.get(f"/v1/investigations/{inv['id']}").json()
    assert still["pending_questions"][0]["id"] == q["id"]  # nothing was consumed


# -- S2 ------------------------------------------------------------------------------------------


def test_s2_two_students_disagree_and_both_are_right(core: TestClient) -> None:
    b = body(fault="AP_2A.dead", people=S2_PEOPLE, report="Wi-Fi is not working in room 210")
    b["report"]["reporter_id"] = "p_neha"
    inv = core.post("/v1/investigations", json=b).json()
    for _ in range(20):
        if not inv["pending_questions"]:
            break
        inv = _answer(core, inv["id"], inv["pending_questions"][0], None, [])
    assert inv["plan"]["decision_class"] == "IT_REPLACE_AP_2A"
    assert inv["disagreements"]
    for d in inv["disagreements"]:
        assert d["reconciling_hypothesis"] == "AP_2A.dead"
        assert [x["component_id"] for x in d["only_one_depends"]] == ["AP_2A"]
        assert "room 205 is also covered by Access point 2B" in d["explanation"]
        assert "—" not in d["explanation"]
        assert "—" not in d["explanation"]
    assert inv["disagreements"][-1]["kind"] == "both_right"
    assert _replay_identical(core, inv["id"])
    for person in S2_PEOPLE:
        personal = for_participant(InvestigationState.model_validate(inv), person["id"])
        assert (
            personal.disagreements == []
        )  # other people's evidence and inferred cause are staff-only
