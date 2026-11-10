"""The saved-model API authorizes membership before parsing resource ids or returning data."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from auth_testkit import CSRF, login
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from starlette.background import BackgroundTask
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql as _sql

from pramana_contracts import StaffRole
from pramana_core import ids
from pramana_core.auth.deps import require_staff
from pramana_core.db import current_actor, current_org, current_user
from pramana_core.tenant_routes import OrganizationRoute
from pramana_domain.spec_storage import spec_digest

pytestmark = pytest.mark.db

# New site operations must have real cross-organization requests, not just schema inventory.
SITE_OPERATIONS = {
    ("get", "/v1/orgs/{org}/sites"),
    ("get", "/v1/orgs/{org}/sites/{site_id}"),
    ("get", "/v1/orgs/{org}/sites/{site_id}/models"),
    ("get", "/v1/orgs/{org}/sites/{site_id}/models/{model_id}"),
    ("get", "/v1/orgs/{org}/sites/{site_id}/draft"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/draft"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/draft/{model_id}/health"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/draft/{model_id}/publish"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/draft/{model_id}/discard"),
    ("get", "/v1/orgs/{org}/sites/{site_id}/people"),
    ("get", "/v1/orgs/{org}/sites/{site_id}/people/track-record"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/people"),
    ("patch", "/v1/orgs/{org}/sites/{site_id}/people/{person_id}"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/people/{person_id}/remove"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/people/{person_id}/erase"),
    ("get", "/v1/orgs/{org}/sites/{site_id}/people/{person_id}/consents"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/people/{person_id}/consents"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/people/{person_id}/consents/{purpose}/withdraw"),
    ("post", "/v1/orgs/{org}/sites/{site_id}/people/{person_id}/consent-requests"),
    ("get", "/v1/orgs/{org}/sites/{site_id}/people/{person_id}/consent-requests/{request_id}"),
}

DOMAIN_JOIN_OPERATIONS = {
    ("get", "/v1/orgs/{org}/domains"),
    ("post", "/v1/orgs/{org}/domains"),
    ("post", "/v1/orgs/{org}/domains/{domain}/verify"),
    ("patch", "/v1/orgs/{org}/domains/{domain}"),
    ("delete", "/v1/orgs/{org}/domains/{domain}"),
    ("get", "/v1/orgs/{org}/join-requests"),
    ("post", "/v1/orgs/{org}/join-requests/{request_id}/approve"),
    ("post", "/v1/orgs/{org}/join-requests/{request_id}/decline"),
}


# A valid body per unsafe operation, so the organization boundary itself is what answers.
VALID_BODIES: dict[tuple[str, str], Any] = {
    ("post", "/draft"): {"template_id": "office_water"},
    ("post", "/people"): {
        "id": "p_probe",
        "display_name": "Probe",
        "roles": ["staff"],
        "skill": "lay",
        "location_id": "LOBBY",
        "languages": {"stt_candidates": ["hi-IN"]},
    },
    ("patch", "/people/{person_id}"): {"display_name": "Probe"},
    ("post", "/people/{person_id}/consents"): {
        "purpose": "voice_processing",
        "notice_version": "1",
        "language": "en",
        "channel": "paper",
    },
}


def sql(url: str, statement: str, **params: Any) -> list[dict[str, Any]]:
    return _sql(url, statement, params)


@pytest.fixture
def two_workspaces(account_core: TestClient) -> tuple[TestClient, dict[str, Any], dict[str, Any]]:
    client = account_core
    a = create(client, name="First campus", slug="first-campus").json()
    login(client, "approver")
    b = client.post(
        "/v1/orgs",
        json={"name": "Second campus", "slug": "second-campus"},
        headers={**CSRF, "Idempotency-Key": "second-workspace-001"},
    )
    assert b.status_code == 201, b.text
    return client, a, b.json()


def _path(template: str, workspace: dict[str, Any], *, org: str | None = None) -> str:
    return template.format(
        org=org or workspace["organization"]["slug"],
        site_id=workspace["sandbox_site"]["id"],
        person_id="p_probe",
        purpose="voice_processing",
        request_id="consent_probe",
        model_id=workspace["sandbox_site"]["current_model_id"],
    )


def test_site_operation_inventory_is_exhaustive(account_core: TestClient) -> None:
    actual = {
        (method, path)
        for path, definition in account_core.app.openapi()["paths"].items()
        if path.startswith("/v1/orgs/{org}/sites")
        for method in definition
        if method in {"get", "post", "patch", "put", "delete"}
    }
    assert actual == SITE_OPERATIONS


def test_domain_join_operation_inventory_is_exhaustive(account_core: TestClient) -> None:
    actual = {
        (method, path)
        for path, definition in account_core.app.openapi()["paths"].items()
        if path.startswith(("/v1/orgs/{org}/domains", "/v1/orgs/{org}/join-requests"))
        for method in definition
        if method in {"get", "post", "patch", "put", "delete"}
    }
    assert actual == DOMAIN_JOIN_OPERATIONS


@pytest.mark.parametrize(("method", "template"), sorted(DOMAIN_JOIN_OPERATIONS))
def test_other_member_cannot_access_domain_join_operations(
    two_workspaces: tuple[TestClient, dict[str, Any], dict[str, Any]], method: str, template: str
) -> None:
    client, workspace, _ = two_workspaces
    path = template.format(
        org=workspace["organization"]["slug"],
        domain="college.edu",
        request_id=ids.new("join")[1],
    )
    response = client.request(
        method,
        path,
        headers={**CSRF, "Idempotency-Key": "domain-cross-org-probe-001"},
        json={},
    )
    assert response.status_code == 404, response.text
    assert workspace["organization"]["name"] not in response.text


@pytest.mark.parametrize(("method", "template"), sorted(SITE_OPERATIONS))
def test_other_member_cannot_read_any_site_operation(
    two_workspaces: tuple[TestClient, dict[str, Any], dict[str, Any]], method: str, template: str
) -> None:
    client, a, b = two_workspaces  # Signed in as B, whose legacy global role includes approver.
    for path in (_path(template, a), _path(template, a, org=b["organization"]["slug"])):
        # Unsafe methods carry CSRF and a key so the organization boundary itself answers.
        unsafe = {**CSRF, "Idempotency-Key": "cross-org-probe-0001"}
        body = VALID_BODIES.get((method, template.rsplit("/sites/{site_id}", 1)[-1]))
        if method == "patch" and "If-Match" not in unsafe:
            unsafe = {**unsafe, "If-Match": '"1"'}
        response = client.request(
            method, path, headers=unsafe if method != "get" else None, json=body
        )
        if template.endswith("/sites") and b["organization"]["slug"] in path:
            assert response.status_code == 200
            assert {site["org_id"] for site in response.json()["items"]} == {
                b["organization"]["id"]
            }
        else:
            assert response.status_code == 404, response.text
            assert "First campus" not in response.text
            assert a["sandbox_site"]["current_model_id"] not in response.text


def test_owner_can_read_saved_model_and_hash_its_exact_spec(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    root = _path("/v1/orgs/{org}/sites/{site_id}", workspace)
    sites = client.get(_path("/v1/orgs/{org}/sites", workspace))
    assert sites.status_code == 200, sites.text
    assert {site["mode"] for site in sites.json()["items"]} == {"sandbox", "live"}
    assert client.get(root).json() == workspace["sandbox_site"]
    models = client.get(root + "/models")
    assert models.status_code == 200, models.text
    assert len(models.json()["items"]) == 1
    assert "spec" not in models.json()["items"][0]
    document = client.get(root + "/models/" + workspace["sandbox_site"]["current_model_id"])
    assert document.status_code == 200, document.text
    body = document.json()
    assert body["spec_sha256"] == spec_digest(body["spec"]).hex()
    assert body["status"] == "published"
    assert body["org_id"] == workspace["organization"]["id"]
    assert set(body) == set(models.json()["items"][0]) | {"spec", "description", "health"}
    assert body["description"] is None  # the frozen sandbox was not made with the builder
    assert document.headers["cache-control"] == "private, no-store"
    assert document.headers["etag"].startswith('"')
    assert client.get(document.request.url).headers["etag"] == document.headers["etag"]
    # The same resource can be addressed by its typed organization id or slug.
    by_id = client.get(
        str(document.request.url).replace(
            workspace["organization"]["slug"], workspace["organization"]["id"]
        )
    )
    assert by_id.content == document.content


def test_revoked_membership_blocks_even_malformed_site_ids(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    workspace = create(client).json()
    org_id = ids.decode("org", workspace["organization"]["id"])
    sql(migrated_db, "delete from memberships where org_id=:org", org=org_id)
    for suffix in ("", "/bad-id", "/bad-id/models", "/bad-id/models/bad-model"):
        response = client.get(f"/v1/orgs/{workspace['organization']['slug']}/sites{suffix}")
        assert response.status_code == 404, response.text


def test_anonymous_cannot_discover_sites(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    client.cookies.clear()
    response = client.get(_path("/v1/orgs/{org}/sites", workspace))
    assert response.status_code == 401


def test_drafts_and_archived_sites_are_not_exposed(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    workspace = create(client).json()
    original = ids.decode("model", workspace["sandbox_site"]["current_model_id"])
    draft_id = ids.uuid7()
    sql(
        migrated_db,
        """
        insert into site_models (id, org_id, site_id, version, status, spec, spec_sha256)
        select :draft, org_id, site_id, 2, 'draft', spec, spec_sha256
        from site_models where id=:original
    """,
        draft=draft_id,
        original=original,
    )
    root = _path("/v1/orgs/{org}/sites/{site_id}", workspace)
    assert len(client.get(root + "/models").json()["items"]) == 1
    assert client.get(root + "/models/" + ids.encode("model", draft_id)).status_code == 404
    sql(
        migrated_db,
        "update sites set archived_at=now() where id=:site",
        site=ids.decode("site", workspace["sandbox_site"]["id"]),
    )
    for path in (root, root + "/models", root + "/models/" + ids.encode("model", original)):
        assert client.get(path).status_code == 404


@pytest.fixture
def boundary_routes(account_core: TestClient) -> dict[str, Any]:
    client = account_core
    observed: dict[str, Any] = {}
    router = APIRouter(prefix="/v1/orgs/{org}/test-boundary", route_class=OrganizationRoute)

    def context() -> dict[str, Any]:
        return {
            "org": str(current_org.get()),
            "user": current_user.get(),
            "actor": current_actor.get(),
        }

    @router.get("/stream")
    async def stream(org: str) -> StreamingResponse:
        async def chunks() -> AsyncIterator[str]:
            for _ in range(2):
                await asyncio.sleep(0)
                yield json.dumps(context()) + "\n"

        def after_response() -> None:
            observed["background"] = context()

        return StreamingResponse(chunks(), background=BackgroundTask(after_response))

    @router.get("/operate", dependencies=[Depends(require_staff(StaffRole.OPERATOR))])
    async def operate(org: str) -> dict[str, str]:
        return {"ok": "operator"}

    @router.get("/approve", dependencies=[Depends(require_staff(StaffRole.APPROVER))])
    async def approve(org: str) -> dict[str, str]:
        return {"ok": "approver"}

    @client.app.get("/test-context-outside-tenant")
    async def outside(request: Request) -> dict[str, Any]:
        return context()

    client.app.include_router(router)
    return observed


def test_membership_replaces_global_roles_and_owner_is_not_approver(
    account_core: TestClient, boundary_routes: dict[str, Any], migrated_db: str
) -> None:
    client = account_core
    workspace = create(client).json()
    root = f"/v1/orgs/{workspace['organization']['slug']}/test-boundary"
    org_id = ids.decode("org", workspace["organization"]["id"])
    # This account has a global operator role, but it is only a viewer in this organization.
    sql(migrated_db, "update memberships set roles=ARRAY['viewer'] where org_id=:org", org=org_id)
    assert client.get(root + "/operate").status_code == 403
    sql(migrated_db, "update memberships set roles=ARRAY['owner'] where org_id=:org", org=org_id)
    assert client.get(root + "/operate").status_code == 200
    assert client.get(root + "/approve").status_code == 403


def test_context_survives_streaming_and_background_then_resets(
    account_core: TestClient, boundary_routes: dict[str, Any]
) -> None:
    client = account_core
    workspace = create(client).json()
    response = client.get(f"/v1/orgs/{workspace['organization']['slug']}/test-boundary/stream")
    assert response.status_code == 200, response.text
    expected = {
        "org": str(ids.decode("org", workspace["organization"]["id"])),
        "user": client.user_ids["operator"],
        "actor": f"user:{client.user_ids['operator']}",
    }
    assert [json.loads(line) for line in response.text.splitlines()] == [expected, expected]
    assert boundary_routes["background"] == expected
    assert client.get("/test-context-outside-tenant").json() == {
        "org": "None",
        "user": None,
        "actor": None,
    }


def test_simultaneous_organizations_do_not_share_request_context(
    two_workspaces: tuple[TestClient, dict[str, Any], dict[str, Any]],
) -> None:
    client, a, b = two_workspaces
    cookie_name = client.app.state.settings.session_cookie_name
    cookie_b = client.cookies[cookie_name]
    # Signing in rotates the presented session, even when switching accounts. Keep B's
    # independent device session alive by not presenting it during A's sign-in.
    client.cookies.clear()
    login(client, "operator")
    cookie_a = client.cookies[cookie_name]

    def read(workspace: dict[str, Any], cookie: str) -> None:
        response = client.get(
            _path("/v1/orgs/{org}/sites", workspace), headers={"Cookie": f"{cookie_name}={cookie}"}
        )
        assert response.status_code == 200, response.text
        assert {site["org_id"] for site in response.json()["items"]} == {
            workspace["organization"]["id"]
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = [
            pool.submit(read, workspace, cookie)
            for workspace, cookie in [(a, cookie_a), (b, cookie_b)] * 4
        ]
        for future in pending:
            future.result(timeout=20)
