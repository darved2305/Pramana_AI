"""Inviting a teammate with a one-time link: email match, expiry, revocation, roles, isolation."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from auth_testkit import CSRF, USERS, login
from fastapi.testclient import TestClient
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql

from pramana_core import ids

pytestmark = pytest.mark.db
APPROVER_EMAIL = USERS["approver"][0]


def post(client: TestClient, path: str, json: Any = None) -> Any:
    return client.post(path, json=json, headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex})


def invite(client: TestClient, org: str, email: str, roles: list[str]) -> dict[str, Any]:
    r = post(client, f"/v1/orgs/{org}/invitations", {"email": email, "roles": roles})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    assert body["accept_path"].startswith("/invite/org_")
    return body


def token(created: dict[str, Any]) -> str:
    return str(created["accept_path"]).removeprefix("/invite/")


def test_an_invited_person_joins_with_the_roles_given(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    org = workspace["organization"]["slug"]
    created = invite(client, org, APPROVER_EMAIL.upper(), ["approver", "operator", "approver"])
    assert created["invitation"]["email"] == APPROVER_EMAIL
    assert created["invitation"]["roles"] == ["approver", "operator"]
    assert created["invitation"]["status"] == "pending"

    login(client, "approver")
    accepted = post(client, "/v1/invitations/accept", {"token": token(created)})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["destination"] == f"/app/{org}"
    assert accepted.json()["organization"]["roles"] == ["approver", "operator"]
    me = client.get("/v1/me").json()
    assert [m["slug"] for m in me["memberships"]] == [org]
    # Accepting again is harmless for the same person.
    assert post(client, "/v1/invitations/accept", {"token": token(created)}).status_code == 200
    members = client.get(f"/v1/orgs/{org}/members").json()
    assert len(members) == 2
    assert all(m["email"] is None or m["you"] for m in members)  # not an admin: no addresses

    login(client, "operator")
    listed = client.get(f"/v1/orgs/{org}/invitations").json()
    assert [i["status"] for i in listed] == ["accepted"]


def test_the_link_works_only_for_the_invited_address(account_core: TestClient) -> None:
    client = account_core
    org = create(client).json()["organization"]["slug"]
    created = invite(client, org, "someone.else@example.com", ["viewer"])
    login(client, "approver")
    r = post(client, "/v1/invitations/accept", {"token": token(created)})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "INVITATION_EMAIL_MISMATCH"
    message = r.json()["error"]["message"]
    assert "so****" in message  # masked, so the invited address is not disclosed
    assert "someone.else" not in message


def test_revoked_expired_and_forged_links_fail(account_core: TestClient, migrated_db: str) -> None:
    client = account_core
    workspace = create(client).json()
    org = workspace["organization"]["slug"]
    first = invite(client, org, APPROVER_EMAIL, ["viewer"])
    # A second invitation to the same address replaces the first.
    second = invite(client, org, APPROVER_EMAIL, ["approver"])
    revoked = post(client, f"/v1/orgs/{org}/invitations/{second['invitation']['id']}/revoke")
    assert revoked.status_code == 204
    third = invite(client, org, APPROVER_EMAIL, ["approver"])
    sql(
        migrated_db,
        "update invitations set expires_at = now() - interval '1 minute' where id = :id",
        {"id": ids.decode("invite", third["invitation"]["id"])},
    )
    login(client, "approver")
    for created, code in ((first, "INVITATION_REVOKED"), (third, "INVITATION_EXPIRED")):
        r = post(client, "/v1/invitations/accept", {"token": token(created)})
        assert r.status_code == 410, r.text
        assert r.json()["error"]["code"] == code
    org_part = token(third).split(".")[0]
    forged = post(client, "/v1/invitations/accept", {"token": f"{org_part}.{'x' * 43}"})
    assert forged.status_code == 404
    assert client.get("/v1/me").json()["memberships"] == []


def test_only_owners_and_admins_invite(account_core: TestClient) -> None:
    client = account_core
    org = create(client).json()["organization"]["slug"]
    created = invite(client, org, APPROVER_EMAIL, ["viewer"])
    login(client, "approver")
    assert post(client, "/v1/invitations/accept", {"token": token(created)}).status_code == 200
    r = post(client, f"/v1/orgs/{org}/invitations", {"email": "x@example.com", "roles": ["viewer"]})
    assert r.status_code == 403
    assert client.get(f"/v1/orgs/{org}/invitations").json() == []


def test_owners_cannot_be_invited_and_members_cannot_be_invited_twice(
    account_core: TestClient,
) -> None:
    client = account_core
    org = create(client).json()["organization"]["slug"]
    owner = post(
        client, f"/v1/orgs/{org}/invitations", {"email": "a@example.com", "roles": ["owner"]}
    )
    assert owner.status_code == 422
    me = USERS["operator"][0]
    twice = post(client, f"/v1/orgs/{org}/invitations", {"email": me, "roles": ["viewer"]})
    assert twice.status_code == 409
    assert twice.json()["error"]["code"] == "ALREADY_MEMBER"


def test_another_workspace_cannot_see_or_revoke_invitations(account_core: TestClient) -> None:
    client = account_core
    org = create(client).json()["organization"]["slug"]
    created = invite(client, org, "a@example.com", ["viewer"])
    login(client, "approver")
    other = post(client, "/v1/orgs", {"name": "Other campus"})
    assert other.status_code == 201, other.text
    other_slug = other.json()["organization"]["slug"]
    assert client.get(f"/v1/orgs/{org}/invitations").status_code == 404
    invite_id = created["invitation"]["id"]
    assert post(client, f"/v1/orgs/{org}/invitations/{invite_id}/revoke").status_code == 404
    assert post(client, f"/v1/orgs/{other_slug}/invitations/{invite_id}/revoke").status_code == 404
