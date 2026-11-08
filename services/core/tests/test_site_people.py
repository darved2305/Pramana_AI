"""People per site: checked against the site's own model, versioned edits, used by the check."""

from __future__ import annotations

from itertools import count
from typing import Any

import pytest
from auth_testkit import CSRF
from fastapi.testclient import TestClient
from test_accounts import account_core as account_core
from test_accounts import create

pytestmark = pytest.mark.db
_keys = count()


def key() -> dict[str, str]:
    return {**CSRF, "Idempotency-Key": f"site-people-test-{next(_keys):06d}"}


def person(pid: str, role: str, skill: str, loc: str) -> dict[str, Any]:
    return {
        "id": pid,
        "display_name": pid.removeprefix("p_").title(),
        "roles": [role],
        "skill": skill,
        "location_id": loc,
        "languages": {"stt_candidates": ["hi-IN", "en-IN"], "template_language": "hi"},
    }


def site_root(workspace: dict[str, Any], which: str = "live_site") -> str:
    return f"/v1/orgs/{workspace['organization']['slug']}/sites/{workspace[which]['id']}"


def with_draft(client: TestClient) -> dict[str, Any]:
    workspace = create(client).json()
    draft = client.post(
        site_root(workspace) + "/draft", json={"template_id": "office_water"}, headers=key()
    )
    assert draft.status_code == 200, draft.text
    return workspace


def test_people_need_a_described_site(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    response = client.post(
        site_root(workspace) + "/people",
        json=person("p_asha", "staff", "lay", "LOBBY"),
        headers=key(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SITE_MODEL_REQUIRED"


def test_people_use_the_site_roles_and_places(account_core: TestClient) -> None:
    client = account_core
    workspace = with_draft(client)
    root = site_root(workspace) + "/people"
    added = client.post(
        root, json=person("p_ravi", "plumber", "technician", "LOBBY"), headers=key()
    )
    assert added.status_code == 201, added.text
    assert added.headers["etag"] == '"1"'
    assert added.json()["person"]["roles"] == ["plumber"]

    nurse = client.post(root, json=person("p_meera", "nurse", "lay", "LOBBY"), headers=key())
    assert nurse.status_code == 422
    assert nurse.json()["error"]["code"] == "UNKNOWN_ROLE"
    roof = client.post(root, json=person("p_dev", "staff", "lay", "ROOF"), headers=key())
    assert roof.json()["error"]["code"] == "UNKNOWN_LOCATION"
    again = client.post(
        root, json=person("p_ravi", "plumber", "technician", "LOBBY"), headers=key()
    )
    assert again.status_code == 409

    listed = client.get(root)
    assert [p["person"]["id"] for p in listed.json()] == ["p_ravi"]
    # The practice site has its own, separate list.
    assert client.get(site_root(workspace, "sandbox_site") + "/people").json() == []


def test_edits_need_the_version_being_edited(account_core: TestClient) -> None:
    client = account_core
    workspace = with_draft(client)
    root = site_root(workspace) + "/people"
    client.post(root, json=person("p_ravi", "plumber", "technician", "LOBBY"), headers=key())
    patch = {"location_id": "PUMP_ROOM"}
    assert client.patch(root + "/p_ravi", json=patch, headers=key()).status_code == 428
    stale = client.patch(root + "/p_ravi", json=patch, headers={**key(), "If-Match": '"7"'})
    assert stale.status_code == 412
    moved = client.patch(root + "/p_ravi", json=patch, headers={**key(), "If-Match": '"1"'})
    assert moved.status_code == 200, moved.text
    assert moved.json()["person"]["location_id"] == "PUMP_ROOM"
    assert moved.headers["etag"] == '"2"'
    bad = client.patch(
        root + "/p_ravi", json={"roles": ["pilot"]}, headers={**key(), "If-Match": '"2"'}
    )
    assert bad.json()["error"]["code"] == "UNKNOWN_ROLE"
    gone = client.post(root + "/p_ravi/remove", headers=key())
    assert gone.status_code == 204
    assert client.get(root).json() == []


def test_the_health_check_uses_the_sites_people(account_core: TestClient) -> None:
    client = account_core
    workspace = with_draft(client)
    root = site_root(workspace)
    draft = client.get(root + "/draft").json()
    for p in (
        person("p_asha", "staff", "lay", "F2_WASHROOM"),
        person("p_guard", "guard", "access", "LOBBY"),
        person("p_ravi", "plumber", "technician", "LOBBY"),
        person("p_sunil", "electrician", "technician", "LOBBY"),
        person("p_neha", "staff", "lay", "F1_WASHROOM"),
    ):
        assert client.post(root + "/people", json=p, headers=key()).status_code == 201
    checked = client.post(root + f"/draft/{draft['id']}/health", headers=key()).json()
    assert checked["health"]["cast"] == "directory"
    assert checked["health"]["people"] == 5
