"""Describe a site, check the generated model, publish it: over HTTP, scoped to a workspace."""

from __future__ import annotations

import copy
from itertools import count
from typing import Any

import pytest
from auth_testkit import CSRF
from fastapi.testclient import TestClient
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql

from pramana_core import ids
from pramana_domain.catalog import template
from pramana_domain.spec_storage import spec_digest

pytestmark = pytest.mark.db
_keys = count()


def key() -> dict[str, str]:
    return {**CSRF, "Idempotency-Key": f"site-builder-test-{next(_keys):06d}"}


def draft_path(workspace: dict[str, Any], suffix: str = "") -> str:
    org, site = workspace["organization"]["slug"], workspace["live_site"]["id"]
    return f"/v1/orgs/{org}/sites/{site}/draft{suffix}"


def start(client: TestClient, workspace: dict[str, Any], **body: Any) -> Any:
    response = client.post(
        draft_path(workspace), json=body or {"template_id": "office_water"}, headers=key()
    )
    assert response.status_code == 200, response.text
    return response


def test_library_lists_equipment_and_templates(account_core: TestClient) -> None:
    client = account_core
    equipment = client.get("/v1/library/equipment")
    assert equipment.status_code == 200, equipment.text
    by_id = {t["id"]: t for t in equipment.json()}
    assert {"pump", "valve", "breaker", "lift", "terminal"} <= set(by_id)
    assert by_id["valve"]["repairs"][0]["trade"] == "plumber"
    templates = client.get("/v1/library/templates")
    assert {t["id"] for t in templates.json()} >= {"office_water", "retail_billing", "ward_cooling"}
    client.cookies.clear()
    assert client.get("/v1/library/equipment").status_code == 401


def test_template_to_published_model(account_core: TestClient, migrated_db: str) -> None:
    client = account_core
    workspace = create(client).json()
    assert client.get(draft_path(workspace)).status_code == 404
    draft = start(client, workspace).json()
    assert draft["status"] == "draft"
    assert draft["version"] == 1
    assert draft["health"] is None
    assert draft["counts"]["equipment"] == 7
    assert draft["description"]["title"] == "Office water supply"

    early = client.post(draft_path(workspace, f"/{draft['id']}/publish"), headers=key())
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "HEALTH_CHECK_REQUIRED"

    checked = client.post(draft_path(workspace, f"/{draft['id']}/health"), headers=key())
    assert checked.status_code == 200, checked.text
    health = checked.json()["health"]
    assert health["ok"] is True
    assert health["cast"] == "one_per_role"
    assert health["people"] == 4
    assert health["spec_sha256"] == draft["spec_sha256"]
    assert any(f["reportable"] and f["episodes"] for f in health["faults"])

    published = client.post(draft_path(workspace, f"/{draft['id']}/publish"), headers=key())
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    org, site = workspace["organization"]["slug"], workspace["live_site"]["id"]
    assert client.get(f"/v1/orgs/{org}/sites/{site}").json()["current_model_id"] == draft["id"]
    assert client.get(draft_path(workspace)).status_code == 404
    stored = client.get(f"/v1/orgs/{org}/sites/{site}/models/{draft['id']}").json()
    assert spec_digest(stored["spec"]).hex() == stored["spec_sha256"] == draft["spec_sha256"]
    assert stored["spec"]["physics"] == "dependency"

    # The published version, its description and its health report are frozen.
    model_id = ids.decode("model", draft["id"])
    with pytest.raises(Exception, match="immutable"):
        sql(migrated_db, "update site_models set source = '{}' where id = :id", {"id": model_id})


