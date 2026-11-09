"""Verified email domains can suggest, request, and automatically join workspaces."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Iterator

import httpx
import pytest
from auth_testkit import CSRF, _seed, login
from core_testkit import core_settings, truncate_all
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core.main import create_app

pytestmark = pytest.mark.db


class FakeTxtResolver:
    def __init__(self) -> None:
        self.records: set[str] = set()

    async def lookup_txt(self, name: str) -> set[str]:
        assert name.startswith("_pramana-verify.")
        return self.records


def _headers(key: str) -> dict[str, str]:
    return {**CSRF, "Idempotency-Key": key}


def _use_session(client: TestClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set("pramana_session", token)


def _google_session(
    db_url: str,
    user_id: str,
    email: str,
    hosted_domain: str | None,
    *,
    verified: bool = True,
) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    async def seed() -> None:
        engine = create_async_engine(db_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "update users set email = :email, "
                        "email_verified_at = case when :verified then now() else null end "
                        "where id = :user_id"
                    ),
                    {"email": email, "verified": verified, "user_id": user_id},
                )
                await conn.execute(
                    text(
                        "insert into sessions (token_hash, user_id, created_at, expires_at, "
                        "auth_method, hosted_domain) values (:hash, :user_id, now(), "
                        "now() + interval '12 hours', 'google', :hosted_domain)"
                    ),
                    {
                        "hash": token_hash,
                        "user_id": user_id,
                        "hosted_domain": hosted_domain,
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return token


@pytest.fixture(params=["owner", "runtime"])
def domain_core(
    request: pytest.FixtureRequest, migrated_db: str, sim_app: FastAPI
) -> Iterator[TestClient]:
    asyncio.run(truncate_all(migrated_db))
    user_ids = asyncio.run(_seed(migrated_db))
    app_url = migrated_db
    if request.param == "runtime":
        app_url = (
            make_url(app_url)
            .set(username="pramana_app", password=None)
            .render_as_string(hide_password=False)
        )
    resolver = FakeTxtResolver()
    app = create_app(
        core_settings(app_url, AUTH_REQUIRED=True, CORE_AUTOMATION_KEY=""),
        sim_transport=httpx.ASGITransport(app=sim_app),
        dns_txt_resolver=resolver,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        client.user_ids = user_ids  # type: ignore[attr-defined]
        client.db_url = migrated_db  # type: ignore[attr-defined]
        client.resolver = resolver  # type: ignore[attr-defined]
        login(client, "operator")
        created = client.post(
            "/v1/orgs",
            json={"name": "Nava College"},
            headers=_headers("domain-org-create-0001"),
        )
        assert created.status_code == 201, created.text
        client.org_id = created.json()["organization"]["id"]  # type: ignore[attr-defined]
        client.owner_token = _google_session(  # type: ignore[attr-defined]
            migrated_db, user_ids["operator"], "owner@college.edu", "college.edu"
        )
        _use_session(client, client.owner_token)
        added = client.post(
            f"/v1/orgs/{client.org_id}/domains",
            json={"domain": "college.edu", "verification": "google_hd"},
            headers=_headers("domain-add-primary-0001"),
        )
        assert added.status_code == 201, added.text
        verified = client.post(
            f"/v1/orgs/{client.org_id}/domains/college.edu/verify",
            headers=_headers("domain-verify-primary-001"),
        )
        assert verified.status_code == 200, verified.text
        yield client


def _request(client: TestClient, org_id: str, key: str) -> httpx.Response:
    return client.post(
        "/v1/join-requests",
        json={"organization_id": org_id},
        headers=_headers(key),
    )


def _as_requester(
    client: TestClient,
    email: str = "member@college.edu",
    hd: str | None = "college.edu",
    verified: bool = True,
) -> str:
    token = _google_session(
        client.db_url,  # type: ignore[attr-defined]
        client.user_ids["approver"],  # type: ignore[attr-defined]
        email,
        hd,
        verified=verified,
    )
    _use_session(client, token)
    return token


def _as_owner(client: TestClient) -> None:
    _use_session(client, client.owner_token)  # type: ignore[attr-defined]


def test_verified_domain_suggestions_and_request_approval_notifications(
    domain_core: TestClient,
) -> None:
    client = domain_core
    org_id = client.org_id  # type: ignore[attr-defined]
    requester = _as_requester(client)
    suggestion = client.get("/v1/me").json()["join_suggestions"]
    assert [row["organization_id"] for row in suggestion] == [org_id]
    assert suggestion[0]["policy"] == "request"

    first = _request(client, org_id, "join-request-pending-0001")
    assert first.status_code == 201, first.text
    pending = first.json()["request"]
    assert pending["status"] == "pending"
    assert first.json()["joined"] is False

    replay = _request(client, org_id, "join-request-pending-0001")
    assert replay.status_code == 201, replay.text
    assert replay.content == first.content
    assert replay.headers.get("idempotent-replayed") == "true"

    duplicate = _request(client, org_id, "join-request-pending-0002")
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["request"]["id"] == pending["id"]

    me = client.get("/v1/me").json()
    assert me["join_suggestions"][0]["request_id"] == pending["id"]
    _as_owner(client)
    requests = client.get(f"/v1/orgs/{org_id}/join-requests")
    assert requests.status_code == 200, requests.text
    assert [row["id"] for row in requests.json()] == [pending["id"]]
    outbox = client.app.state.domain_joins.mailer
    assert any("asked to join Nava College" in body for _, _, body in outbox.messages)

    approved = client.post(
        f"/v1/orgs/{org_id}/join-requests/{pending['id']}/approve",
        json={"role": "viewer"},
        headers=_headers("join-approve-viewer-0001"),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["role"] == "viewer"

    _use_session(client, requester)
    me = client.get("/v1/me").json()
    assert any(org["id"] == org_id and org["roles"] == ["viewer"] for org in me["memberships"])
    assert me["join_suggestions"] == []


def test_cancel_decline_and_removed_member_can_request_again(domain_core: TestClient) -> None:
    client = domain_core
    org_id = client.org_id  # type: ignore[attr-defined]
    requester = _as_requester(client)
    first = _request(client, org_id, "join-cancel-create-0001").json()["request"]
    cancelled = client.post(
        f"/v1/join-requests/{first['id']}/cancel",
        headers=_headers("join-cancel-action-0001"),
    )
    assert cancelled.status_code == 204, cancelled.text

    second = _request(client, org_id, "join-request-after-cancel-1").json()["request"]
    assert second["id"] != first["id"]
    _as_owner(client)
    declined = client.post(
        f"/v1/orgs/{org_id}/join-requests/{second['id']}/decline",
        headers=_headers("join-decline-action-0001"),
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"

    _use_session(client, requester)
    third = _request(client, org_id, "join-request-before-approval-01").json()["request"]
    _as_owner(client)
    approved = client.post(
        f"/v1/orgs/{org_id}/join-requests/{third['id']}/approve",
        json={"role": "viewer"},
        headers=_headers("join-approve-before-remove-01"),
    )
    assert approved.status_code == 200, approved.text
    removed = client.post(
        f"/v1/orgs/{org_id}/members/{client.user_ids['approver']}/remove",  # type: ignore[attr-defined]
        headers=_headers("join-remove-member-action-001"),
    )
    assert removed.status_code == 204, removed.text

    _use_session(client, requester)
    fourth = _request(client, org_id, "join-request-after-remove-01")
    assert fourth.status_code == 201, fourth.text
    assert fourth.json()["request"]["status"] == "pending"
    assert fourth.json()["request"]["id"] not in {first["id"], second["id"], third["id"]}


def test_pending_request_uses_new_auto_policy_and_joins_as_viewer(domain_core: TestClient) -> None:
    client = domain_core
    org_id = client.org_id  # type: ignore[attr-defined]
    requester = _as_requester(client)
    pending = _request(client, org_id, "join-request-before-policy-01").json()["request"]

    _as_owner(client)
    changed = client.patch(
        f"/v1/orgs/{org_id}/domains/college.edu",
        json={"join_policy": "auto"},
        headers=_headers("domain-policy-auto-change-01"),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["join_policy"] == "auto"

    _use_session(client, requester)
    auto = _request(client, org_id, "join-request-auto-after-policy-01")
    assert auto.status_code == 201, auto.text
    assert auto.json()["joined"] is True
    assert auto.json()["request"]["status"] == "approved"
    assert auto.json()["request"]["role"] == "viewer"
    requests = client.get("/v1/me").json()["memberships"]
    assert any(org["id"] == org_id and org["roles"] == ["viewer"] for org in requests)

    _as_owner(client)
    history = client.get(f"/v1/orgs/{org_id}/join-requests").json()
    assert any(row["id"] == pending["id"] and row["status"] == "cancelled" for row in history)
    assert any(row["status"] == "approved" and row["decision_source"] == "auto" for row in history)
    assert any(
        "joined Nava College as a viewer" in body
        for _, _, body in client.app.state.domain_joins.mailer.messages
    )


@pytest.mark.parametrize(
    ("email", "hosted_domain", "verified", "expected_code"),
    [
        ("member@college.edu", None, True, "DOMAIN_JOIN_VERIFICATION_REQUIRED"),
        ("member@wrong.edu", "college.edu", True, "DOMAIN_JOIN_VERIFICATION_REQUIRED"),
        ("member@college.edu", "college.edu", False, "EMAIL_VERIFICATION_REQUIRED"),
    ],
)
def test_join_requires_verified_google_email_and_matching_hosted_domain(
    domain_core: TestClient,
    email: str,
    hosted_domain: str | None,
    verified: bool,
    expected_code: str,
) -> None:
    client = domain_core
    _as_requester(client, email, hosted_domain, verified=verified)
    response = _request(client, client.org_id, "join-invalid-google-identity-01")  # type: ignore[attr-defined]
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == expected_code


@pytest.mark.parametrize(
    ("email", "hosted_domain", "verified", "expected_code"),
    [
        ("owner@college.edu", None, True, "DOMAIN_IDENTITY_MISMATCH"),
        ("owner@wrong.edu", "college.edu", True, "DOMAIN_IDENTITY_MISMATCH"),
        ("owner@college.edu", "college.edu", False, "EMAIL_VERIFICATION_REQUIRED"),
    ],
)
def test_domain_verification_rejects_missing_wrong_or_unverified_google_claims(
    domain_core: TestClient,
    email: str,
    hosted_domain: str | None,
    verified: bool,
    expected_code: str,
) -> None:
    client = domain_core
    org_id = client.org_id  # type: ignore[attr-defined]
    _as_owner(client)
    added = client.post(
        f"/v1/orgs/{org_id}/domains",
        json={"domain": "claimed.edu", "verification": "google_hd"},
        headers=_headers("domain-add-claim-check-01"),
    )
    assert added.status_code == 201, added.text
    token = _google_session(
        client.db_url,  # type: ignore[attr-defined]
        client.user_ids["operator"],  # type: ignore[attr-defined]
        email,
        hosted_domain,
        verified=verified,
    )
    _use_session(client, token)
    response = client.post(
        f"/v1/orgs/{org_id}/domains/claimed.edu/verify",
        headers=_headers("domain-verify-claim-check-01"),
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == expected_code


def test_consumer_domains_are_refused_and_dns_txt_claims_are_checked(
    domain_core: TestClient,
) -> None:
    client = domain_core
    org_id = client.org_id  # type: ignore[attr-defined]
    consumer = client.post(
        f"/v1/orgs/{org_id}/domains",
        json={"domain": "gmail.com", "verification": "google_hd"},
        headers=_headers("domain-add-consumer-0001"),
    )
    assert consumer.status_code == 422
    assert consumer.json()["error"]["code"] == "PUBLIC_EMAIL_DOMAIN"

    added = client.post(
        f"/v1/orgs/{org_id}/domains",
        json={"domain": "dns-college.edu", "verification": "dns_txt"},
        headers=_headers("domain-add-dns-claim-0001"),
    )
    assert added.status_code == 201, added.text
    challenge = added.json()
    assert challenge["verification_name"] == "_pramana-verify.dns-college.edu"
    assert challenge["verification_value"].startswith("pramana-verification=")

    missing = client.post(
        f"/v1/orgs/{org_id}/domains/dns-college.edu/verify",
        headers=_headers("domain-verify-dns-missing-01"),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "DOMAIN_TXT_NOT_FOUND"

    client.resolver.records.add(challenge["verification_value"])  # type: ignore[attr-defined]
    verified = client.post(
        f"/v1/orgs/{org_id}/domains/dns-college.edu/verify",
        headers=_headers("domain-verify-dns-present-01"),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verified_at"] is not None


def test_other_organization_join_request_id_is_not_visible_or_decidable(
    domain_core: TestClient,
) -> None:
    client = domain_core
    org_id = client.org_id  # type: ignore[attr-defined]
    requester = _as_requester(client)
    request = _request(client, org_id, "join-request-for-foreign-test-01").json()["request"]
    _as_owner(client)

    second = client.post(
        "/v1/orgs",
        json={"name": "Other College"},
        headers=_headers("domain-second-org-create-01"),
    )
    assert second.status_code == 201, second.text
    foreign_org = second.json()["organization"]["id"]
    response = client.post(
        f"/v1/orgs/{foreign_org}/join-requests/{request['id']}/approve",
        json={"role": "admin"},
        headers=_headers("join-foreign-request-approve-01"),
    )
    assert response.status_code == 404, response.text
    cancel = client.post(
        f"/v1/join-requests/{request['id']}/cancel",
        headers=_headers("join-foreign-request-cancel-01"),
    )
    assert cancel.status_code == 404, cancel.text
    _use_session(client, requester)
    foreign = _request(client, foreign_org, "join-foreign-workspace-request-01")
    assert foreign.status_code == 404, foreign.text


def test_verified_domain_claim_cannot_be_owned_by_two_workspaces(domain_core: TestClient) -> None:
    client = domain_core
    resolver = client.resolver  # type: ignore[attr-defined]
    org_id = client.org_id  # type: ignore[attr-defined]
    claimed = client.post(
        f"/v1/orgs/{org_id}/domains",
        json={"domain": "contested.edu", "verification": "dns_txt"},
        headers=_headers("domain-add-contested-first-01"),
    )
    assert claimed.status_code == 201, claimed.text
    resolver.records.add(claimed.json()["verification_value"])
    checked = client.post(
        f"/v1/orgs/{org_id}/domains/contested.edu/verify",
        headers=_headers("domain-verify-contested-first-01"),
    )
    assert checked.status_code == 200, checked.text

    other = client.post(
        "/v1/orgs",
        json={"name": "Another College"},
        headers=_headers("domain-contested-second-org-01"),
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["organization"]["id"]
    second_claim = client.post(
        f"/v1/orgs/{other_id}/domains",
        json={"domain": "contested.edu", "verification": "dns_txt"},
        headers=_headers("domain-add-contested-second-01"),
    )
    assert second_claim.status_code == 201, second_claim.text
    # The second claim has a distinct nonce, so a second token cannot verify against the first.
    resolver.records.add(second_claim.json()["verification_value"])
    contested = client.post(
        f"/v1/orgs/{other_id}/domains/contested.edu/verify",
        headers=_headers("domain-verify-contested-second-01"),
    )
    assert contested.status_code == 409, contested.text
    assert contested.json()["error"]["code"] == "DOMAIN_ALREADY_CLAIMED"
