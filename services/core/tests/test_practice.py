"""Practice investigations on a workspace's own, generated site model, through to a repair."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from auth_testkit import CSRF
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion
from test_accounts import account_core as account_core
from test_accounts import create

pytestmark = pytest.mark.db

PEOPLE = [
    ("p_asha", "staff", "lay", "F2_WASHROOM", "hi"),
    ("p_guard", "guard", "access", "LOBBY", "mr"),
    ("p_ravi", "plumber", "technician", "LOBBY", "hi"),
    ("p_sunil", "electrician", "technician", "LOBBY", "hi"),
]


def post(client: TestClient, path: str, json: Any = None) -> Any:
    return client.post(path, json=json, headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex})


def person(pid: str, role: str, skill: str, loc: str, lang: str) -> dict[str, Any]:
    return {
        "id": pid,
        "display_name": pid.removeprefix("p_").title(),
        "roles": [role],
        "skill": skill,
        "location_id": loc,
        "languages": {"stt_candidates": ["hi-IN", "en-IN"], "template_language": lang},
    }


def published_water_site(client: TestClient) -> tuple[dict[str, Any], str]:
    workspace = create(client).json()
    org = workspace["organization"]["slug"]
    site = workspace["live_site"]["id"]
    root = f"/v1/orgs/{org}/sites/{site}"
    draft = post(client, root + "/draft", {"template_id": "office_water"}).json()
    assert post(client, root + f"/draft/{draft['id']}/health").status_code == 200
    assert post(client, root + f"/draft/{draft['id']}/publish").status_code == 200
    for p in PEOPLE:
        assert post(client, root + "/people", person(*p)).status_code == 201
    return workspace, f"/v1/orgs/{org}/investigations"


def request(site_id: str, fault: str, **changes: Any) -> dict[str, Any]:
    component, mode = fault.split(".")
    body = {
        "site_id": site_id,
        "participants": [person(*p) for p in PEOPLE],
        "report": {
            "text": "Doosre floor pe paani nahi aa raha",
            "reporter_id": "p_asha",
            "affected_location_id": "F2_WASHROOM",
        },
        "scenario": {"seed": 7, "fault": {"faults": [{"component_id": component, "mode": mode}]}},
    }
    body.update(changes)
    return body


def test_a_live_site_is_refused_unless_practising(account_core: TestClient) -> None:
    client = account_core
    workspace, investigations = published_water_site(client)
    site = workspace["live_site"]["id"]
    refused = post(client, investigations, request(site, "VALVE_F2.closed"))
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "LIVE_NOT_CONFIGURED"
    started = post(client, investigations, request(site, "VALVE_F2.closed", practice=True))
    assert started.status_code == 201, started.text
    state = started.json()
    assert state["practice"] is True
    assert state["site_id"] == site
    assert state["repair_options"] == []  # nothing decided yet


def test_practice_on_your_own_site_reaches_the_right_repair(account_core: TestClient) -> None:
    client = account_core
    workspace, investigations = published_water_site(client)
    site = workspace["live_site"]["id"]
    initial = post(client, investigations, request(site, "VALVE_F2.closed", practice=True)).json()

    class Scoped:
        """The participant bot talks to the workspace's investigation routes."""

        def post(self, path: str, **kw: Any) -> Any:
            return client.post(
                path.replace("/v1/investigations", investigations),
                headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex, **kw.pop("headers", {})},
                **kw,
            )

        def get(self, path: str, **kw: Any) -> Any:
            return client.get(path.replace("/v1/investigations", investigations), **kw)

    with TestClient(client.app.state.sim._http._transport.app) as sim:
        final, path = run_to_conclusion(Scoped(), sim, initial)  # type: ignore[arg-type]
    assert final["status"] == "decided", final["plan"]["reason"]
    assert final["plan"]["decision_class"] == "VALVE_F2_CLOSED", path
    options = final["repair_options"]
    assert [(o["action"], o["target"]) for o in options] == [("open_valve", "VALVE_F2")]
    assert options[0]["participant_ids"] == ["p_ravi"]  # only the plumber may open it
    assert options[0]["place"] == "the pump room"

    approval = post(
        client,
        f"{investigations}/{final['id']}/approvals",
        {"action": "open_valve", "target": "VALVE_F2", "participant_id": "p_ravi"},
    )
    assert approval.status_code in (200, 201), approval.text
    assert approval.json()["approvals"][0]["action_label"] == "Open a closed valve"
    assert approval.json()["repair_options"] == []  # awaiting approval now


def test_the_shared_practice_site_is_always_practice(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    org = workspace["organization"]["slug"]
    body = {
        "site_id": workspace["sandbox_site"]["id"],
        "participants": [
            person("p_riya", "student", "lay", "F3_R304", "hi"),
            person("p_imran", "electrician", "technician", "MAINT_ROOM", "hi"),
        ],
        "report": {"text": "WiFi is down on floor 3", "reporter_id": "p_riya"},
        "scenario": {"seed": 3, "fault": "random"},
    }
    started = post(client, f"/v1/orgs/{org}/investigations", body)
    assert started.status_code == 201, started.text
    assert started.json()["practice"] is True


def test_track_record_counts_only_revealed_truth(account_core: TestClient) -> None:
    client = account_core
    workspace, investigations = published_water_site(client)
    site = workspace["live_site"]["id"]
    org = workspace["organization"]["slug"]
    record_path = f"/v1/orgs/{org}/sites/{site}/people/track-record"
    initial = post(client, investigations, request(site, "VALVE_F2.closed", practice=True)).json()

    class Scoped:
        def post(self, path: str, **kw: Any) -> Any:
            return client.post(
                path.replace("/v1/investigations", investigations),
                headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex, **kw.pop("headers", {})},
                **kw,
            )

        def get(self, path: str, **kw: Any) -> Any:
            return client.get(path.replace("/v1/investigations", investigations), **kw)

    with TestClient(client.app.state.sim._http._transport.app) as sim:
        final, _ = run_to_conclusion(Scoped(), sim, initial)  # type: ignore[arg-type]
    # Nothing is known until the truth is: Pramana's own conclusion is not evidence.
    assert client.get(record_path).json() == []
    revealed = post(client, f"{investigations}/{final['id']}/reveal")
    assert revealed.status_code == 200, revealed.text
    records = {r["person_id"]: r for r in client.get(record_path).json()}
    assert records, "someone answered"
    for r in records.values():
        assert r["matched"] == r["checked"] > 0  # the bot answered truthfully
        assert r["investigations"] == 1
        assert sum(k["checked"] for k in r["by_kind"]) == r["checked"]