def test_editing_needs_the_version_being_edited(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    first = start(client, workspace)
    etag = first.headers["etag"]
    description = copy.deepcopy(first.json()["description"])
    description["title"] = "Office water, block B"

    missing = client.post(draft_path(workspace), json={"description": description}, headers=key())
    assert missing.status_code == 428
    stale = client.post(
        draft_path(workspace),
        json={"description": description},
        headers={**key(), "If-Match": '"' + "0" * 64 + '"'},
    )
    assert stale.status_code == 412
    saved = client.post(
        draft_path(workspace),
        json={"description": description},
        headers={**key(), "If-Match": etag},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["id"] == first.json()["id"]  # still the one draft
    assert saved.json()["description"]["title"] == "Office water, block B"
    assert saved.headers["etag"] != etag


def test_empty_lists_say_what_to_add(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    description = {
        "id": "empty_site",
        "title": "Empty site",
        "roles": [],
        "places": [],
        "equipment": [],
        "service_points": [],
    }
    response = client.post(draft_path(workspace), json={"description": description}, headers=key())
    assert response.status_code == 422, response.text
    problems = response.json()["error"]["details"]["problems"]
    assert problems == [
        "Add at least one role.",
        "Add at least one place.",
        "Add at least one piece of equipment.",
        "Add at least one place where problems are noticed.",
    ]


def test_problems_come_back_readable(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    first = start(client, workspace)
    broken = copy.deepcopy(first.json()["description"])
    broken["equipment"][3]["needs"] = ["NO_SUCH_THING"]
    broken["equipment"][0]["type"] = "teleporter"
    response = client.post(
        draft_path(workspace),
        json={"description": broken},
        headers={**key(), "If-Match": first.headers["etag"]},
    )
    assert response.status_code == 422, response.text
    problems = response.json()["error"]["details"]["problems"]
    assert any("NO_SUCH_THING" in p for p in problems)
    assert any("teleporter" in p for p in problems)
    # The draft is unchanged.
    assert client.get(draft_path(workspace)).headers["etag"] == first.headers["etag"]


def test_an_edit_makes_the_health_report_stale(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    draft = start(client, workspace)
    checked = client.post(draft_path(workspace, f"/{draft.json()['id']}/health"), headers=key())
    description = copy.deepcopy(draft.json()["description"])
    description["equipment"][3]["priors"] = {"failed": 0.02}
    edited = client.post(
        draft_path(workspace),
        json={"description": description},
        headers={**key(), "If-Match": checked.headers["etag"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["health"] is None
    publish = client.post(draft_path(workspace, f"/{draft.json()['id']}/publish"), headers=key())
    assert publish.json()["error"]["code"] == "HEALTH_CHECK_REQUIRED"


def test_a_failing_health_check_blocks_publishing(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    description = template("office_water")
    assert description is not None
    for place in description["places"]:  # nobody but office staff may go anywhere
        if place.get("restricted"):
            place["access"] = ["staff"]
    description["roles"] = [r for r in description["roles"] if r["skill"] == "lay"]
    draft = start(client, workspace, description=description).json()
    checked = client.post(draft_path(workspace, f"/{draft['id']}/health"), headers=key()).json()
    assert checked["health"]["ok"] is False
    assert any(f["code"] == "INDISTINGUISHABLE" for f in checked["health"]["findings"])
    publish = client.post(draft_path(workspace, f"/{draft['id']}/publish"), headers=key())
    assert publish.status_code == 409
    assert publish.json()["error"]["code"] == "HEALTH_CHECK_FAILED"


def test_republishing_retires_the_previous_version(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    versions = []
    for _ in range(2):
        draft = start(client, workspace).json()
        client.post(draft_path(workspace, f"/{draft['id']}/health"), headers=key())
        published = client.post(draft_path(workspace, f"/{draft['id']}/publish"), headers=key())
        assert published.status_code == 200, published.text
        versions.append(draft)
    assert [v["version"] for v in versions] == [1, 2]
    org, site = workspace["organization"]["slug"], workspace["live_site"]["id"]
    listed = {
        m["id"]: m["status"]
        for m in client.get(f"/v1/orgs/{org}/sites/{site}/models").json()["items"]
    }
    assert listed == {versions[0]["id"]: "retired", versions[1]["id"]: "published"}


def test_discarding_a_draft(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    draft = start(client, workspace).json()
    gone = client.post(draft_path(workspace, f"/{draft['id']}/discard"), headers=key())
    assert gone.status_code == 204
    assert client.get(draft_path(workspace)).status_code == 404


def test_the_practice_site_cannot_be_edited(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    org, site = workspace["organization"]["slug"], workspace["sandbox_site"]["id"]
    response = client.post(
        f"/v1/orgs/{org}/sites/{site}/draft", json={"template_id": "office_water"}, headers=key()
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SANDBOX_READ_ONLY"


def test_unknown_template(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    response = client.post(draft_path(workspace), json={"template_id": "castle"}, headers=key())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_TEMPLATE"
