"""The participant directory and the investigation list."""

from __future__ import annotations

from typing import Any

import pytest
from auth_testkit import AUTO, CSRF, login, secure_core
from core_testkit import PEOPLE, body
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion

pytestmark = pytest.mark.db
__all__ = ["secure_core"]

RIYA: dict[str, Any] = PEOPLE[0]


def test_directory_crud(core: TestClient) -> None:
    assert core.get("/v1/participants").json() == []
    r = core.post("/v1/participants", json=RIYA)
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["pack_id"] == "campus_block_c"
    assert entry["participant"]["id"] == "p_riya"
    dup = core.post("/v1/participants", json=RIYA)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "PARTICIPANT_EXISTS"
    for p in PEOPLE[1:]:
        assert core.post("/v1/participants", json=p).status_code == 201
    ids = [e["participant"]["id"] for e in core.get("/v1/participants").json()]
    assert ids == ["p_imran", "p_mahesh", "p_riya"]

    r = core.patch("/v1/participants/p_riya", json={"display_name": "Riya S", "available": False})
    assert r.status_code == 200, r.text
    got = core.get("/v1/participants/p_riya").json()
    assert got["participant"]["display_name"] == "Riya S"
    assert got["participant"]["available"] is False
    assert got["participant"]["languages"] == RIYA["languages"]  # untouched fields are kept
    assert got["updated_at"] >= entry["updated_at"]

    assert core.delete("/v1/participants/p_riya").status_code == 204
    assert core.get("/v1/participants/p_riya").status_code == 404
    assert core.delete("/v1/participants/p_riya").status_code == 404


def test_directory_validation(core: TestClient) -> None:
    r = core.post("/v1/participants", json={**RIYA, "location_id": "MOON_BASE"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_LOCATION"
    assert core.post("/v1/participants", json={**RIYA, "roles": []}).status_code == 422
    # Unknown fields are rejected, as everywhere.
    assert core.post("/v1/participants", json={**RIYA, "nickname": "x"}).status_code == 422
    r = core.post("/v1/participants", params={"pack_id": "no_such_pack"}, json=RIYA)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_PACK"
    assert core.post("/v1/participants", params={"pack_id": "../etc"}, json=RIYA).status_code == 422
    assert core.post("/v1/participants", json=RIYA).status_code == 201
    r = core.patch("/v1/participants/p_riya", json={"location_id": "MOON_BASE"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_LOCATION"
    r = core.patch(
        "/v1/participants/p_riya", json={"languages": {"stt_candidates": ["hi-IN", "hi-IN"]}}
    )
    assert r.status_code == 422
    assert core.patch("/v1/participants/p_nobody", json={"available": True}).status_code == 404
    stored = core.get("/v1/participants/p_riya").json()["participant"]
    assert stored == {**RIYA, "available": True, "question_budget": 4}  # nothing half-applied


def test_directory_roles(secure_core: TestClient) -> None:
    c = secure_core
    assert c.get("/v1/participants").status_code == 401
    login(c, "approver")
    assert c.get("/v1/participants").status_code == 200
    r = c.post("/v1/participants", json=RIYA, headers=CSRF)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ROLE_FORBIDDEN"
    login(c, "operator")
    assert c.post("/v1/participants", json=RIYA, headers=CSRF).status_code == 201
    assert c.delete("/v1/participants/p_riya").status_code == 403  # CSRF header missing
    assert c.delete("/v1/participants/p_riya", headers=CSRF).status_code == 204


def _make(core: TestClient, report: str) -> str:
    r = core.post("/v1/investigations", json=body(fault="CB_C2_7.tripped", report=report))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_investigation_list_pages_filters_and_searches(core: TestClient) -> None:
    ids = [_make(core, f"Floor 3 pe WiFi nahi chal raha #{i}") for i in range(5)]
    special = _make(core, "100% down_now, kuch nahi")
    page = core.get("/v1/investigations", params={"limit": 2}).json()
    assert set(page) == {"items", "limit", "next_cursor"}
    assert page["limit"] == 2
    assert [i["id"] for i in page["items"]] == [special, ids[4]]  # newest first
    rest = core.get(
        "/v1/investigations", params={"limit": 10, "cursor": page["next_cursor"]}
    ).json()
    assert [i["id"] for i in rest["items"]] == [ids[3], ids[2], ids[1], ids[0]]
    assert rest["next_cursor"] is None
    item = page["items"][1]
    assert item["status"] == "investigating"
    assert item["participant_count"] == 3
    assert item["reporter_id"] == "p_riya"
    assert item["report_text"].endswith("#4")

    found = core.get("/v1/investigations", params={"q": "#3"}).json()
    assert [i["id"] for i in found["items"]] == [ids[3]]
    # LIKE wildcards in the query are literal characters, not patterns.
    assert len(core.get("/v1/investigations", params={"q": "%"}).json()["items"]) == 1
    assert len(core.get("/v1/investigations", params={"q": "n_n"}).json()["items"]) == 1
    assert len(core.get("/v1/investigations", params={"q": "WIFI"}).json()["items"]) == 5
    by_id = core.get("/v1/investigations", params={"q": ids[2]}).json()
    assert [i["id"] for i in by_id["items"]] == [ids[2]]

    none = core.get("/v1/investigations", params={"status": ["decided", "verified"]}).json()
    assert none["items"] == []
    assert (
        len(core.get("/v1/investigations", params={"status": "investigating"}).json()["items"]) == 6
    )
    assert core.get("/v1/investigations", params={"status": "nonsense"}).status_code == 422
    assert core.get("/v1/investigations", params={"limit": 0}).status_code == 422
    assert core.get("/v1/investigations", params={"limit": 101}).status_code == 422


def test_list_shows_the_decision(secure_core: TestClient) -> None:
    c = secure_core
    c.headers.update(AUTO)
    sim = TestClient(c.sim_app)  # type: ignore[attr-defined]
    inv = c.post("/v1/investigations", json=body(fault="CB_C2_7.tripped")).json()
    final, _ = run_to_conclusion(c, sim, inv)
    assert final["status"] == "decided"
    item = c.get("/v1/investigations", params={"status": "decided"}).json()["items"][0]
    assert item["decision_class"] == "DISPATCH_ELECTRICIAN_DB_C2"
    assert item["decision_probability"] >= 0.95
